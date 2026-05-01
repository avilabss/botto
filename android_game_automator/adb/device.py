"""ADB-backed async device discovery, sessions, and display helpers."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import uuid4

from adbutils_async import AdbClient  # type: ignore[import-untyped]

from android_game_automator.types import (
    DeviceIdentity,
    DeviceInfo,
    SessionInfo,
    Size,
    Viewport,
)

from ._parse import (
    orient_size_for_rotation,
    parse_display_size,
    parse_rotation_quadrants,
    parse_wm_size,
)
from ._server import list_adb_server_devices
from ._types import AdbClientLike, AdbDeviceHandle
from .errors import (
    AdbDeviceDiscoveryError,
    AdbDeviceUnavailableError,
    AdbDisplayStateError,
    AdbSessionClosedError,
)

_ANDROID_PROPERTY_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_PROP_MANUFACTURER = "ro.product.manufacturer"
_PROP_MODEL = "ro.product.model"
_PROP_ANDROID_RELEASE = "ro.build.version.release"
_PROP_ANDROID_SDK = "ro.build.version.sdk"
_ANDROID_PACKAGE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")


class AdbDeviceBackend:
    """Device discovery and session lifecycle backed by adbutils-async."""

    backend_name = "adb"

    def __init__(
        self,
        client: AdbClientLike | None = None,
    ) -> None:
        self._client: AdbClientLike = client if client is not None else AdbClient()

    async def list_devices(self) -> tuple[DeviceInfo, ...]:
        try:
            listed_devices = await list_adb_server_devices(self._client)
        except Exception as exc:
            raise AdbDeviceDiscoveryError("Unable to list adb devices from adb-server.") from exc

        devices = []
        for listed in listed_devices:
            state = listed.state.strip()
            if state != "device":
                continue
            metadata = {
                "adb.state": state,
                "adb.target_kind": _target_kind(listed.serial),
            }
            metadata.update(await self._listed_device_metadata(listed.serial))
            devices.append(
                DeviceInfo(
                    identity=DeviceIdentity(
                        backend_name=self.backend_name,
                        device_id=listed.serial,
                        display_name=_display_name_from_metadata(metadata) or listed.serial,
                    ),
                    metadata=metadata,
                )
            )
        return tuple(devices)

    async def _listed_device_metadata(self, device_id: str) -> dict[str, str]:
        try:
            device = await self._client.device(serial=device_id)
        except Exception:
            return {}
        return await _device_metadata(device)

    async def open_session(self, device_id: str | None = None) -> AdbDeviceSession:
        if device_id is None:
            devices = await self.list_devices()
            if not devices:
                raise AdbDeviceUnavailableError("No usable ADB devices are connected.")
            if len(devices) > 1:
                device_ids = ", ".join(device.identity.device_id for device in devices)
                raise AdbDeviceUnavailableError(
                    "Multiple usable ADB devices are connected; pass a device_id. "
                    f"Found: {device_ids}."
                )
            device_id = devices[0].identity.device_id

        if not device_id.strip():
            raise ValueError("device_id must be non-empty")

        try:
            device = await self._client.device(serial=device_id)
        except Exception as exc:
            raise AdbDeviceUnavailableError(
                f"Device {device_id!r} could not be resolved through adb-server."
            ) from exc
        state = await _safe_device_state(device)
        if state != "device":
            raise AdbDeviceUnavailableError(
                f"Device {device_id!r} is not in a usable adb state (got {state!r})."
            )

        metadata = {
            "adb.state": state,
            "adb.target_kind": _target_kind(device_id),
        }
        device_metadata = await _device_metadata(device)
        display_name = _display_name_from_metadata(device_metadata)

        device_info = DeviceInfo(
            identity=DeviceIdentity(
                backend_name=self.backend_name,
                device_id=device_id,
                display_name=display_name,
            ),
            metadata={
                **metadata,
                **device_metadata,
            },
        )
        session_info = SessionInfo(
            session_id=_session_id(device_id),
            device=device_info,
            started_at=datetime.now(UTC),
            metadata=metadata,
        )
        return AdbDeviceSession(
            device=device,
            info=session_info,
        )


@dataclass(frozen=True, slots=True)
class AdbDisplayState:
    """Current display dimensions and rotation metadata."""

    size: Size
    rotation_quadrants: int

    def __post_init__(self) -> None:
        if self.rotation_quadrants not in (0, 1, 2, 3):
            raise ValueError("rotation_quadrants must be one of 0, 1, 2, 3")

    @property
    def viewport(self) -> Viewport:
        """The full active display as a generic viewport."""
        return Viewport(surface_size=self.size)


class AdbDeviceSession:
    """Concrete automation session for ADB devices."""

    def __init__(
        self,
        device: AdbDeviceHandle,
        info: SessionInfo,
    ) -> None:
        self._device = device
        self._info = info
        self._closed = False

    @property
    def info(self) -> SessionInfo:
        return self._info

    async def __aenter__(self) -> Self:
        self._ensure_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type, exc, traceback
        await self.close()

    async def close(self) -> None:
        self._closed = True

    async def is_healthy(self) -> bool:
        """Return whether adb still reports this session device as healthy."""
        if self._closed:
            return False

        try:
            return (await self._device.get_state()).strip() == "device"
        except Exception:
            return False

    async def get_rotation_quadrants(self) -> int:
        """Return the current display rotation in quarter turns (0-3)."""
        return await self._get_rotation_quadrants()

    async def get_display_state(self) -> AdbDisplayState:
        """Return current display size adjusted to orientation."""
        rotation = await self._get_rotation_quadrants()
        size = await self._get_display_size()
        oriented_size = orient_size_for_rotation(size, rotation)
        return AdbDisplayState(size=oriented_size, rotation_quadrants=rotation)

    async def launch_app(self, package_name: str) -> None:
        """Launch an app package through Android's launcher intent."""
        self._ensure_open()
        package_arg = _validated_package_shell_arg(package_name)
        await self._run_shell(f"monkey -p {package_arg} -c android.intent.category.LAUNCHER 1")

    async def close_app(self, package_name: str) -> None:
        """Force-stop an app package."""
        self._ensure_open()
        await self._run_shell(f"am force-stop {_validated_package_shell_arg(package_name)}")

    async def _get_rotation_quadrants(self) -> int:
        self._ensure_open()

        for command in ("dumpsys input", "dumpsys display", "dumpsys window displays"):
            output = await self._try_shell(command)
            if output is None:
                continue
            rotation = parse_rotation_quadrants(output)
            if rotation is not None:
                return rotation

        raise AdbDisplayStateError("Unable to determine display rotation from adb output.")

    async def _get_display_size(self) -> Size:
        self._ensure_open()

        wm_output = await self._try_shell("wm size")
        if wm_output is not None:
            wm_size = parse_wm_size(wm_output)
            if wm_size is not None:
                return wm_size

        for command in ("dumpsys display", "dumpsys window displays"):
            output = await self._try_shell(command)
            if output is None:
                continue
            display_size = parse_display_size(output)
            if display_size is not None:
                return display_size

        raise AdbDisplayStateError("Unable to determine display size from adb output.")

    async def _run_shell(self, command: str) -> str:
        output = await self._device.shell(command)
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return output

    async def _try_shell(self, command: str) -> str | None:
        try:
            return await self._run_shell(command)
        except Exception:
            return None

    def _ensure_open(self) -> None:
        if self._closed:
            raise AdbSessionClosedError("ADB session is closed.")


