"""Tests for ADB backend device/session behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO

import pytest
from android_game_automator.backends.adb._types import AdbListedDevice
from PIL import Image

from android_game_automator.backends.adb import (
    AdbCoordinateOffset,
    AdbDefaultViewports,
    AdbDeviceBackend,
    AdbDeviceDiscoveryError,
    AdbDeviceUnavailableError,
    AdbDisplayState,
    AdbFrameCaptureError,
    AdbInputHumanizationPolicy,
    AdbSessionClosedError,
    build_adb_input_command,
    build_default_viewports,
)
from android_game_automator.core import (
    AsyncDeviceBackend,
    AsyncDeviceSession,
    AsyncFrameCapturer,
    AsyncInputExecutor,
    Capability,
    InputStatus,
    KeyPressAction,
    NormalizedPoint,
    PixelFormat,
    Point,
    Size,
    SwipeAction,
    TapAction,
    TextEntryAction,
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


def test_backend_protocol_conformance_and_device_listing() -> None:
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

    assert isinstance(backend, AsyncDeviceBackend)

    devices = asyncio.run(backend.list_devices())
    assert tuple(device.identity.device_id for device in devices) == (
        "emulator-5554",
        "R58M123ABC",
    )
    assert devices[0].metadata["adb.target_kind"] == "emulator"
    assert devices[1].metadata["adb.target_kind"] == "physical"
    assert devices[0].capabilities.supports(Capability.INPUT_TAP)
    assert len(devices[0].capabilities) == 5
    assert client.list_calls == 0
    assert client.server_connections[0].sent == [b"000chost:devices"]
    assert client.server_connections[0].closed


def test_device_listing_accepts_samsung_serial_from_adb_server_payload() -> None:
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            device_list_payload="R5CT316NY7H\tdevice\n",
            list_error=AssertionError("AdbClient.list must not be used for discovery"),
        )
    )

    devices = asyncio.run(backend.list_devices())

    assert tuple(device.identity.device_id for device in devices) == ("R5CT316NY7H",)
    assert devices[0].metadata["adb.state"] == "device"


def test_device_listing_contains_transport_errors_in_backend_exception() -> None:
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            connection_error=RuntimeError("adb transport unavailable"),
        )
    )

    with pytest.raises(AdbDeviceDiscoveryError):
        asyncio.run(backend.list_devices())


def test_open_session_builds_metadata_and_exposes_session_contract() -> None:
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

    assert isinstance(session, AsyncDeviceSession)
    assert isinstance(session, AsyncFrameCapturer)
    assert isinstance(session, AsyncInputExecutor)
    assert session.info.device.identity.backend_name == "adb"
    assert session.info.device.identity.display_name == "Google Pixel 8"
    assert session.info.device.metadata["adb.model"] == "Pixel 8"
    assert session.info.device.metadata["adb.android_release"] == "14"
    assert session.info.metadata["adb.target_kind"] == "emulator"
    assert session.info.device.capabilities.supports(Capability.FRAME_CAPTURE)
    assert device.getprop_calls == []
    assert {
        ("getprop ro.product.manufacturer", "utf-8"),
        ("getprop ro.product.model", "utf-8"),
        ("getprop ro.build.version.release", "utf-8"),
        ("getprop ro.build.version.sdk", "utf-8"),
    }.issubset(set(device.shell_calls))


def test_open_session_declares_frame_capture_capability() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5554"))

    assert session.info.device.capabilities.supports(Capability.FRAME_CAPTURE)
    assert session.info.device.capabilities.supports(Capability.INPUT_TAP)
    assert session.info.device.capabilities.supports(Capability.INPUT_SWIPE)
    assert session.info.device.capabilities.supports(Capability.INPUT_KEY_PRESS)
    assert session.info.device.capabilities.supports(Capability.INPUT_TEXT_ENTRY)


def test_build_adb_input_command_generates_expected_shell_commands() -> None:
    viewport = AdbDisplayState(size=Size(width=1080, height=1920), rotation_quadrants=0).viewport

    tap = build_adb_input_command(TapAction(point=Point(x=10, y=20)), viewport=viewport)
    hold = build_adb_input_command(
        TapAction(point=Point(x=10, y=20), hold_ms=300),
        viewport=viewport,
    )
    swipe = build_adb_input_command(
        SwipeAction(start=Point(x=1, y=2), end=Point(x=30, y=40), duration_ms=250),
        viewport=viewport,
    )
    key = build_adb_input_command(KeyPressAction(key="back"))
    text = build_adb_input_command(TextEntryAction(text="hello world"))

    assert tap.shell_command == "input tap 10 20"
    assert hold.shell_command == "input swipe 10 20 10 20 300"
    assert swipe.shell_command == "input swipe 1 2 30 40 250"
    assert key.shell_command == "input keyevent KEYCODE_BACK"
    assert text.shell_command == "input text 'hello%sworld'"


def test_build_adb_input_command_preserves_literal_percent_and_backslash() -> None:
    text = build_adb_input_command(TextEntryAction(text=r"50% done \\ path"))

    assert text.shell_command == r"input text '50%%sdone%s\\%spath'"
    assert text.rejection_message is None


def test_build_adb_input_command_rejects_literal_percent_s_sequence() -> None:
    text = build_adb_input_command(TextEntryAction(text="literal %s payload"))

    assert text.shell_command == ""
    assert "cannot represent faithfully" in (text.rejection_message or "")


def test_build_adb_input_command_allows_absolute_swipe_without_viewport() -> None:
    swipe = build_adb_input_command(
        SwipeAction(start=Point(x=1, y=2), end=Point(x=30, y=40), duration_ms=250)
    )

    assert swipe.shell_command == "input swipe 1 2 30 40 250"


def test_build_adb_input_command_maps_normalized_coordinates_through_viewport() -> None:
    viewport = AdbDisplayState(
        size=Size(width=1080, height=1920),
        rotation_quadrants=0,
    ).viewport

    tap = build_adb_input_command(
        TapAction(point=NormalizedPoint(x=0.5, y=0.25)),
        viewport=viewport,
    )
    swipe = build_adb_input_command(
        SwipeAction(
            start=NormalizedPoint(x=0.0, y=0.0),
            end=NormalizedPoint(x=1.0, y=1.0),
            duration_ms=120,
        ),
        viewport=viewport,
    )

    assert tap.shell_command == "input tap 540 480"
    assert swipe.shell_command == "input swipe 0 0 1079 1919 120"


def test_build_adb_input_command_applies_deterministic_humanization() -> None:
    viewport = AdbDisplayState(
        size=Size(width=100, height=200),
        rotation_quadrants=0,
    ).viewport
    humanization = AdbInputHumanizationPolicy(
        coordinate_offset_px=AdbCoordinateOffset(x=3, y=-4),
        duration_scale=1.25,
        duration_offset_ms=5,
    )

    tap = build_adb_input_command(
        TapAction(point=NormalizedPoint(x=0.5, y=0.5), hold_ms=80),
        viewport=viewport,
        humanization=humanization,
    )
    swipe = build_adb_input_command(
        SwipeAction(
            start=Point(x=0, y=0),
            end=Point(x=99, y=199),
            duration_ms=120,
        ),
        viewport=viewport,
        humanization=humanization,
    )

    assert tap.shell_command == "input swipe 53 96 53 96 105"
    assert swipe.shell_command == "input swipe 3 0 99 195 155"


def test_execute_input_returns_failed_result_when_adb_command_errors() -> None:
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
    result = asyncio.run(session.execute_input(TapAction(point=NormalizedPoint(x=0.5, y=0.5))))

    assert result.status is InputStatus.FAILED
    assert result.message == "input transport failed"


def test_execute_input_allows_absolute_tap_when_display_state_probe_fails() -> None:
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "input tap 10 20": "",
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
    result = asyncio.run(session.execute_input(TapAction(point=Point(x=10, y=20))))

    assert result.status is InputStatus.APPLIED
    assert device.shell_calls == [("input tap 10 20", "utf-8")]


def test_execute_input_rejects_invalid_android_key_identifier() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5554"))
    result = asyncio.run(session.execute_input(KeyPressAction(key="bad key")))

    assert result.status is InputStatus.REJECTED
    assert "Unsupported Android key identifier" in (result.message or "")


def test_execute_input_rejects_unknown_android_symbolic_key() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()
    result = asyncio.run(session.execute_input(KeyPressAction(key="definitely_not_a_real_key")))

    assert result.status is InputStatus.REJECTED
    assert "Unsupported Android key identifier" in (result.message or "")
    assert device.shell_calls == []


def test_execute_input_rejects_unrepresentable_text_payload() -> None:
    device = FakeAdbDevice("emulator-5554")
    backend = AdbDeviceBackend(
        client=FakeAdbClient(
            listed_devices=[FakeListedDevice(serial="emulator-5554", state="device")],
            devices={"emulator-5554": device},
        )
    )

    session = asyncio.run(backend.open_session("emulator-5554"))
    device.shell_calls.clear()
    result = asyncio.run(session.execute_input(TextEntryAction(text="literal %s payload")))

    assert result.status is InputStatus.REJECTED
    assert "cannot represent faithfully" in (result.message or "")
    assert device.shell_calls == []


def test_capture_frame_prefers_exec_out_and_decodes_rgba_pixels() -> None:
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
    frame = asyncio.run(session.capture_frame())

    assert frame.metadata.size.width == 2
    assert frame.metadata.size.height == 1
    assert frame.metadata.pixel_format is PixelFormat.RGBA32
    assert frame.data == bytes((12, 34, 56, 78, 12, 34, 56, 78))
    assert frame.metadata.frame_id is not None
    assert device.transport_calls == [None]
    assert device.transport_connections[0].sent_commands == ["exec:screencap -p"]
    assert device.shell_calls == []


def test_capture_frame_falls_back_to_raw_shell_screencap_when_exec_fails() -> None:
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
    frame = asyncio.run(session.capture_frame())

    assert frame.metadata.size.width == 1
    assert frame.metadata.size.height == 1
    assert frame.data == bytes((7, 8, 9, 255))
    assert device.transport_calls == [None]
    assert device.shell_calls[-1] == ("screencap -p", None)


def test_capture_frame_falls_back_to_shell_screencap_when_exec_out_fails() -> None:
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
    frame = asyncio.run(session.capture_frame())

    assert frame.metadata.size.width == 1
    assert frame.metadata.size.height == 2
    assert frame.metadata.pixel_format is PixelFormat.RGBA32
    assert frame.data == bytes((90, 80, 70, 255, 90, 80, 70, 255))
    assert device.transport_calls == [None]
    assert device.shell_calls[-1] == ("screencap -p", None)


def test_capture_frame_raises_when_adb_output_is_not_a_valid_png() -> None:
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
        asyncio.run(session.capture_frame())


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


def test_build_default_viewports_exposes_full_frame_and_display_regions() -> None:
    png_bytes = make_png_bytes((720, 1280), (1, 2, 3, 255))
    device = FakeAdbDevice(
        "emulator-5554",
        shell_outputs={
            "dumpsys input": "SurfaceOrientation: 1",
            "wm size": "Physical size: 1080x1920",
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

    frame = asyncio.run(session.capture_frame())
    display_state = asyncio.run(session.get_display_state())
    viewports = build_default_viewports(frame, display_state)

    assert isinstance(viewports, AdbDefaultViewports)
    assert viewports.frame.region.width == 720
    assert viewports.frame.region.height == 1280
    assert viewports.display.region.width == 1920
    assert viewports.display.region.height == 1080
    assert display_state.viewport.map_point(NormalizedPoint(x=1.0, y=1.0)) == Point(x=1919, y=1079)


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
        asyncio.run(session.capture_frame())
    with pytest.raises(AdbSessionClosedError):
        asyncio.run(session.execute_input(KeyPressAction(key="back")))
