"""Tests for reduced ADB device/session behavior."""

from __future__ import annotations

import asyncio

import pytest
from android_game_automator.types import NormalizedPoint, Point

import android_game_automator.adb as adb_package
from android_game_automator.adb import (
    AdbDeviceBackend,
    AdbDeviceDiscoveryError,
    AdbDeviceUnavailableError,
    AdbDisplayState,
    AdbSessionClosedError,
)


class FakeAdbServerConnection:
    def __init__(self, payload: str | bytes | Exception) -> None:
        if isinstance(payload, Exception):
            self._read_error: Exception | None = payload
            self._buffer = b""
        else:
            self._read_error = None
            payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload
            self._buffer = b"OKAY" + f"{len(payload_bytes):04x}".encode("ascii") + payload_bytes
        self.sent: list[bytes] = []
        self.closed = False

    async def send(self, data: bytes) -> int:
        self.sent.append(data)
        return len(data)

    async def read(self, n: int) -> bytes:
        if self._read_error is not None:
            raise self._read_error
        if len(self._buffer) < n:
            raise EOFError("adb server response ended early")
        result = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return result

    async def close(self) -> None:
        self.closed = True


class FakeAdbDevice:
    def __init__(
        self,
        serial: str,
        *,
        state: str = "device",
        shell_outputs: dict[str, str | bytes | Exception] | None = None,
    ) -> None:
        self.serial = serial
        self._state = state
        self._shell_outputs = shell_outputs or {}
        self.shell_calls: list[tuple[str, str | None]] = []

    async def get_state(self) -> str:
        return self._state

    async def shell(self, cmdargs: str, encoding: str | None = "utf-8") -> str | bytes:
        self.shell_calls.append((cmdargs, encoding))
        result = self._shell_outputs.get(cmdargs, "")
        if isinstance(result, Exception):
            raise result
        if encoding is None and isinstance(result, str):
            return result.encode("utf-8", errors="surrogateescape")
        if encoding is not None and isinstance(result, bytes):
            return result.decode(encoding, errors="replace")
        return result


class FakeAdbClient:
    def __init__(
        self,
        *,
        devices: dict[str, FakeAdbDevice] | None = None,
        device_list_payload: str | bytes | Exception = "",
        connection_error: Exception | None = None,
    ) -> None:
        self._devices = devices or {}
        self._device_list_payload = device_list_payload
        self._connection_error = connection_error
        self.list_calls = 0
        self.server_connections: list[FakeAdbServerConnection] = []

    async def list(self) -> tuple[object, ...]:
        self.list_calls += 1
        raise AssertionError("AdbClient.list must not be used for discovery")

    async def make_connection(self, timeout: float | None = None) -> FakeAdbServerConnection:
        _ = timeout
        if self._connection_error is not None:
            raise self._connection_error
        connection = FakeAdbServerConnection(self._device_list_payload)
        self.server_connections.append(connection)
        return connection

    async def device(
        self,
        serial: str | None = None,
        transport_id: int | None = None,
    ) -> FakeAdbDevice:
        _ = transport_id
        if serial is None:
            raise ValueError("serial must be provided in tests")
        return self._devices[serial]


def test_backend_lists_usable_devices_from_adb_server_with_metadata() -> None:
    samsung = FakeAdbDevice(
        "R5CT316NY7H",
        shell_outputs={
            "getprop ro.product.manufacturer": "Samsung\n",
            "getprop ro.product.model": "SM-S928B\n",
            "getprop ro.build.version.release": "15\n",
            "getprop ro.build.version.sdk": "35\n",
        },
    )
    client = FakeAdbClient(
        device_list_payload=(
            "emulator-5554\tdevice\n"
            "R5CT316NY7H\tdevice\n"
            "offline-serial\toffline\n"
            "unauthorized-serial\tunauthorized\n"
        ),
        devices={"R5CT316NY7H": samsung},
    )
    backend = AdbDeviceBackend(client=client)

    devices = asyncio.run(backend.list_devices())

    assert tuple(device.identity.device_id for device in devices) == (
        "emulator-5554",
        "R5CT316NY7H",
    )
    assert devices[0].metadata["adb.target_kind"] == "emulator"
    assert devices[1].metadata["adb.target_kind"] == "physical"
    assert devices[1].metadata["adb.manufacturer"] == "Samsung"
    assert devices[1].metadata["adb.model"] == "SM-S928B"
    assert devices[1].metadata["adb.android_release"] == "15"
    assert devices[1].metadata["adb.android_sdk"] == "35"
    assert devices[1].identity.display_name == "Samsung SM-S928B"
    assert client.list_calls == 0
    assert client.server_connections[0].sent == [b"000chost:devices"]
    assert client.server_connections[0].closed


