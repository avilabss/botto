"""Smoke tests for the project CLI entrypoint."""

from __future__ import annotations

import subprocess
import sys


def test_module_entrypoint_runs() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "android_game_automator"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "android game automator sdk is ready" in completed.stdout.lower()


def test_module_entrypoint_help() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "android_game_automator", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Android Game Automator SDK CLI." in completed.stdout


def test_module_entrypoint_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "android_game_automator", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.startswith("android-game-automator ")


def test_botto_module_entrypoint_runs() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "botto"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Botto reference CLI built on android_game_automator." in completed.stdout


def test_botto_module_entrypoint_help() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "botto", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "{devices,session,capture}" in completed.stdout
