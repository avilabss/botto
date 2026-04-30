"""Tests for async-first core protocol contracts."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

from android_game_automator.core import (
    ArtifactKind,
    ArtifactRecord,
    AsyncArtifactRecorder,
    AsyncDetector,
    AsyncDeviceBackend,
    AsyncDeviceSession,
    AsyncFrameCapturer,
    AsyncInputExecutor,
    Capability,
    CapabilitySet,
    CapturedFrame,
    DebugRecord,
    DetectionRequest,
    DetectionResult,
    DeviceIdentity,
    DeviceInfo,
    FrameMetadata,
    InputAction,
    InputActionKind,
    InputActionResult,
    InputStatus,
    LogLevel,
    LogRecord,
    SessionInfo,
    Size,
)


class DummySession:
    """Minimal in-memory session implementing all async contracts."""

    def __init__(self, info: SessionInfo) -> None:
        self._info = info

    @property
    def info(self) -> SessionInfo:
        return self._info

    async def close(self) -> None:
        return None

    async def capture_frame(self) -> CapturedFrame:
        metadata = FrameMetadata(size=Size(width=10, height=20), captured_at=datetime.now(UTC))
        return CapturedFrame(data=b"01", metadata=metadata)

    async def execute_input(self, action: InputAction) -> InputActionResult:
        _ = action
        return InputActionResult(
            action_kind=InputActionKind.TAP,
            status=InputStatus.APPLIED,
            completed_at=datetime.now(UTC),
            message="ok",
        )

    async def detect(
        self,
        frame: CapturedFrame,
        request: DetectionRequest | None = None,
    ) -> DetectionResult:
        _ = frame
        _ = request
        return DetectionResult(detections=(), produced_at=datetime.now(UTC), frame_id="frame-1")

    async def record_artifact(self, record: ArtifactRecord) -> None:
        _ = record
        return None

    async def record_log(self, record: LogRecord) -> None:
        _ = record
        return None

    async def record_debug(self, record: DebugRecord) -> None:
        _ = record
        return None


class DummyBackend:
    """Minimal backend implementing discovery and session open contracts."""

    def __init__(self) -> None:
        device = DeviceInfo(
            identity=DeviceIdentity(backend_name="adb", device_id="emulator-5554"),
            capabilities=CapabilitySet.from_iterable([Capability.FRAME_CAPTURE]),
        )
        self._devices = (device,)
        self._session = DummySession(
            SessionInfo(session_id="session-1", device=device, started_at=datetime.now(UTC))
        )

    async def list_devices(self) -> tuple[DeviceInfo, ...]:
        return self._devices

    async def open_session(self, device_id: str) -> DummySession:
        _ = device_id
        return self._session


def test_protocol_methods_are_async() -> None:
    assert inspect.iscoroutinefunction(AsyncDeviceBackend.list_devices)
    assert inspect.iscoroutinefunction(AsyncDeviceBackend.open_session)
    assert inspect.iscoroutinefunction(AsyncDeviceSession.close)
    assert inspect.iscoroutinefunction(AsyncFrameCapturer.capture_frame)
    assert inspect.iscoroutinefunction(AsyncInputExecutor.execute_input)
    assert inspect.iscoroutinefunction(AsyncDetector.detect)
    assert inspect.iscoroutinefunction(AsyncArtifactRecorder.record_artifact)
    assert inspect.iscoroutinefunction(AsyncArtifactRecorder.record_log)
    assert inspect.iscoroutinefunction(AsyncArtifactRecorder.record_debug)


def test_runtime_protocol_conformance() -> None:
    backend = DummyBackend()
    session = DummySession(
        SessionInfo(
            session_id="session-2",
            device=DeviceInfo(
                identity=DeviceIdentity(backend_name="adb", device_id="emulator-5556"),
                capabilities=CapabilitySet.from_iterable([Capability.ARTIFACT_RECORDING]),
            ),
            started_at=datetime.now(UTC),
        )
    )

    assert isinstance(backend, AsyncDeviceBackend)
    assert isinstance(session, AsyncDeviceSession)
    assert isinstance(session, AsyncFrameCapturer)
    assert isinstance(session, AsyncInputExecutor)
    assert isinstance(session, AsyncDetector)
    assert isinstance(session, AsyncArtifactRecorder)

    artifact = ArtifactRecord(
        artifact_id="artifact-1",
        kind=ArtifactKind.TEXT,
        created_at=datetime.now(UTC),
        label="summary",
    )
    log_record = LogRecord(timestamp=datetime.now(UTC), level=LogLevel.INFO, message="ok")
    debug_record = DebugRecord(timestamp=datetime.now(UTC), name="dbg")

    assert artifact.label == "summary"
    assert log_record.message == "ok"
    assert debug_record.name == "dbg"
