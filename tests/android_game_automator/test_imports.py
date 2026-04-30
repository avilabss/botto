"""Smoke tests for current package layout."""

from __future__ import annotations

import importlib

IMPORTABLE_MODULES = (
    "android_game_automator.types",
    "android_game_automator.image",
    "android_game_automator.vision",
    "android_game_automator.ocr",
    "android_game_automator.artifacts",
    "android_game_automator.adb",
    "botto",
)


def test_current_modules_are_importable() -> None:
    for module_name in IMPORTABLE_MODULES:
        module = importlib.import_module(module_name)
        assert module is not None
