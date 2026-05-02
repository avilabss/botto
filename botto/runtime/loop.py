"""Read-only frame runtime loop and background analysis coordination."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from time import monotonic
from typing import Protocol, TypeGuard

from android_game_automator.image import FrameImage
from android_game_automator.scrcpy import ScrcpyFrameSource
from android_game_automator.types import SessionInfo

from android_game_automator.adb import AdbDeviceBackend
from botto.automation.actions import ActionBackend, ActionExecutor
from botto.detection import ScreenAnalysis, analyze_screen

from .config import (
    DEFAULT_CLASH_PACKAGE,
    DEFAULT_RUNTIME_ANALYZE_EVERY_SECONDS,
    DEFAULT_RUNTIME_MAX_FPS,
)
from .state import RuntimeAnalysisSnapshot, RuntimeLoopState

type RuntimeClock = Callable[[], float]


_LOGGER = logging.getLogger(__name__)


class RuntimeScreenAnalyzer(Protocol):
    """Callable used by the runtime to analyze throttled frames."""

    def __call__(self, image: FrameImage) -> ScreenAnalysis: ...


class RuntimeSession(Protocol):
    """ADB session operations used by the read-only runtime."""

    @property
    def info(self) -> SessionInfo: ...

    async def close(self) -> None: ...

    async def launch_app(self, package_name: str) -> None: ...


class RuntimeBackend(Protocol):
    """Backend operations used by the read-only runtime."""

    async def open_session(self, device_id: str | None = None) -> RuntimeSession: ...


class RuntimeFrameSource(Protocol):
    """Read-only frame source operations used by the runtime."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def latest_frame(self) -> FrameImage | None: ...


class RuntimeFrameSourceFactory(Protocol):
    """Factory for creating a source once the ADB device id is resolved."""

    def __call__(self, *, serial: str, max_fps: int) -> RuntimeFrameSource: ...


class RuntimeLoopSink(Protocol):
    """Receives current read-only runtime state and returns whether to continue."""

    def __call__(self, state: RuntimeLoopState) -> bool: ...


@dataclass(frozen=True, slots=True)
class _PendingRuntimeAnalysis:
    future: Future[ScreenAnalysis]
    started_at: float
    frame_id: str | None