def _session_id(device_id: str) -> str:
    return f"adb:{device_id}:{uuid4().hex}"


async def _safe_device_state(device: AdbDeviceHandle) -> str:
    try:
        return (await device.get_state()).strip()
    except Exception as exc:
        raise AdbDeviceUnavailableError(
            f"Unable to query adb state for device {device.serial!r}."
        ) from exc


async def _device_metadata(device: AdbDeviceHandle) -> dict[str, str]:
    metadata: dict[str, str] = {}

    manufacturer = await _safe_getprop(device, _PROP_MANUFACTURER)
    if manufacturer:
        metadata["adb.manufacturer"] = manufacturer

    model = await _safe_getprop(device, _PROP_MODEL)
    if model:
        metadata["adb.model"] = model

    android_release = await _safe_getprop(device, _PROP_ANDROID_RELEASE)
    if android_release:
        metadata["adb.android_release"] = android_release

    sdk = await _safe_getprop(device, _PROP_ANDROID_SDK)
    if sdk:
        metadata["adb.android_sdk"] = sdk

    return metadata


def _display_name_from_metadata(metadata: dict[str, str]) -> str | None:
    parts = [
        part
        for part in (
            metadata.get("adb.manufacturer"),
            metadata.get("adb.model"),
        )
        if part
    ]
    if not parts:
        return None
    return " ".join(parts)


async def _safe_getprop(device: AdbDeviceHandle, name: str) -> str | None:
    if _ANDROID_PROPERTY_NAME.fullmatch(name) is None:
        raise ValueError(f"Unsafe Android property name: {name!r}")

    try:
        output = await device.shell(f"getprop {name}")
    except Exception:
        return None

    if isinstance(output, bytes):
        value = output.decode("utf-8", errors="replace").strip()
    else:
        value = output.strip()
    return value if value else None


def _target_kind(serial: str) -> str:
    if serial.startswith("emulator-"):
        return "emulator"
    if ":" in serial:
        return "network"
    return "physical"


def _validated_package_shell_arg(package_name: str) -> str:
    if (
        package_name.strip() != package_name
        or _ANDROID_PACKAGE_NAME.fullmatch(package_name) is None
    ):
        raise ValueError(
            "package_name must be a valid Android package name such as 'com.example.app'"
        )
    return shlex.quote(package_name)
