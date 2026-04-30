"""Smoke tests for scaffold package layout."""

from __future__ import annotations

import importlib

SCAFFOLD_MODULES = (
    "android_game_automator.types",
    "android_game_automator.image",
    "android_game_automator.vision",
    "android_game_automator.ocr",
    "android_game_automator.artifacts",
    "android_game_automator.adb",
    "botto",
)


def test_scaffold_modules_are_importable() -> None:
    for module_name in SCAFFOLD_MODULES:
        module = importlib.import_module(module_name)
        assert module is not None