async def run_read_only_runtime(
    *,
    sink: RuntimeLoopSink,
    device_id: str | None = None,
    package_name: str = DEFAULT_CLASH_PACKAGE,
    launch: bool = True,
    max_fps: int = DEFAULT_RUNTIME_MAX_FPS,
    analyze_every_seconds: float = DEFAULT_RUNTIME_ANALYZE_EVERY_SECONDS,
    backend: RuntimeBackend | None = None,
    source_factory: RuntimeFrameSourceFactory | None = None,
    screen_analyzer: RuntimeScreenAnalyzer | None = None,
    clock: RuntimeClock = monotonic,
) -> None:
    """Run the read-only frame loop and deliver state to ``sink``."""

    if not package_name.strip():
        raise ValueError("package_name must be non-empty")
    if isinstance(max_fps, bool) or max_fps < 0:
        raise ValueError("max_fps must be >= 0")
    if analyze_every_seconds <= 0:
        raise ValueError("analyze_every_seconds must be > 0")

    resolved_backend = backend if backend is not None else AdbDeviceBackend()
    resolved_source_factory = (
        source_factory if source_factory is not None else _default_runtime_frame_source_factory
    )
    analyzer = screen_analyzer if screen_analyzer is not None else analyze_screen

    _LOGGER.debug("Opening runtime session for device %s", device_id or "default")
    session = await resolved_backend.open_session(device_id)
    source: RuntimeFrameSource | None = None
    latest_snapshot: RuntimeAnalysisSnapshot | None = None
    last_analysis_started_at: float | None = None
    pending_analysis: _PendingRuntimeAnalysis | None = None
    analysis_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="botto-runtime-analysis",
    )

    def complete_pending_analysis_if_ready() -> RuntimeAnalysisSnapshot | None:
        nonlocal latest_snapshot, pending_analysis
        if pending_analysis is not None and pending_analysis.future.done():
            latest_snapshot = _completed_runtime_analysis_snapshot(pending_analysis, clock=clock)
            pending_analysis = None
        return latest_snapshot

    try:
        if launch:
            _LOGGER.debug("Launching package %s", package_name)
            await session.launch_app(package_name)

        serial = session.info.device.identity.device_id
        source = resolved_source_factory(serial=serial, max_fps=max_fps)
        _LOGGER.debug("Starting frame source for device %s", serial)
        source.start()
        action_executor = _action_executor_for_source(source)

        while True:
            complete_pending_analysis_if_ready()

            frame = source.latest_frame()
            frame_time = clock()
            if (
                frame is not None
                and pending_analysis is None
                and (
                    last_analysis_started_at is None
                    or frame_time - last_analysis_started_at >= analyze_every_seconds
                )
            ):
                last_analysis_started_at = frame_time
                pending_analysis = _start_runtime_analysis(
                    analyzer,
                    frame,
                    started_at=frame_time,
                    executor=analysis_executor,
                )

            state = RuntimeLoopState(
                frame=frame,
                analysis_snapshot=latest_snapshot,
                now=frame_time,
                analysis_running=pending_analysis is not None,
                session_info=session.info,
                action_executor=action_executor,
                _analysis_snapshot_refresher=complete_pending_analysis_if_ready,
            )
            if not sink(state):
                _LOGGER.debug("Runtime sink requested stop")
                break
            await asyncio.sleep(0)
    finally:
        try:
            if source is not None:
                _LOGGER.debug("Stopping frame source")
                source.stop()
        finally:
            try:
                _LOGGER.debug("Closing runtime session")
                await session.close()
            finally:
                try:
                    if pending_analysis is not None:
                        _LOGGER.debug("Waiting for pending runtime analysis")
                    await _finish_pending_runtime_analysis(pending_analysis)
                finally:
                    analysis_executor.shutdown(wait=True, cancel_futures=True)
                    _LOGGER.debug("Runtime cleanup complete")


def _start_runtime_analysis(
    analyzer: RuntimeScreenAnalyzer,
    frame: FrameImage,
    *,
    started_at: float,
    executor: ThreadPoolExecutor,
) -> _PendingRuntimeAnalysis:
    return _PendingRuntimeAnalysis(
        future=executor.submit(analyzer, frame),
        started_at=started_at,
        frame_id=frame.frame_id,
    )


def _completed_runtime_analysis_snapshot(
    pending: _PendingRuntimeAnalysis,
    *,
    clock: RuntimeClock,
) -> RuntimeAnalysisSnapshot:
    analysis = pending.future.result()
    finished_at = clock()
    return RuntimeAnalysisSnapshot(
        analysis=analysis,
        analyzed_at=finished_at,
        duration_seconds=max(0.0, finished_at - pending.started_at),
        frame_id=pending.frame_id,
    )


async def _finish_pending_runtime_analysis(pending: _PendingRuntimeAnalysis | None) -> None:
    if pending is None:
        return

    await asyncio.shield(asyncio.wrap_future(pending.future))


def _default_runtime_frame_source_factory(
    *,
    serial: str,
    max_fps: int,
) -> RuntimeFrameSource:
    return ScrcpyFrameSource(serial=serial, max_fps=max_fps)


def _action_executor_for_source(source: RuntimeFrameSource) -> ActionExecutor | None:
    if not _source_supports_action_backend(source):
        _LOGGER.debug("Frame source does not expose action backend; automation input unavailable")
        return None
    return ActionExecutor(source)


def _source_supports_action_backend(source: object) -> TypeGuard[ActionBackend]:
    return (
        "action_surface_size" in dir(source)
        and callable(getattr(source, "tap_pixels", None))
        and callable(getattr(source, "swipe_pixels", None))
    )


__all__ = [
    "RuntimeBackend",
    "RuntimeClock",
    "RuntimeFrameSource",
    "RuntimeFrameSourceFactory",
    "RuntimeLoopSink",
    "RuntimeScreenAnalyzer",
    "RuntimeSession",
    "run_read_only_runtime",
]
