"""Read-only snapshot decision runtime loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
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
    """Read-only frame source operations used by the runtime.

    Snapshot-loop contract: automation should acquire a single decision frame via
    ``wait_for_frame()``. ``latest_frame()`` remains available as a non-blocking
    helper for callers outside the automation runtime.
    """

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def wait_for_frame(self, *, timeout: float | None = None) -> FrameImage: ...

    def latest_frame(self) -> FrameImage | None: ...


class RuntimeFrameSourceFactory(Protocol):
    """Factory for creating a source once the ADB device id is resolved."""

    def __call__(self, *, serial: str, max_fps: int) -> RuntimeFrameSource: ...


class RuntimeLoopSink(Protocol):
    """Receives current read-only runtime state and returns whether to continue."""

    def __call__(self, state: RuntimeLoopState) -> bool: ...


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
            tick_started_at = clock()
            frame = source.wait_for_frame()
            snapshot = _analyze_runtime_frame(analyzer, frame, clock=clock)

            state = RuntimeLoopState(
                frame=frame,
                analysis_snapshot=snapshot,
                now=snapshot.analyzed_at,
                analysis_running=False,
                session_info=session.info,
                action_executor=action_executor,
            )
            if not sink(state):
                _LOGGER.debug("Runtime sink requested stop")
                break
            await _throttle_next_runtime_tick(
                tick_started_at=tick_started_at,
                analyze_every_seconds=analyze_every_seconds,
                clock=clock,
            )
    finally:
        try:
            if source is not None:
                _LOGGER.debug("Stopping frame source")
                source.stop()
        finally:
            _LOGGER.debug("Closing runtime session")
            await session.close()
            _LOGGER.debug("Runtime cleanup complete")


def _analyze_runtime_frame(
    analyzer: RuntimeScreenAnalyzer,
    frame: FrameImage,
    *,
    clock: RuntimeClock,
) -> RuntimeAnalysisSnapshot:
    started_at = clock()
    analysis = analyzer(frame)
    finished_at = clock()
    return RuntimeAnalysisSnapshot(
        analysis=analysis,
        analyzed_at=finished_at,
        duration_seconds=max(0.0, finished_at - started_at),
        frame_id=frame.frame_id,
    )


async def _throttle_next_runtime_tick(
    *,
    tick_started_at: float,
    analyze_every_seconds: float,
    clock: RuntimeClock,
) -> None:
    elapsed_seconds = max(0.0, clock() - tick_started_at)
    sleep_seconds = analyze_every_seconds - elapsed_seconds
    if sleep_seconds <= 0:
        return

    await asyncio.sleep(sleep_seconds)


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
