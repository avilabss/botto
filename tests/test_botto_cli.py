"""Focused tests for the Botto reference CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from android_game_automator.core import (
    ArtifactKind,
    ArtifactRecord,
    Capability,
    CapabilitySet,
    CapturedFrame,
    DeviceIdentity,
    DeviceInfo,
    FrameMetadata,
    PixelFormat,
    SessionInfo,
    Size,
)
from botto.cli import run


def test_session_requires_explicit_device_when_multiple_devices_exist() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = run(
        ["session"],
        backend_factory=lambda: FakeBackend(
            devices=(make_device_info("emulator-5554"), make_device_info("emulator-5556")),
            session=FakeSession(device_id="emulator-5554"),
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert "multiple adb devices are available; pass --device" in stderr.getvalue().lower()


def test_capture_writes_artifact_record_for_selected_device(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()
    recorder = FakeRecorder(tmp_path)

    exit_code = run(
        ["capture", "--device", "emulator-5554", "--output-dir", str(tmp_path)],
        backend_factory=lambda: FakeBackend(
            devices=(make_device_info("emulator-5554"),),
            session=FakeSession(device_id="emulator-5554"),
        ),
        recorder_factory=lambda root: recorder,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert recorder.root == tmp_path
    assert recorder.metadata == {
        "device_id": "emulator-5554",
        "session_id": "adb:emulator-5554:test",
    }
    assert "artifacts/capture.png" in stdout.getvalue()


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
        capabilities=CapabilitySet.from_iterable((Capability.FRAME_CAPTURE,)),
        metadata={"adb.target_kind": "emulator"},
    )


class FakeBackend:
    def __init__(self, *, devices: tuple[DeviceInfo, ...], session: FakeSession) -> None:
        self._devices = devices
        self._session = session

    async def list_devices(self) -> tuple[DeviceInfo, ...]:
        return self._devices

    async def open_session(self, device_id: str) -> FakeSession:
        if device_id != self._session.info.device.identity.device_id:
            raise RuntimeError(f"unknown device: {device_id}")
        return self._session


class FakeSession:
    def __init__(self, *, device_id: str) -> None:
        self._frame = CapturedFrame(
            data=bytes((0, 0, 0, 255)),
            metadata=FrameMetadata(
                size=Size(width=1, height=1),
                captured_at=datetime.now(UTC),
                pixel_format=PixelFormat.RGBA32,
                frame_id="frame-1",
            ),
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

    async def capture_frame(self) -> CapturedFrame:
        return self._frame


class FakeRecorder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.metadata: dict[str, str] | None = None

    async def save_frame_image_artifact(
        self,
        *,
        label: str,
        frame: CapturedFrame,
        metadata: dict[str, str] | None = None,
        artifact_id: str | None = None,
    ) -> ArtifactRecord:
        _ = frame
        _ = artifact_id
        self.metadata = metadata
        return ArtifactRecord(
            artifact_id="artifact-1",
            kind=ArtifactKind.IMAGE,
            created_at=datetime.now(UTC),
            label=label,
            persisted_path="artifacts/capture.png",
            metadata=metadata or {},
        )
