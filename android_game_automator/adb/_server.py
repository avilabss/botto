"""Small adb-server host protocol helpers."""

from __future__ import annotations

from dataclasses import dataclass

from ._types import AdbClientLike, AdbServerConnectionLike

_ADB_OKAY = b"OKAY"
_ADB_FAIL = b"FAIL"
_DEVICE_LIST_QUERY = "host:devices"


@dataclass(frozen=True, slots=True)
class AdbServerDevice:
    """Single entry returned by the adb server device-list query."""

    serial: str
    state: str


class AdbServerProtocolError(RuntimeError):
    """Raised when adb-server returns an invalid host protocol response."""


async def list_adb_server_devices(client: AdbClientLike) -> tuple[AdbServerDevice, ...]:
    """List adb devices using the host protocol without AdbClient.list()."""
    connection = await client.make_connection()
    try:
        await _send_host_query(connection, _DEVICE_LIST_QUERY)
        payload = await _read_string_block(connection)
    finally:
        await connection.close()

    return _parse_device_list(payload)


async def _send_host_query(connection: AdbServerConnectionLike, query: str) -> None:
    query_bytes = query.encode("utf-8")
    await connection.send(f"{len(query_bytes):04x}".encode("ascii") + query_bytes)

    status = await connection.read(4)
    if status == _ADB_OKAY:
        return
    if status == _ADB_FAIL:
        message = await _read_string_block(connection)
        raise AdbServerProtocolError(message or "adb-server rejected device-list query")
    raise AdbServerProtocolError(f"Unexpected adb-server status {status!r}")


async def _read_string_block(connection: AdbServerConnectionLike) -> str:
    length_bytes = await connection.read(4)
    if len(length_bytes) != 4:
        raise AdbServerProtocolError(f"Invalid adb payload length {length_bytes!r}")

    try:
        payload_length = int(length_bytes.decode("ascii"), 16)
    except ValueError as exc:
        raise AdbServerProtocolError(f"Invalid adb payload length {length_bytes!r}") from exc

    payload = await connection.read(payload_length) if payload_length else b""
    if len(payload) != payload_length:
        raise AdbServerProtocolError(
            f"Expected {payload_length} adb payload bytes, got {len(payload)}"
        )
    return payload.decode("utf-8", errors="replace")


def _parse_device_list(payload: str) -> tuple[AdbServerDevice, ...]:
    devices: list[AdbServerDevice] = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        serial, separator, state_payload = line.partition("\t")
        serial = serial.strip()
        if not separator:
            continue

        state_parts = state_payload.strip().split(maxsplit=1)
        if not serial or not state_parts:
            continue

        devices.append(AdbServerDevice(serial=serial, state=state_parts[0]))
    return tuple(devices)
