"""Read-only runtime loop primitives for Botto."""

from __future__ import annotations

from .config import (
    DEFAULT_CLASH_PACKAGE,
    DEFAULT_RUNTIME_ANALYZE_EVERY_SECONDS,
    DEFAULT_RUNTIME_MAX_FPS,
)
from .loop import (
    RuntimeBackend,
    RuntimeClock,
    RuntimeFrameSource,
    RuntimeFrameSourceFactory,
    RuntimeLoopSink,
    RuntimeScreenAnalyzer,
    RuntimeSession,
    run_read_only_runtime,
)
from .state import RuntimeAnalysisSnapshot, RuntimeLoopState

__all__ = [
    "DEFAULT_CLASH_PACKAGE",
    "DEFAULT_RUNTIME_ANALYZE_EVERY_SECONDS",
    "DEFAULT_RUNTIME_MAX_FPS",
    "RuntimeAnalysisSnapshot",
    "RuntimeBackend",
    "RuntimeClock",
    "RuntimeFrameSource",
    "RuntimeFrameSourceFactory",
    "RuntimeLoopSink",
    "RuntimeLoopState",
    "RuntimeScreenAnalyzer",
    "RuntimeSession",
    "run_read_only_runtime",
]
