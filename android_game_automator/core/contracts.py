"""Async-first backend-facing core protocols."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .artifacts import ArtifactRecord, DebugRecord, LogRecord
from .detection import DetectionRequest, DetectionResult
from .device import DeviceInfo, SessionInfo
from .frame import CapturedFrame
from .input import InputAction, InputActionResult


@runtime_checkable
class AsyncDeviceBackend(Protocol):
    """Contract for discovering devices and opening automation sessions."""

    async def list_devices(self) -> tuple[DeviceInfo, ...]:
        """Enumerate devices currently reachable by this backend."""

    async def open_session(self, device_id: str) -> AsyncDeviceSession:
        """Open a session against a specific device identifier."""


@runtime_checkable
class AsyncDeviceSession(Protocol):
    """Contract for a live automation session lifecycle."""

    @property
    def info(self) -> SessionInfo:
        """Return session identity, capabilities, and metadata."""

    async def close(self) -> None:
        """Release all resources associated with this session."""


@runtime_checkable
class AsyncFrameCapturer(Protocol):
    """Contract for asynchronous frame capture."""

    async def capture_frame(self) -> CapturedFrame:
        """Capture and return the latest frame."""


@runtime_checkable
class AsyncInputExecutor(Protocol):
    """Contract for asynchronous input execution."""

    async def execute_input(self, action: InputAction) -> InputActionResult:
        """Execute an input action and return its result."""


@runtime_checkable
class AsyncDetector(Protocol):
    """Contract for asynchronous frame detections."""

    async def detect(
        self,
        frame: CapturedFrame,
        request: DetectionRequest | None = None,
    ) -> DetectionResult:
        """Run a detection pass over an image frame."""


@runtime_checkable
class AsyncArtifactRecorder(Protocol):
    """Contract for recording artifacts and structured diagnostics."""

    async def record_artifact(self, record: ArtifactRecord) -> None:
        """Persist an artifact metadata record."""

    async def record_log(self, record: LogRecord) -> None:
        """Persist a log record."""

    async def record_debug(self, record: DebugRecord) -> None:
        """Persist a debug record."""
