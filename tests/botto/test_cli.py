"""Focused tests for the Botto reference CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from android_game_automator.image import FrameImage
from android_game_automator.types import (
    DeviceIdentity,
    DeviceInfo,
    PixelFormat,
    SessionInfo,
    Size,
)
from botto.cli import run
from PIL import Image


def test_session_uses_backend_default_device_selection() -> None:
    stdout = StringIO()
    stderr = StringIO()
    backend = FakeBackend(
        devices=(make_device_info("emulator-5554"),),
        session=FakeSession(device_id="emulator-5554"),
    )

    exit_code = run(
        ["session"],
        backend_factory=lambda: backend,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert backend.opened_device_ids == [None]
    assert "Session: adb:emulator-5554:test" in stdout.getvalue()


def test_capture_saves_png_for_selected_device(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = run(
        [
            "capture",
            "--device",
            "emulator-5554",
            "--output-dir",
            str(tmp_path),
            "--label",
            "capture",
        ],
        backend_factory=lambda: FakeBackend(
            devices=(make_device_info("emulator-5554"),),
            session=FakeSession(device_id="emulator-5554"),
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    saved_path = tmp_path / "capture.png"
    assert saved_path.is_file()
    manifest_entry = json.loads((tmp_path / "manifest.jsonl").read_text(encoding="utf-8"))
    assert manifest_entry["kind"] == "image"
    assert manifest_entry["path"] == "capture.png"
    assert manifest_entry["metadata"]["device_id"] == "emulator-5554"
    assert str(saved_path) in stdout.getvalue()
    with Image.open(saved_path) as saved_image:
        assert saved_image.mode == "RGBA"
        assert saved_image.size == (1, 1)
        assert saved_image.getpixel((0, 0)) == (0, 0, 0, 255)


def test_capture_rejects_label_paths_before_opening_backend(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()
    backend = FakeBackend(
        devices=(make_device_info("emulator-5554"),),
        session=FakeSession(device_id="emulator-5554"),
    )

    exit_code = run(
        [
            "capture",
            "--device",
            "emulator-5554",
            "--output-dir",
            str(tmp_path / "screenshots"),
            "--label",
            "../escape",
        ],
        backend_factory=lambda: backend,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert "--label must be a filename stem" in stderr.getvalue()
    assert backend.opened_device_ids == []
    assert not (tmp_path / "escape.png").exists()


def test_devices_json_output_includes_sdk_metadata() -> None:
    stdout = StringIO()

    exit_code = run(
        ["devices", "--json"],
        backend_factory=lambda: FakeBackend(
            devices=(make_device_info("emulator-5554", display_name="Pixel 8"),),
            session=FakeSession(device_id="emulator-5554"),
        ),
        stdout=stdout,
    )

    assert exit_code == 0
    assert '"device_id": "emulator-5554"' in stdout.getvalue()
    assert '"adb.target_kind": "emulator"' in stdout.getvalue()


def make_device_info(device_id: str, *, display_name: str | None = None) -> DeviceInfo:
    return DeviceInfo(
        identity=DeviceIdentity(
            backend_name="adb",
            device_id=device_id,
            display_name=display_name or device_id,
        ),
        metadata={"adb.target_kind": "emulator"},
    )


class FakeBackend:
    def __init__(self, *, devices: tuple[DeviceInfo, ...], session: FakeSession) -> None:
        self._devices = devices
        self._session = session
        self.opened_device_ids: list[str | None] = []

    async def list_devices(self) -> tuple[DeviceInfo, ...]:
        return self._devices

    async def open_session(self, device_id: str | None = None) -> FakeSession:
        self.opened_device_ids.append(device_id)
        selected_device_id = device_id
        if selected_device_id is None:
            if len(self._devices) != 1:
                raise RuntimeError("expected exactly one default device")
            selected_device_id = self._devices[0].identity.device_id
        if selected_device_id != self._session.info.device.identity.device_id:
            raise RuntimeError(f"unknown device: {selected_device_id}")
        return self._session


class FakeSession:
    def __init__(self, *, device_id: str) -> None:
        self._image = FrameImage(
            size=Size(width=1, height=1),
            pixel_format=PixelFormat.RGBA32,
            data=bytes((0, 0, 0, 255)),
            captured_at=datetime.now(UTC),
            frame_id="frame-1",
        )
        self._info = SessionInfo(
            session_id=f"adb:{device_id}:test",
            device=make_device_info(device_id),
            started_at=datetime.now(UTC),
            metadata={"adb.target_kind": "emulator"},
        )
        self.closed = False

    @property
    def info(self) -> SessionInfo:
        return self._info

    async def close(self) -> None:
        self.closed = True

    async def screenshot(self) -> FrameImage:
        return self._image
