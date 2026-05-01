"""Small protocol surface for adbutils-async integration."""

from __future__ import annotations

from typing import Protocol


class AdbServerConnectionLike(Protocol):
    """Subset of adb server connection operations used for host protocol queries."""

    async def send(self, data: bytes) -> int:
        """Send raw bytes to the adb server."""

    async def read(self, n: int) -> bytes:
        """Read exactly n bytes from the adb server."""

    async def close(self) -> None:
        """Close the underlying adb server connection."""


class AdbDeviceHandle(Protocol):
    """Subset of adbutils device operations used by this backend."""

    serial: str

    async def get_state(self) -> str:
        """Return adb-reported device state."""

    async def shell(self, cmdargs: str, encoding: str | None = "utf-8") -> str | bytes:
        """Execute a shell command and return output."""


class AdbClientLike(Protocol):
    """Subset of adbutils client operations used by this backend."""

    async def make_connection(self, timeout: float | None = None) -> AdbServerConnectionLike:
        """Open a raw connection to the local adb server."""

    async def device(
        self,
        serial: str | None = None,
        transport_id: int | None = None,
    ) -> AdbDeviceHandle:
        """Resolve a device handle for the provided serial."""
