"""ADB-backed async device discovery and session lifecycle."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from adbutils_async import AdbClient  # type: ignore[import-untyped]

from android_game_automator.core import (
    Capability,
    CapabilitySet,
    DeviceIdentity,
    DeviceInfo,
    SessionInfo,
)

from ._input import AdbInputHumanizationPolicy
from ._server import list_adb_server_devices
from ._types import AdbClientLike, AdbDeviceHandle
from .errors import AdbDeviceDiscoveryError, AdbDeviceUnavailableError
from .session import AdbDeviceSession

_ANDROID_PROPERTY_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_PROP_MANUFACTURER = "ro.product.manufacturer"
_PROP_MODEL = "ro.product.model"
_PROP_ANDROID_RELEASE = "ro.build.version.release"
_PROP_ANDROID_SDK = "ro.build.version.sdk"


class AdbDeviceBackend:
    """AsyncDeviceBackend implementation backed by adbutils-async."""

    backend_name = "adb"

    def __init__(
        self,
        client: AdbClientLike | None = None,
        input_humanization: AdbInputHumanizationPolicy | None = None,
    ) -> None:
        self._client: AdbClientLike = client if client is not None else AdbClient()
        self._input_humanization = input_humanization

    async def list_devices(self) -> tuple[DeviceInfo, ...]:
        try:
            listed_devices = await list_adb_server_devices(self._client)
        except Exception as exc:
            raise AdbDeviceDiscoveryError(
                "Unable to list adb devices from adb-server."
            ) from exc

        devices = []
        for listed in listed_devices:
            state = listed.state.strip()
            if state != "device":
                continue
            metadata = {
                "adb.state": state,
                "adb.target_kind": _target_kind(listed.serial),
            }
            devices.append(
                DeviceInfo(
                    identity=DeviceIdentity(
                        backend_name=self.backend_name,
                        device_id=listed.serial,
                        display_name=listed.serial,
                    ),
                    capabilities=CapabilitySet.from_iterable(_adb_capabilities()),
                    metadata=metadata,
                )
            )
        return tuple(devices)

    async def open_session(self, device_id: str) -> AdbDeviceSession:
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
        display_name = await _device_display_name(device)

        device_info = DeviceInfo(
            identity=DeviceIdentity(
                backend_name=self.backend_name,
                device_id=device_id,
                display_name=display_name,
            ),
            capabilities=CapabilitySet.from_iterable(_adb_capabilities()),
            metadata={
                **metadata,
                **(await _device_metadata(device)),
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
            input_humanization=self._input_humanization,
        )


def _session_id(device_id: str) -> str:
    return f"adb:{device_id}:{uuid4().hex}"


async def _safe_device_state(device: AdbDeviceHandle) -> str:
    try:
        return (await device.get_state()).strip()
    except Exception as exc:
        raise AdbDeviceUnavailableError(
            f"Unable to query adb state for device {device.serial!r}."
        ) from exc


async def _device_display_name(device: AdbDeviceHandle) -> str | None:
    manufacturer = await _safe_getprop(device, _PROP_MANUFACTURER)
    model = await _safe_getprop(device, _PROP_MODEL)

    parts = [part for part in (manufacturer, model) if part]
    if not parts:
        return None
    return " ".join(parts)


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


def _adb_capabilities() -> tuple[Capability, ...]:
    return (
        Capability.FRAME_CAPTURE,
        Capability.INPUT_TAP,
        Capability.INPUT_SWIPE,
        Capability.INPUT_KEY_PRESS,
        Capability.INPUT_TEXT_ENTRY,
    )
