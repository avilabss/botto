"""Smoke tests for scaffold package layout."""

from __future__ import annotations

import importlib

SCAFFOLD_MODULES = (
    "android_game_automator.core",
    "android_game_automator.backends",
    "android_game_automator.backends.adb",
    "android_game_automator.vision",
    "android_game_automator.runtime",
    "android_game_automator.artifacts",
    "botto",
)


def test_scaffold_modules_are_importable() -> None:
    for module_name in SCAFFOLD_MODULES:
        module = importlib.import_module(module_name)
        assert module is not None