def test_device_listing_contains_transport_errors_in_backend_exception() -> None:
    backend = AdbDeviceBackend(
        client=FakeAdbClient(connection_error=RuntimeError("adb transport unavailable"))
    )

    with pytest.raises(AdbDeviceDiscoveryError):
        asyncio.run(backend.list_devices())


def test_open_session_builds_metadata_and_returns_healthy_session() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "getprop ro.product.manufacturer": "Google\n",
            "getprop ro.product.model": "Pixel 8\n",
            "getprop ro.build.version.release": "14\n",
            "getprop ro.build.version.sdk": "34\n",
        },
    )
    backend = AdbDeviceBackend(client=FakeAdbClient(devices={"emulator-5554": device}))

    session = asyncio.run(backend.open_session("emulator-5554"))

    assert session.info.device.identity.backend_name == "adb"
    assert session.info.device.identity.display_name == "Google Pixel 8"
    assert session.info.device.metadata["adb.model"] == "Pixel 8"
    assert session.info.device.metadata["adb.android_release"] == "14"
    assert session.info.metadata["adb.target_kind"] == "emulator"
    assert asyncio.run(session.is_healthy())
    assert {
        ("getprop ro.product.manufacturer", "utf-8"),
        ("getprop ro.product.model", "utf-8"),
        ("getprop ro.build.version.release", "utf-8"),
        ("getprop ro.build.version.sdk", "utf-8"),
    }.issubset(set(device.shell_calls))


def test_open_session_without_device_id_uses_only_connected_usable_device() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            device_list_payload="emulator-5554\tdevice\noffline-serial\toffline\n",
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session())

    assert session.info.device.identity.device_id == "emulator-5554"


def test_open_session_without_device_id_requires_exactly_one_usable_device() -> None:
    empty_backend = AdbDeviceBackend(
        client=FakeAdbClient(device_list_payload="offline-serial\toffline\n")
    )
    multiple_backend = AdbDeviceBackend(
        client=FakeAdbClient(
            device_list_payload="emulator-5554\tdevice\nemulator-5556\tdevice\n"
        )
    )

    with pytest.raises(AdbDeviceUnavailableError, match="No usable ADB devices"):
        asyncio.run(empty_backend.open_session())
    with pytest.raises(AdbDeviceUnavailableError, match="Multiple usable ADB devices"):
        asyncio.run(multiple_backend.open_session())


def test_open_session_rejects_invalid_or_unusable_device() -> None:
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            devices={"R58M123ABC": FakeAdbDevice("R58M123ABC", state="offline")}
        )
    )

    with pytest.raises(ValueError, match="device_id"):
        asyncio.run(backend.open_session(" "))
    with pytest.raises(AdbDeviceUnavailableError):
        asyncio.run(backend.open_session("missing-device"))
    with pytest.raises(AdbDeviceUnavailableError, match="not in a usable adb state"):
        asyncio.run(backend.open_session("R58M123ABC"))


def test_session_async_context_manager_closes_session() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(client=FakeAdbClient(devices={"emulator-5554": device}))
    session = asyncio.run(backend.open_session("emulator-5554"))

    async def use_session() -> bool:
        async with session as active:
            assert active is session
            assert await active.is_healthy()
        return await session.is_healthy()

    assert not asyncio.run(use_session())


def test_launch_and_close_app_execute_expected_adb_commands() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(client=FakeAdbClient(devices={"emulator-5554": device}))
    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    asyncio.run(session.launch_app("com.example.game"))
    asyncio.run(session.close_app("com.example.game"))

    assert device.shell_calls == [
        ("monkey -p com.example.game -c android.intent.category.LAUNCHER 1", "utf-8"),
        ("am force-stop com.example.game", "utf-8"),
    ]


def test_session_rejects_unsafe_package_names_before_shelling_out() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(client=FakeAdbClient(devices={"emulator-5554": device}))
    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    with pytest.raises(ValueError, match="package_name"):
        asyncio.run(session.launch_app("com.example.game; input keyevent HOME"))
    with pytest.raises(ValueError, match="package_name"):
        asyncio.run(session.close_app("com.example.game && id"))
    with pytest.raises(ValueError, match="package_name"):
        asyncio.run(session.launch_app("comexample"))

    assert device.shell_calls == []


