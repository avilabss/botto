"""Smoke tests for the Botto CLI entrypoint."""

from __future__ import annotations

import subprocess
import sys
from importlib import metadata


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
    assert "live-preview" in completed.stdout
    assert "live-debug" in completed.stdout


def test_botto_module_entrypoint_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "botto", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == f"botto {metadata.version('botto')}\n"
