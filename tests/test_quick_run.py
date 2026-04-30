"""Smoke tests for the local quick_run learning harness."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import android_game_automator.adb as adb_backend
import pytest
from android_game_automator.image import FrameImage
from android_game_automator.types import PixelFormat, Size

QUICK_RUN_PATH = Path(__file__).parents[1] / "quick_run.py"
pytestmark = pytest.mark.skipif(
    not QUICK_RUN_PATH.exists(),
    reason="quick_run.py is a local learning harness and is not present",
)


@dataclass(frozen=True, slots=True)
class FakeIdentity:
    device_id: str
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class FakeDeviceInfo:
    identity: FakeIdentity


def test_quick_run_import_does_not_start_adb(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailAdbDeviceBackend:
        def __init__(self) -> None:
            raise AssertionError("quick_run should not connect to ADB on import")

    monkeypatch.setattr(adb_backend, "AdbDeviceBackend", FailAdbDeviceBackend)
    sys.modules.pop("quick_run", None)
    try:
        module = importlib.import_module("quick_run")
    finally:
        sys.modules.pop("quick_run", None)

    assert module.CLASH_PACKAGE == "com.supercell.clashofclans"
    assert inspect.iscoroutinefunction(module.main)


def test_quick_run_main_launches_captures_saves_and_closes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sys.modules.pop("quick_run", None)
    try:
        module = importlib.import_module("quick_run")
    finally:
        sys.modules.pop("quick_run", None)

    events: list[tuple[str, object]] = []
    image = FrameImage(
        size=Size(width=1, height=1),
        pixel_format=PixelFormat.RGBA32,
        data=bytes((1, 2, 3, 255)),
        captured_at=datetime.now(UTC),
        frame_id="frame-1",
    )

    class FakeSession:
        info = SimpleNamespace(
            device=SimpleNamespace(
                identity=FakeIdentity(device_id="device-1", display_name="Pixel Test")
            )
        )

        async def __aenter__(self) -> FakeSession:
            events.append(("enter", None))
            return self

        async def __aexit__(self, *_args: object) -> None:
            events.append(("exit", None))

        async def launch_app(self, package_name: str) -> None:
            events.append(("launch", package_name))

        async def screenshot(self) -> FrameImage:
            events.append(("screenshot", None))
            return image

        async def close_app(self, package_name: str) -> None:
            events.append(("close", package_name))

    class FakeAdbDeviceBackend:
        async def open_session(self, device_id: str | None = None) -> FakeSession:
            events.append(("open_session", device_id))
            return FakeSession()

    monkeypatch.setattr(module, "AdbDeviceBackend", FakeAdbDeviceBackend)
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path / "screenshots")
    monkeypatch.setattr(module, "SCREENSHOT_LABEL", "clash")

    asyncio.run(module.main())

    assert events == [
        ("open_session", None),
        ("enter", None),
        ("launch", "com.supercell.clashofclans"),
        ("screenshot", None),
        ("close", "com.supercell.clashofclans"),
        ("exit", None),
    ]
    assert (tmp_path / "screenshots" / "clash.png").is_file()
    assert (tmp_path / "screenshots" / "manifest.jsonl").is_file()
