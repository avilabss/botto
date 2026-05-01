"""Live scrcpy debug loop and background analysis coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from os import PathLike
from time import monotonic
from typing import Protocol

from android_game_automator.artifacts import ArtifactStore
from android_game_automator.image import FrameImage
from android_game_automator.scrcpy import DEFAULT_SCRCPY_MAX_FPS, ScrcpyFrameSource
from android_game_automator.types import SessionInfo

from android_game_automator.adb import AdbDeviceBackend
from botto.detection import ScreenAnalysis, analyze_screen

from .artifacts import (
    _SAVE_STATUS_SECONDS,
    _live_debug_artifact_label,
    _live_debug_artifact_selection,
    _live_debug_overlay_save_message,
    _live_debug_stdout_save_message,
    _save_live_debug_artifacts,
    _SavedLiveDebugArtifacts,
)
from .overlay import render_debug_overlay
from .window import EXIT_KEY_CODES, OpenCvPreviewWindow, PreviewWindow

DEFAULT_CLASH_PACKAGE = "com.supercell.clashofclans"
DEFAULT_LIVE_DEBUG_WINDOW_TITLE = "Botto live debug"
DEFAULT_LIVE_DEBUG_ANALYZE_EVERY_SECONDS = 1.0
DEFAULT_ARTIFACT_ROOT = ".botto-artifacts"

type ClockFn = Callable[[], float]
type StatusWriter = Callable[[str], None]


class LiveScreenAnalyzer(Protocol):
    """Callable used by live debug to analyze throttled frames."""

    def __call__(self, image: FrameImage) -> ScreenAnalysis: ...


class LiveDebugSession(Protocol):
    """ADB session operations used by live debug."""

    @property
    def info(self) -> SessionInfo: ...

    async def close(self) -> None: ...

    async def launch_app(self, package_name: str) -> None: ...


class LiveDebugBackend(Protocol):
    """Backend operations used by live debug."""

    async def open_session(self, device_id: str | None = None) -> LiveDebugSession: ...


class LiveDebugFrameSource(Protocol):
    """Read-only frame source operations used by live debug."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def latest_frame(self) -> FrameImage | None: ...

    def frames(self) -> Iterator[FrameImage]: ...


class LiveDebugFrameSourceFactory(Protocol):
    """Factory for creating a source once the ADB device id is resolved."""

    def __call__(self, *, serial: str, max_fps: int) -> LiveDebugFrameSource: ...


@dataclass(frozen=True, slots=True)
class LiveAnalysisSnapshot:
    """Latest screen analysis plus timing metadata for overlay display."""

    analysis: ScreenAnalysis
    analyzed_at: float
    duration_seconds: float | None = None
    frame_id: str | None = None


class DebugOverlayRenderer(Protocol):
    """Callable that annotates a frame with the latest live debug state."""

    def __call__(
        self,
        frame: FrameImage,
        snapshot: LiveAnalysisSnapshot | None,
        *,
        now: float | None = None,
        analysis_running: bool = False,
    ) -> FrameImage: ...


@dataclass(frozen=True, slots=True)
class _PendingLiveAnalysis:
    future: asyncio.Future[ScreenAnalysis]
    started_at: float
    frame_id: str | None


