"""Defaults for Botto's read-only runtime loop."""

from __future__ import annotations

from android_game_automator.scrcpy import DEFAULT_SCRCPY_MAX_FPS

DEFAULT_CLASH_PACKAGE = "com.supercell.clashofclans"
DEFAULT_RUNTIME_ANALYZE_EVERY_SECONDS = 1.0
DEFAULT_RUNTIME_MAX_FPS = DEFAULT_SCRCPY_MAX_FPS

__all__ = [
    "DEFAULT_CLASH_PACKAGE",
    "DEFAULT_RUNTIME_ANALYZE_EVERY_SECONDS",
    "DEFAULT_RUNTIME_MAX_FPS",
]
