"""Read-only scrcpy debug preview flow for Botto."""

from __future__ import annotations

from botto.live.debug_preview import (
    DEFAULT_DEBUG_PREVIEW_ANALYZE_EVERY_SECONDS,
    DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE,
    DebugOverlayRenderer,
    DebugPreviewAnalysisSnapshot,
    DebugPreviewBackend,
    DebugPreviewFrameSource,
    DebugPreviewFrameSourceFactory,
    DebugPreviewRuntimeStateHook,
    DebugPreviewScreenAnalyzer,
    DebugPreviewSession,
    run_debug_preview,
)
from botto.live.overlay import render_debug_overlay
from botto.live.window import (
    EXIT_KEY_CODES,
    OpenCvPreviewWindow,
    PreviewWindow,
    frame_image_to_bgr_array,
)

__all__ = [
    "DEFAULT_DEBUG_PREVIEW_ANALYZE_EVERY_SECONDS",
    "DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE",
    "DebugOverlayRenderer",
    "DebugPreviewAnalysisSnapshot",
    "DebugPreviewBackend",
    "DebugPreviewFrameSource",
    "DebugPreviewFrameSourceFactory",
    "DebugPreviewRuntimeStateHook",
    "DebugPreviewScreenAnalyzer",
    "DebugPreviewSession",
    "EXIT_KEY_CODES",
    "OpenCvPreviewWindow",
    "PreviewWindow",
    "frame_image_to_bgr_array",
    "render_debug_overlay",
    "run_debug_preview",
]