def test_session_reports_health_rotation_and_display_state() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 1",
            "wm size": "Physical size: 1080x1920",
        },
    )
    backend = AdbDeviceBackend(client=FakeAdbClient(devices={"emulator-5554": device}))
    session = asyncio.run(backend.open_session("emulator-5554"))

    assert asyncio.run(session.is_healthy())
    assert asyncio.run(session.get_rotation_quadrants()) == 1

    display_state = asyncio.run(session.get_display_state())
    assert isinstance(display_state, AdbDisplayState)
    assert display_state.rotation_quadrants == 1
    assert display_state.size.width == 1920
    assert display_state.size.height == 1080
    assert display_state.viewport.map_point(NormalizedPoint(x=1.0, y=1.0)) == Point(
        x=1919,
        y=1079,
    )


def test_session_falls_back_to_dumpsys_display_for_rotation_and_size() -> None:
    device = FakeAdbDevice(
        "R58M123ABC",
        shell_outputs={
            "dumpsys input": "",
            "dumpsys display": (
                "DisplayViewport{displayId=0, valid=true, orientation=3, "
                "deviceWidth=1440, deviceHeight=2560}"
            ),
            "wm size": "something unexpected",
        },
    )
    backend = AdbDeviceBackend(client=FakeAdbClient(devices={"R58M123ABC": device}))
    session = asyncio.run(backend.open_session("R58M123ABC"))

    assert asyncio.run(session.get_rotation_quadrants()) == 3

    display_state = asyncio.run(session.get_display_state())
    assert display_state.rotation_quadrants == 3
    assert display_state.size.width == 2560
    assert display_state.size.height == 1440


def test_session_prefers_override_size_when_reported() -> None:
    device = FakeAdbDevice(
        "emulator-5558",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 0",
            "wm size": "Physical size: 1080x1920\nOverride size: 720x1280",
        },
    )
    backend = AdbDeviceBackend(client=FakeAdbClient(devices={"emulator-5558": device}))
    session = asyncio.run(backend.open_session("emulator-5558"))

    display_state = asyncio.run(session.get_display_state())
    assert display_state.size.width == 720
    assert display_state.size.height == 1280


def test_session_tolerates_shell_failures_when_display_fallbacks_exist() -> None:
    device = FakeAdbDevice(
        "R58M123DEF",
        shell_outputs={
            "dumpsys input": RuntimeError("command failed"),
            "dumpsys display": (
                "DisplayViewport{displayId=0, valid=true, orientation=0, "
                "deviceWidth=1080, deviceHeight=1920}"
            ),
            "wm size": RuntimeError("wm unavailable"),
        },
    )
    backend = AdbDeviceBackend(client=FakeAdbClient(devices={"R58M123DEF": device}))
    session = asyncio.run(backend.open_session("R58M123DEF"))

    assert asyncio.run(session.get_rotation_quadrants()) == 0
    display_state = asyncio.run(session.get_display_state())
    assert display_state.size.width == 1080
    assert display_state.size.height == 1920


def test_session_close_is_idempotent_and_blocks_remaining_session_calls() -> None:
    device = FakeAdbDevice(
        "emulator-5556",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 0",
            "wm size": "Physical size: 1080x1920",
        },
    )
    backend = AdbDeviceBackend(client=FakeAdbClient(devices={"emulator-5556": device}))
    session = asyncio.run(backend.open_session("emulator-5556"))

    asyncio.run(session.close())
    asyncio.run(session.close())

    assert not asyncio.run(session.is_healthy())
    with pytest.raises(AdbSessionClosedError):
        asyncio.run(session.get_rotation_quadrants())
    with pytest.raises(AdbSessionClosedError):
        asyncio.run(session.get_display_state())
    with pytest.raises(AdbSessionClosedError):
        asyncio.run(session.launch_app("com.example.game"))
    with pytest.raises(AdbSessionClosedError):
        asyncio.run(session.close_app("com.example.game"))


def test_removed_capture_and_input_apis_are_not_public_sdk_surface() -> None:
    session = asyncio.run(
        AdbDeviceBackend(
            client=FakeAdbClient(devices={"emulator-5554": FakeAdbDevice("emulator-5554")})
        ).open_session("emulator-5554")
    )

    assert not hasattr(adb_package, "AndroidKey")
    assert not hasattr(adb_package, "AdbFrameCaptureError")
    for removed_method in (
        "screenshot",
        "tap",
        "swipe",
        "key",
        "text",
        "multi_swipe",
        "pinch_in",
        "pinch_out",
    ):
        assert not hasattr(session, removed_method)
