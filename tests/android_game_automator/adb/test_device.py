"""Tests for ADB device/session behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO

import pytest
from android_game_automator.adb._types import AdbListedDevice
from android_game_automator.types import (
    NormalizedPoint,
    PixelFormat,
    Point,
)
from PIL import Image

from android_game_automator.adb import (
    AdbDeviceBackend,
    AdbDeviceDiscoveryError,
    AdbDeviceUnavailableError,
    AdbDisplayState,
    AdbFrameCaptureError,
    AdbSessionClosedError,
    AndroidKey,
)


def make_png_bytes(size: tuple[int, int], rgba: tuple[int, int, int, int]) -> bytes:
    image = Image.new("RGBA", size=size, color=rgba)
    buffer = BytesIO()
    try:
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        image.close()


@dataclass(slots=True)
class FakeListedDevice:
    serial: str
    state: str


class FakeAdbConnection:
    def __init__(
        self,
        result: str | bytes | Exception,
        *,
        command_results: dict[str | None, str | bytes | Exception] | None = None,
    ) -> None:
        self._result = result
        self._command_results = command_results or {}
        self.sent_commands: list[str] = []
        self.closed = False

    async def send_command(self, cmd: str) -> None:
        self.sent_commands.append(cmd)
        if cmd in self._command_results:
            self._result = self._command_results[cmd]

    async def read_until_close(self, encoding: str | None = "utf-8") -> str | bytes:
        if isinstance(self._result, Exception):
            raise self._result
        if encoding is None or isinstance(self._result, str):
            return self._result
        return self._result.decode(encoding, errors="replace")

    async def close(self) -> None:
        self.closed = True


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
        props: dict[str, str] | None = None,
        shell_outputs: dict[str, str | bytes | Exception] | None = None,
        transport_outputs: dict[str | None, str | bytes | Exception] | None = None,
    ) -> None:
        self.serial = serial
        self._state = state
        self._props = props or {}
        self._shell_outputs = shell_outputs or {}
        self._transport_outputs = transport_outputs or {}
        self.shell_calls: list[tuple[str, str | None]] = []
        self.transport_calls: list[str | None] = []
        self.transport_connections: list[FakeAdbConnection] = []
        self.getprop_calls: list[str] = []

    async def get_state(self) -> str:
        return self._state

    async def getprop(self, prop: str) -> str:
        self.getprop_calls.append(prop)
        return self._props.get(prop, "")

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

    async def open_transport(self, command: str | None = None) -> FakeAdbConnection:
        self.transport_calls.append(command)
        connection = FakeAdbConnection(
            self._transport_outputs.get(command, b""),
            command_results=self._transport_outputs,
        )
        self.transport_connections.append(connection)
        return connection


class FakeAdbClient:
    def __init__(
        self,
        listed_devices: Sequence[AdbListedDevice] = (),
        devices: dict[str, FakeAdbDevice] | None = None,
        *,
        list_error: Exception | None = None,
        device_list_payload: str | bytes | Exception = "",
        connection_error: Exception | None = None,
    ) -> None:
        self._listed_devices: Sequence[AdbListedDevice] = listed_devices
        self._devices = devices or {}
        self._list_error = list_error
        self._device_list_payload = device_list_payload
        self._connection_error = connection_error
        self.list_calls = 0
        self.server_connections: list[FakeAdbServerConnection] = []

    async def list(self) -> Sequence[AdbListedDevice]:
        self.list_calls += 1
        if self._list_error is not None:
            raise self._list_error
        return self._listed_devices

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


def test_backend_lists_usable_devices_from_adb_server() -> None:
    client = FakeAdbClient(
        device_list_payload=(
            "emulator-5554\tdevice\n"
            "R58M123ABC\tdevice\n"
            "offline-serial\toffline\n"
            "unauthorized-serial\tunauthorized\n"
        ),
        devices={},
        list_error=AssertionError("AdbClient.list must not be used for discovery"),
    )
    backend = AdbDeviceBackend(client=client)

    devices = asyncio.run(backend.list_devices())
    assert tuple(device.identity.device_id for device in devices) == (
        "emulator-5554",
        "R58M123ABC",
    )
    assert devices[0].metadata["adb.target_kind"] == "emulator"
    assert devices[1].metadata["adb.target_kind"] == "physical"
    assert client.list_calls == 0
    assert client.server_connections[0].sent == [b"000chost:devices"]
    assert client.server_connections[0].closed


def test_device_listing_accepts_samsung_serial_from_adb_server_payload() -> None:
    device = FakeAdbDevice(
        "R5CT316NY7H",
        shell_outputs={
            "getprop ro.product.manufacturer": "Samsung\n",
            "getprop ro.product.model": "SM-S928B\n",
            "getprop ro.build.version.release": "15\n",
            "getprop ro.build.version.sdk": "35\n",
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            device_list_payload="R5CT316NY7H\tdevice\n",
            devices={"R5CT316NY7H": device},
            list_error=AssertionError("AdbClient.list must not be used for discovery"),
        )
    )

    devices = asyncio.run(backend.list_devices())

    assert tuple(device.identity.device_id for device in devices) == ("R5CT316NY7H",)
    assert devices[0].metadata["adb.state"] == "device"
    assert devices[0].metadata["adb.manufacturer"] == "Samsung"
    assert devices[0].metadata["adb.model"] == "SM-S928B"
    assert devices[0].metadata["adb.android_release"] == "15"
    assert devices[0].metadata["adb.android_sdk"] == "35"
    assert devices[0].identity.display_name == "Samsung SM-S928B"


def test_device_listing_contains_transport_errors_in_backend_exception() -> None:
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            connection_error=RuntimeError("adb transport unavailable"),
        )
    )

    with pytest.raises(AdbDeviceDiscoveryError):
        asyncio.run(backend.list_devices())


def test_open_session_builds_metadata_and_returns_session() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "getprop ro.product.manufacturer": "Google\n",
            "getprop ro.product.model": "Pixel 8\n",
            "getprop ro.build.version.release": "14\n",
            "getprop ro.build.version.sdk": "34\n",
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5554"))

    assert session.info.device.identity.backend_name == "adb"
    assert session.info.device.identity.display_name == "Google Pixel 8"
    assert session.info.device.metadata["adb.model"] == "Pixel 8"
    assert session.info.device.metadata["adb.android_release"] == "14"
    assert session.info.metadata["adb.target_kind"] == "emulator"
    assert device.getprop_calls == []
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
            list_error=AssertionError("AdbClient.list must not be used for discovery"),
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session())

    assert session.info.device.identity.device_id == "emulator-5554"


def test_open_session_without_device_id_requires_exactly_one_usable_device() -> None:
    empty_backend = AdbDeviceBackend(
        client=FakeAdbClient(
            device_list_payload="offline-serial\toffline\n",
            list_error=AssertionError("AdbClient.list must not be used for discovery"),
        )
    )
    multiple_backend = AdbDeviceBackend(
        client=FakeAdbClient(
            device_list_payload="emulator-5554\tdevice\nemulator-5556\tdevice\n",
            list_error=AssertionError("AdbClient.list must not be used for discovery"),
        )
    )

    with pytest.raises(AdbDeviceUnavailableError, match="No usable ADB devices"):
        asyncio.run(empty_backend.open_session())
    with pytest.raises(AdbDeviceUnavailableError, match="Multiple usable ADB devices"):
        asyncio.run(multiple_backend.open_session())


def test_session_async_context_manager_closes_session() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5554"))

    async def use_session() -> bool:
        async with session as active:
            assert active is session
            assert await active.is_healthy()
        return await session.is_healthy()

    assert not asyncio.run(use_session())


def test_session_convenience_methods_execute_expected_adb_commands() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 0",
            "wm size": "Physical size: 100x200",
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    asyncio.run(session.tap(0.5, 0.25, hold_ms=50))
    asyncio.run(session.swipe(0.0, 0.0, 1.0, 1.0))
    asyncio.run(session.key(AndroidKey.BACK))
    asyncio.run(session.text("hello world"))
    asyncio.run(session.launch_app("com.example.game"))
    asyncio.run(session.close_app("com.example.game"))
    asyncio.run(session.key(AndroidKey.HOME))

    assert [call[0] for call in device.shell_calls] == [
        "dumpsys input",
        "wm size",
        "input swipe 50 50 50 50 50",
        "dumpsys input",
        "wm size",
        "input swipe 0 0 99 199 120",
        "input keyevent KEYCODE_BACK",
        "input text hello%sworld",
        "monkey -p com.example.game -c android.intent.category.LAUNCHER 1",
        "am force-stop com.example.game",
        "input keyevent KEYCODE_HOME",
    ]


def test_absolute_point_input_methods_do_not_query_display_state() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    asyncio.run(session.tap(Point(x=500, y=800)))
    asyncio.run(session.swipe(Point(x=10, y=20), Point(x=30, y=40), duration_ms=250))

    assert device.shell_calls == [
        ("input tap 500 800", "utf-8"),
        ("input swipe 10 20 30 40 250", "utf-8"),
    ]


def test_normalized_point_input_methods_map_through_display_state() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 0",
            "wm size": "Physical size: 100x200",
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    asyncio.run(session.tap(NormalizedPoint(x=0.5, y=0.25), hold_ms=50))
    asyncio.run(
        session.swipe(
            NormalizedPoint(x=0.0, y=0.0),
            NormalizedPoint(x=1.0, y=1.0),
        )
    )

    assert [call[0] for call in device.shell_calls] == [
        "dumpsys input",
        "wm size",
        "input swipe 50 50 50 50 50",
        "dumpsys input",
        "wm size",
        "input swipe 0 0 99 199 120",
    ]


def test_multi_swipe_absolute_points_do_not_query_display_state() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    asyncio.run(
        session.multi_swipe(
            (
                (Point(x=10, y=20), Point(x=30, y=40)),
                (Point(x=50, y=60), Point(x=70, y=80)),
            ),
            duration_ms=250,
        )
    )

    assert device.shell_calls == [
        ("input swipe 10 20 30 40 250", "utf-8"),
        ("input swipe 50 60 70 80 250", "utf-8"),
    ]


def test_multi_swipe_normalized_points_map_through_display_state_once() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 0",
            "wm size": "Physical size: 100x200",
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    asyncio.run(
        session.multi_swipe(
            (
                (NormalizedPoint(x=0.0, y=0.0), NormalizedPoint(x=1.0, y=1.0)),
                (Point(x=10, y=20), NormalizedPoint(x=0.5, y=0.25)),
            ),
            duration_ms=300,
        )
    )

    assert [call[0] for call in device.shell_calls] == [
        "dumpsys input",
        "wm size",
        "input swipe 0 0 99 199 300",
        "input swipe 10 20 50 50 300",
    ]


def test_pinch_helpers_generate_best_effort_swipe_commands() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 0",
            "wm size": "Physical size: 100x200",
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    asyncio.run(session.pinch_in(inner_span=0.20, outer_span=0.60, duration_ms=400))
    asyncio.run(session.pinch_out(inner_span=0.20, outer_span=0.60, duration_ms=500))

    assert [call[0] for call in device.shell_calls] == [
        "dumpsys input",
        "wm size",
        "input swipe 20 100 40 100 400",
        "input swipe 80 100 60 100 400",
        "dumpsys input",
        "wm size",
        "input swipe 40 100 20 100 500",
        "input swipe 60 100 80 100 500",
    ]


def test_multi_touch_helpers_reject_invalid_inputs_before_shelling_out() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    with pytest.raises(ValueError, match="at least two strokes"):
        asyncio.run(session.multi_swipe(((Point(x=1, y=1), Point(x=2, y=2)),)))
    with pytest.raises(ValueError, match="duration_ms"):
        asyncio.run(
            session.multi_swipe(
                (
                    (Point(x=1, y=1), Point(x=2, y=2)),
                    (Point(x=3, y=3), Point(x=4, y=4)),
                ),
                duration_ms=0,
            )
        )
    with pytest.raises(ValueError, match="pinch spans"):
        asyncio.run(session.pinch_in(inner_span=0.60, outer_span=0.20))
    with pytest.raises(ValueError, match="duration_ms"):
        asyncio.run(session.pinch_out(duration_ms=0))

    assert device.shell_calls == []


def test_session_rejects_unsafe_package_names_before_shelling_out() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    with pytest.raises(ValueError, match="package_name"):
        asyncio.run(session.launch_app("com.example.game; input keyevent HOME"))
    with pytest.raises(ValueError, match="package_name"):
        asyncio.run(session.close_app("com.example.game && id"))
    with pytest.raises(ValueError, match="package_name"):
        asyncio.run(session.launch_app("comexample"))

    assert device.shell_calls == []


def test_direct_input_methods_raise_when_adb_command_errors() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 0",
            "wm size": "Physical size: 1080x1920",
            "input tap 540 960": RuntimeError("input transport failed"),
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5554"))

    with pytest.raises(RuntimeError, match="input transport failed"):
        asyncio.run(session.tap(0.5, 0.5))


def test_direct_input_rejects_invalid_android_key_identifier() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    with pytest.raises(ValueError, match="letters, digits, or underscores"):
        asyncio.run(session.key("bad key"))

    assert device.shell_calls == []


def test_direct_input_lets_android_reject_unknown_safe_symbolic_keys() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "input keyevent KEYCODE_DEFINITELY_NOT_A_REAL_KEY": RuntimeError("unknown key"),
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    with pytest.raises(RuntimeError, match="unknown key"):
        asyncio.run(session.key("definitely_not_a_real_key"))

    assert device.shell_calls == [("input keyevent KEYCODE_DEFINITELY_NOT_A_REAL_KEY", "utf-8")]


def test_direct_text_input_quotes_shell_arguments_and_rejects_ambiguous_text() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={r"input text '50%%sdone%s\\%spath'": ""},
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()

    asyncio.run(session.text(r"50% done \\ path"))
    with pytest.raises(ValueError, match="cannot represent"):
        asyncio.run(session.text("literal %s payload"))

    assert device.shell_calls == [(r"input text '50%%sdone%s\\%spath'", "utf-8")]


def test_screenshot_prefers_exec_out_and_decodes_rgba_pixels() -> None:
    png_bytes = make_png_bytes((2, 1), (12, 34, 56, 78))
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "screencap -p": RuntimeError("fallback should not be used"),
        },
        transport_outputs={
            "exec:screencap -p": png_bytes,
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()
    image = asyncio.run(session.screenshot())

    assert image.size.width == 2
    assert image.size.height == 1
    assert image.pixel_format is PixelFormat.RGBA32
    assert image.data == bytes((12, 34, 56, 78, 12, 34, 56, 78))
    assert image.frame_id is not None
    assert not hasattr(session, "capture" + "_frame")
    assert device.transport_calls == [None]
    assert device.transport_connections[0].sent_commands == ["exec:screencap -p"]
    assert device.shell_calls == []


def test_screenshot_falls_back_to_raw_shell_screencap_when_exec_fails() -> None:
    png_bytes = make_png_bytes((1, 1), (7, 8, 9, 255))
    device = FakeAdbDevice(
        "emulator-5555",
        shell_outputs={
            "screencap -p": png_bytes,
        },
        transport_outputs={
            "exec:screencap -p": RuntimeError("exec unavailable"),
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5555", state="device")],
            devices={"emulator-5555": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5555"))
    image = asyncio.run(session.screenshot())

    assert image.size.width == 1
    assert image.size.height == 1
    assert image.data == bytes((7, 8, 9, 255))
    assert device.transport_calls == [None]
    assert device.shell_calls[-1] == ("screencap -p", None)


def test_screenshot_falls_back_to_shell_screencap_when_exec_out_fails() -> None:
    png_bytes = make_png_bytes((1, 2), (90, 80, 70, 255)).replace(b"\n", b"\r\n")
    device = FakeAdbDevice(
        "emulator-5556",
        shell_outputs={
            "screencap -p": png_bytes,
        },
        transport_outputs={
            "exec:screencap -p": RuntimeError("exec-out unavailable"),
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5556", state="device")],
            devices={"emulator-5556": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5556"))
    image = asyncio.run(session.screenshot())

    assert image.size.width == 1
    assert image.size.height == 2
    assert image.pixel_format is PixelFormat.RGBA32
    assert image.data == bytes((90, 80, 70, 255, 90, 80, 70, 255))
    assert device.transport_calls == [None]
    assert device.shell_calls[-1] == ("screencap -p", None)


def test_screenshot_raises_when_adb_output_is_not_a_valid_png() -> None:
    device = FakeAdbDevice(
        "emulator-5558",
        shell_outputs={
            "screencap -p": b"still-not-a-png",
        },
        transport_outputs={
            "exec:screencap -p": b"not-a-png",
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5558", state="device")],
            devices={"emulator-5558": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5558"))

    with pytest.raises(AdbFrameCaptureError):
        asyncio.run(session.screenshot())


def test_open_session_rejects_non_ready_device_state() -> None:
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="R58M123ABC", state="offline")],
            devices={"R58M123ABC": FakeAdbDevice("R58M123ABC", state="offline")},
        )
    )

    with pytest.raises(AdbDeviceUnavailableError):
        asyncio.run(backend.open_session("R58M123ABC"))


def test_open_session_rejects_unknown_device_id() -> None:
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={},
        )
    )

    with pytest.raises(AdbDeviceUnavailableError):
        asyncio.run(backend.open_session("missing-device"))


def test_session_reports_health_orientation_and_display_state() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 1",
            "wm size": "Physical size: 1080x1920",
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )
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
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="R58M123ABC", state="device")],
            devices={"R58M123ABC": device},
        )
    )
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
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5558", state="device")],
            devices={"emulator-5558": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5558"))

    display_state = asyncio.run(session.get_display_state())
    assert display_state.size.width == 720
    assert display_state.size.height == 1280


def test_session_tolerates_shell_failures_when_fallbacks_exist() -> None:
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
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="R58M123DEF", state="device")],
            devices={"R58M123DEF": device},
        )
    )
    session = asyncio.run(backend.open_session("R58M123DEF"))

    assert asyncio.run(session.get_rotation_quadrants()) == 0
    display_state = asyncio.run(session.get_display_state())
    assert display_state.size.width == 1080
    assert display_state.size.height == 1920


def test_rotation_quadrants_do_not_imply_portrait_for_landscape_native_device() -> None:
    device = FakeAdbDevice(
        "landscape-native",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 0",
            "wm size": "Physical size: 2560x1440",
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="landscape-native", state="device")],
            devices={"landscape-native": device},
        )
    )
    session = asyncio.run(backend.open_session("landscape-native"))

    assert asyncio.run(session.get_rotation_quadrants()) == 0
    display_state = asyncio.run(session.get_display_state())
    assert display_state.rotation_quadrants == 0
    assert display_state.size.width == 2560
    assert display_state.size.height == 1440
    assert not hasattr(session, "get_orientation")
    assert not hasattr(display_state, "orientation")


def test_session_close_is_idempotent_and_blocks_display_calls() -> None:
    png_bytes = make_png_bytes((1, 1), (1, 2, 3, 255))
    device = FakeAdbDevice(
        "emulator-5556",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 0",
            "wm size": "Physical size: 1080x1920",
        },
        transport_outputs={
            "exec:screencap -p": png_bytes,
        },
    )
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5556", state="device")],
            devices={"emulator-5556": device},
        )
    )
    session = asyncio.run(backend.open_session("emulator-5556"))

    asyncio.run(session.close())
    asyncio.run(session.close())

    assert not asyncio.run(session.is_healthy())
    with pytest.raises(AdbSessionClosedError):
        asyncio.run(session.get_rotation_quadrants())
    with pytest.raises(AdbSessionClosedError):
        asyncio.run(session.get_display_state())
    with pytest.raises(AdbSessionClosedError):
        asyncio.run(session.screenshot())
    with pytest.raises(AdbSessionClosedError):
        asyncio.run(session.key("back"))
