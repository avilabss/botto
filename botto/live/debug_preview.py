"""Debug preview UI sink for the read-only runtime loop."""

from __future__ import annotations

import logging
from collections.abc import Callable
from os import PathLike
from time import monotonic
from typing import Protocol

from android_game_automator.artifacts import ArtifactStore
from android_game_automator.image import FrameImage
from android_game_automator.types import SessionInfo

from botto.runtime import (
    DEFAULT_CLASH_PACKAGE,
    DEFAULT_RUNTIME_ANALYZE_EVERY_SECONDS,
    DEFAULT_RUNTIME_MAX_FPS,
    RuntimeAnalysisSnapshot,
    RuntimeBackend,
    RuntimeFrameSource,
    RuntimeFrameSourceFactory,
    RuntimeLoopState,
    RuntimeScreenAnalyzer,
    RuntimeSession,
    run_read_only_runtime,
)

from .artifacts import (
    _SAVE_STATUS_SECONDS,
    _debug_preview_artifact_label,
    _debug_preview_artifact_selection,
    _debug_preview_overlay_save_message,
    _debug_preview_stdout_save_message,
    _save_debug_preview_artifacts,
    _SavedDebugPreviewArtifacts,
)
from .overlay import render_debug_overlay
from .window import EXIT_KEY_CODES, OpenCvPreviewWindow, PreviewWindow

DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE = "Botto debug preview"
DEFAULT_DEBUG_PREVIEW_ANALYZE_EVERY_SECONDS = DEFAULT_RUNTIME_ANALYZE_EVERY_SECONDS
DEFAULT_ARTIFACT_ROOT = ".botto-artifacts"

_LOGGER = logging.getLogger(__name__)

DebugPreviewAnalysisSnapshot = RuntimeAnalysisSnapshot
DebugPreviewBackend = RuntimeBackend
DebugPreviewFrameSource = RuntimeFrameSource
DebugPreviewFrameSourceFactory = RuntimeFrameSourceFactory
DebugPreviewSession = RuntimeSession
DebugPreviewScreenAnalyzer = RuntimeScreenAnalyzer

type ClockFn = Callable[[], float]
type StatusWriter = Callable[[str], None]
type DebugPreviewRuntimeStateHook = Callable[[RuntimeLoopState], bool]


class DebugOverlayRenderer(Protocol):
    """Callable that annotates a frame with the latest debug preview state."""

    def __call__(
        self,
        frame: FrameImage,
        snapshot: DebugPreviewAnalysisSnapshot | None,
        *,
        now: float | None = None,
        analysis_running: bool = False,
    ) -> FrameImage: ...


