"""ADB backend implementation for device discovery, capture, and input."""

from __future__ import annotations

from .backend import AdbDeviceBackend
from .errors import (
    AdbBackendError,
    AdbDeviceDiscoveryError,
    AdbDeviceUnavailableError,
    AdbDisplayStateError,
    AdbFrameCaptureError,
    AdbSessionClosedError,
)
from .input import (
    AdbCoordinateOffset,
    AdbInputCommand,
    AdbInputHumanizationPolicy,
    build_adb_input_command,
)
from .session import AdbDefaultViewports, AdbDeviceSession, AdbDisplayState, build_default_viewports

__all__ = [
    "AdbBackendError",
    "AdbCoordinateOffset",
    "AdbDefaultViewports",
    "AdbDeviceBackend",
    "AdbDeviceSession",
    "AdbDeviceDiscoveryError",
    "AdbDeviceUnavailableError",
    "AdbDisplayState",
    "AdbDisplayStateError",
    "AdbFrameCaptureError",
    "AdbInputCommand",
    "AdbInputHumanizationPolicy",
    "AdbSessionClosedError",
    "build_adb_input_command",
    "build_default_viewports",
]
