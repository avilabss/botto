"""Read-only scrcpy live debug flows for Botto."""

from __future__ import annotations

from botto.live.debug import (
    DEFAULT_LIVE_DEBUG_ANALYZE_EVERY_SECONDS,
    DEFAULT_LIVE_DEBUG_WINDOW_TITLE,
    DebugOverlayRenderer,
    LiveAnalysisSnapshot,
    LiveDebugBackend,
    LiveDebugFrameSource,
    LiveDebugFrameSourceFactory,
    LiveDebugSession,
    LiveScreenAnalyzer,
    run_live_debug,
)
from botto.live.overlay import render_debug_overlay
from botto.live.window import (
    EXIT_KEY_CODES,
    OpenCvPreviewWindow,
    PreviewWindow,
    frame_image_to_bgr_array,
)

__all__ = [
    "DEFAULT_LIVE_DEBUG_ANALYZE_EVERY_SECONDS",
    "DEFAULT_LIVE_DEBUG_WINDOW_TITLE",
    "DebugOverlayRenderer",
    "EXIT_KEY_CODES",
    "LiveAnalysisSnapshot",
    "LiveDebugBackend",
    "LiveDebugFrameSource",
    "LiveDebugFrameSourceFactory",
    "LiveDebugSession",
    "LiveScreenAnalyzer",
    "OpenCvPreviewWindow",
    "PreviewWindow",
    "frame_image_to_bgr_array",
    "render_debug_overlay",
    "run_live_debug",
]