async def run_live_debug(
    *,
    device_id: str | None = None,
    package_name: str = DEFAULT_CLASH_PACKAGE,
    launch: bool = True,
    max_fps: int = DEFAULT_SCRCPY_MAX_FPS,
    window_title: str = DEFAULT_LIVE_DEBUG_WINDOW_TITLE,
    analyze_every_seconds: float = DEFAULT_LIVE_DEBUG_ANALYZE_EVERY_SECONDS,
    artifact_root: str | PathLike[str] = DEFAULT_ARTIFACT_ROOT,
    run_name: str | None = None,
    backend: LiveDebugBackend | None = None,
    source_factory: LiveDebugFrameSourceFactory | None = None,
    preview_window: PreviewWindow | None = None,
    screen_analyzer: LiveScreenAnalyzer | None = None,
    overlay_renderer: DebugOverlayRenderer | None = None,
    status_writer: StatusWriter | None = None,
    clock: ClockFn = monotonic,
) -> None:
    """Display live scrcpy frames with throttled read-only detector annotations."""

    if not package_name.strip():
        raise ValueError("package_name must be non-empty")
    if isinstance(max_fps, bool) or max_fps < 0:
        raise ValueError("max_fps must be >= 0")
    if not window_title.strip():
        raise ValueError("window_title must be non-empty")
    if analyze_every_seconds <= 0:
        raise ValueError("analyze_every_seconds must be > 0")

    resolved_backend = backend if backend is not None else AdbDeviceBackend()
    resolved_source_factory = (
        source_factory if source_factory is not None else _default_live_debug_frame_source_factory
    )
    window = preview_window if preview_window is not None else OpenCvPreviewWindow()
    analyzer = screen_analyzer if screen_analyzer is not None else analyze_screen

    session = await resolved_backend.open_session(device_id)
    source: LiveDebugFrameSource | None = None
    window_opened = False
    latest_snapshot: LiveAnalysisSnapshot | None = None
    last_analysis_started_at: float | None = None
    pending_analysis: _PendingLiveAnalysis | None = None
    artifact_store: ArtifactStore | None = None
    artifact_sequence = 0
    save_status_message: str | None = None
    save_status_until = 0.0
    analysis_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="botto-live-debug-analysis",
    )

    def complete_pending_analysis_if_ready() -> None:
        nonlocal latest_snapshot, pending_analysis
        if pending_analysis is not None and pending_analysis.future.done():
            latest_snapshot = _completed_live_analysis_snapshot(pending_analysis, clock=clock)
            pending_analysis = None

    def get_artifact_store() -> ArtifactStore:
        nonlocal artifact_store
        if artifact_store is None:
            artifact_store = ArtifactStore(artifact_root, run_name=run_name)
        return artifact_store

    def save_artifacts_for_hotkey(
        *,
        key_code: int,
        raw_frame: FrameImage,
        annotated_frame: FrameImage,
        now: float,
    ) -> _SavedLiveDebugArtifacts | None:
        nonlocal artifact_sequence, save_status_message, save_status_until

        selection = _live_debug_artifact_selection(key_code)
        if selection is None:
            return None

        kind, hotkey = selection
        image = raw_frame if kind == "raw" else annotated_frame
        complete_pending_analysis_if_ready()
        artifact_sequence += 1
        label = _live_debug_artifact_label(kind=kind, sequence=artifact_sequence)
        saved = _save_live_debug_artifacts(
            store=get_artifact_store(),
            label=label,
            kind=kind,
            hotkey=hotkey,
            image=image,
            snapshot=latest_snapshot,
            session_info=session.info,
            package_name=package_name,
            launched=launch,
        )
        save_status_message = _live_debug_overlay_save_message(saved)
        save_status_until = now + _SAVE_STATUS_SECONDS
        if status_writer is not None:
            status_writer(_live_debug_stdout_save_message(saved))
        return saved

    try:
        if launch:
            await session.launch_app(package_name)

        serial = session.info.device.identity.device_id
        source = resolved_source_factory(serial=serial, max_fps=max_fps)
        source.start()

        window.open(window_title)
        window_opened = True
        while True:
            complete_pending_analysis_if_ready()

            frame = source.latest_frame()
            frame_time = clock()
            if frame is None:
                if window.wait_key(1) in EXIT_KEY_CODES:
                    break
                await asyncio.sleep(0)
                continue

            if pending_analysis is None and (
                last_analysis_started_at is None
                or frame_time - last_analysis_started_at >= analyze_every_seconds
            ):
                last_analysis_started_at = frame_time
                pending_analysis = _start_live_analysis(
                    analyzer,
                    frame,
                    started_at=frame_time,
                    executor=analysis_executor,
                )

            if save_status_message is not None and frame_time > save_status_until:
                save_status_message = None
            active_save_status = save_status_message
            if overlay_renderer is None:
                annotated_frame = render_debug_overlay(
                    frame,
                    latest_snapshot,
                    now=frame_time,
                    analysis_running=pending_analysis is not None,
                    status_message=active_save_status,
                )
            else:
                annotated_frame = overlay_renderer(
                    frame,
                    latest_snapshot,
                    now=frame_time,
                    analysis_running=pending_analysis is not None,
                )
            window.show(window_title, annotated_frame)
            key_code = window.wait_key(1)
            if key_code in EXIT_KEY_CODES:
                break
            save_artifacts_for_hotkey(
                key_code=key_code,
                raw_frame=frame,
                annotated_frame=annotated_frame,
                now=frame_time,
            )
            await asyncio.sleep(0)
    finally:
        try:
            if source is not None:
                source.stop()
        finally:
            try:
                if window_opened:
                    window.close(window_title)
            finally:
                try:
                    await session.close()
                finally:
                    try:
                        await _finish_pending_live_analysis(pending_analysis)
                    finally:
                        analysis_executor.shutdown(wait=True, cancel_futures=True)


def _start_live_analysis(
    analyzer: LiveScreenAnalyzer,
    frame: FrameImage,
    *,
    started_at: float,
    executor: ThreadPoolExecutor,
) -> _PendingLiveAnalysis:
    loop = asyncio.get_running_loop()
    return _PendingLiveAnalysis(
        future=loop.run_in_executor(executor, analyzer, frame),
        started_at=started_at,
        frame_id=frame.frame_id,
    )


def _completed_live_analysis_snapshot(
    pending: _PendingLiveAnalysis,
    *,
    clock: ClockFn,
) -> LiveAnalysisSnapshot:
    analysis = pending.future.result()
    finished_at = clock()
    return LiveAnalysisSnapshot(
        analysis=analysis,
        analyzed_at=finished_at,
        duration_seconds=max(0.0, finished_at - pending.started_at),
        frame_id=pending.frame_id,
    )


async def _finish_pending_live_analysis(pending: _PendingLiveAnalysis | None) -> None:
    if pending is None:
        return

    await asyncio.shield(pending.future)


def _default_live_debug_frame_source_factory(
    *,
    serial: str,
    max_fps: int,
) -> LiveDebugFrameSource:
    return ScrcpyFrameSource(serial=serial, max_fps=max_fps)


__all__ = [
    "DEFAULT_LIVE_DEBUG_ANALYZE_EVERY_SECONDS",
    "DEFAULT_LIVE_DEBUG_WINDOW_TITLE",
    "DebugOverlayRenderer",
    "LiveDebugBackend",
    "LiveDebugFrameSource",
    "LiveDebugFrameSourceFactory",
    "LiveDebugSession",
    "LiveAnalysisSnapshot",
    "LiveScreenAnalyzer",
    "run_live_debug",
]
