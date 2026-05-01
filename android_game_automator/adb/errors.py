"""ADB-specific exceptions."""

from __future__ import annotations


class AdbBackendError(Exception):
    """Base exception for ADB backend/session failures."""


class AdbDeviceDiscoveryError(AdbBackendError):
    """Raised when device discovery fails due to adb transport issues."""


class AdbDeviceUnavailableError(AdbBackendError):
    """Raised when a requested device cannot be opened for a session."""


class AdbDisplayStateError(AdbBackendError):
    """Raised when orientation/display state cannot be determined."""


class AdbSessionClosedError(AdbBackendError):
    """Raised when an operation is attempted on a closed session."""