async def run_debug_preview(
    *,
    device_id: str | None = None,
    package_name: str = DEFAULT_CLASH_PACKAGE,
    launch: bool = True,
    max_fps: int = DEFAULT_RUNTIME_MAX_FPS,
    window_title: str = DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE,
    analyze_every_seconds: float = DEFAULT_DEBUG_PREVIEW_ANALYZE_EVERY_SECONDS,
    artifact_root: str | PathLike[str] = DEFAULT_ARTIFACT_ROOT,
    run_name: str | None = None,
    backend: DebugPreviewBackend | None = None,
    source_factory: DebugPreviewFrameSourceFactory | None = None,
    preview_window: PreviewWindow | None = None,
    screen_analyzer: DebugPreviewScreenAnalyzer | None = None,
    overlay_renderer: DebugOverlayRenderer | None = None,
    status_writer: StatusWriter | None = None,
    runtime_state_hook: DebugPreviewRuntimeStateHook | None = None,
    clock: ClockFn = monotonic,
) -> None:
    """Display scrcpy frames with throttled read-only detector annotations."""

    if not package_name.strip():
        raise ValueError("package_name must be non-empty")
    if isinstance(max_fps, bool) or max_fps < 0:
        raise ValueError("max_fps must be >= 0")
    if not window_title.strip():
        raise ValueError("window_title must be non-empty")
    if analyze_every_seconds <= 0:
        raise ValueError("analyze_every_seconds must be > 0")

    window = preview_window if preview_window is not None else OpenCvPreviewWindow()
    window_opened = False
    artifact_store: ArtifactStore | None = None
    artifact_sequence = 0
    save_status_message: str | None = None
    save_status_until = 0.0

    def ensure_window_open() -> None:
        nonlocal window_opened
        if not window_opened:
            window.open(window_title)
            window_opened = True
            _LOGGER.debug("Opened debug preview window %s", window_title)

    def close_window_if_open() -> None:
        nonlocal window_opened
        if window_opened:
            window.close(window_title)
            window_opened = False
            _LOGGER.debug("Closed debug preview window %s", window_title)

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
        snapshot: DebugPreviewAnalysisSnapshot | None,
        session_info: SessionInfo,
        now: float,
    ) -> _SavedDebugPreviewArtifacts | None:
        nonlocal artifact_sequence, save_status_message, save_status_until

        selection = _debug_preview_artifact_selection(key_code)
        if selection is None:
            return None

        kind, hotkey = selection
        image = raw_frame if kind == "raw" else annotated_frame
        artifact_sequence += 1
        label = _debug_preview_artifact_label(kind=kind, sequence=artifact_sequence)
        saved = _save_debug_preview_artifacts(
            store=get_artifact_store(),
            label=label,
            kind=kind,
            hotkey=hotkey,
            image=image,
            snapshot=snapshot,
            session_info=session_info,
            package_name=package_name,
            launched=launch,
        )
        save_status_message = _debug_preview_overlay_save_message(saved)
        save_status_until = now + _SAVE_STATUS_SECONDS
        status_message = _debug_preview_stdout_save_message(saved)
        _LOGGER.info(status_message)
        if status_writer is not None:
            status_writer(status_message)
        return saved

    def handle_runtime_state(state: RuntimeLoopState) -> bool:
        nonlocal save_status_message

        ensure_window_open()
        frame_time = state.now
        frame = state.frame
        if frame is None:
            if window.wait_key(1) in EXIT_KEY_CODES:
                _LOGGER.info("Debug preview exit requested")
                close_window_if_open()
                return False
            return True

        if save_status_message is not None and frame_time > save_status_until:
            save_status_message = None
        active_save_status = save_status_message
        snapshot = state.analysis_snapshot
        if overlay_renderer is None:
            annotated_frame = render_debug_overlay(
                frame,
                snapshot,
                now=frame_time,
                analysis_running=state.analysis_running,
                status_message=active_save_status,
            )
        else:
            annotated_frame = overlay_renderer(
                frame,
                snapshot,
                now=frame_time,
                analysis_running=state.analysis_running,
            )
        window.show(window_title, annotated_frame)
        key_code = window.wait_key(1)
        if key_code in EXIT_KEY_CODES:
            _LOGGER.info("Debug preview exit requested")
            close_window_if_open()
            return False
        snapshot_for_save = snapshot
        if _debug_preview_artifact_selection(key_code) is not None:
            snapshot_for_save = state.refresh_analysis_snapshot()
        save_artifacts_for_hotkey(
            key_code=key_code,
            raw_frame=frame,
            annotated_frame=annotated_frame,
            snapshot=snapshot_for_save,
            session_info=state.session_info,
            now=frame_time,
        )
        if runtime_state_hook is not None and not runtime_state_hook(state):
            _LOGGER.debug("Debug preview runtime hook requested stop")
            close_window_if_open()
            return False
        return True

    try:
        _LOGGER.info("Starting debug preview")
        await run_read_only_runtime(
            sink=handle_runtime_state,
            device_id=device_id,
            package_name=package_name,
            launch=launch,
            max_fps=max_fps,
            analyze_every_seconds=analyze_every_seconds,
            backend=backend,
            source_factory=source_factory,
            screen_analyzer=screen_analyzer,
            clock=clock,
        )
    finally:
        close_window_if_open()
        _LOGGER.debug("Debug preview finished")


__all__ = [
    "DEFAULT_DEBUG_PREVIEW_ANALYZE_EVERY_SECONDS",
    "DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE",
    "DebugPreviewAnalysisSnapshot",
    "DebugPreviewBackend",
    "DebugPreviewFrameSource",
    "DebugPreviewFrameSourceFactory",
    "DebugPreviewRuntimeStateHook",
    "DebugPreviewScreenAnalyzer",
    "DebugPreviewSession",
    "DebugOverlayRenderer",
    "run_debug_preview",
]
