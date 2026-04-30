"""Reference CLI entrypoints for the Botto app."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol, TextIO

from android_game_automator.artifacts.local import LocalArtifactRecorder
from android_game_automator.backends import AdbDeviceBackend
from android_game_automator.core import (
    ArtifactRecord,
    AsyncDeviceSession,
    AsyncFrameCapturer,
    CapturedFrame,
    DeviceInfo,
)


class _Backend(Protocol):
    async def list_devices(self) -> tuple[DeviceInfo, ...]: ...

    async def open_session(self, device_id: str) -> AsyncDeviceSession: ...


class _Recorder(Protocol):
    async def save_frame_image_artifact(
        self,
        *,
        label: str,
        frame: CapturedFrame,
        metadata: dict[str, str] | None = None,
        artifact_id: str | None = None,
    ) -> ArtifactRecord: ...


class _BackendFactory(Protocol):
    def __call__(self) -> _Backend: ...


class _RecorderFactory(Protocol):
    def __call__(self, root: Path) -> _Recorder: ...


class CliError(Exception):
    """Raised when CLI input or runtime state prevents completion."""


def _package_version() -> str:
    try:
        return metadata.version("android-game-automator")
    except metadata.PackageNotFoundError:
        return "0.0.0+local"


def build_parser() -> argparse.ArgumentParser:
    """Build the Botto reference CLI parser."""
    parser = argparse.ArgumentParser(
        prog="botto",
        description="Botto reference CLI built on android_game_automator.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_package_version()}",
    )

    subparsers = parser.add_subparsers(dest="command")

    devices_parser = subparsers.add_parser(
        "devices",
        help="List adb devices exposed through the SDK.",
    )
    devices_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )

    session_parser = subparsers.add_parser(
        "session",
        help="Inspect a live SDK session for one adb device.",
    )
    session_parser.add_argument(
        "--device",
        help="ADB device serial. If omitted, the only connected device is used.",
    )
    session_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )

    capture_parser = subparsers.add_parser(
        "capture",
        help="Capture a frame and persist it through the SDK artifact recorder.",
    )
    capture_parser.add_argument(
        "--device",
        help="ADB device serial. If omitted, the only connected device is used.",
    )
    capture_parser.add_argument(
        "--output-dir",
        default=".botto-output",
        help="Directory where the artifact recorder writes output.",
    )
    capture_parser.add_argument(
        "--label",
        default="device-capture",
        help="Artifact label for the saved screenshot.",
    )
    capture_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    backend_factory: _BackendFactory = AdbDeviceBackend,
    recorder_factory: _RecorderFactory = LocalArtifactRecorder,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the Botto reference CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    resolved_stdout = stdout if stdout is not None else sys.stdout
    resolved_stderr = stderr if stderr is not None else sys.stderr

    if args.command is None:
        parser.print_help(resolved_stdout)
        return 0

    try:
        return asyncio.run(
            _run_command(
                args,
                backend_factory=backend_factory,
                recorder_factory=recorder_factory,
                stdout=resolved_stdout,
            )
        )
    except CliError as exc:
        print(f"error: {exc}", file=resolved_stderr)
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=resolved_stderr)
        return 1


async def _run_command(
    args: argparse.Namespace,
    *,
    backend_factory: _BackendFactory,
    recorder_factory: _RecorderFactory,
    stdout: TextIO,
) -> int:
    backend = backend_factory()

    if args.command == "devices":
        devices = await backend.list_devices()
        _write_payload(_serialize_devices(devices), as_json=args.json, stdout=stdout)
        return 0

    if args.command == "session":
        session = await _open_selected_session(backend, requested_device_id=args.device)
        try:
            payload = await _serialize_session(session)
        finally:
            await session.close()
        _write_payload(payload, as_json=args.json, stdout=stdout)
        return 0

    if args.command == "capture":
        session = await _open_selected_session(backend, requested_device_id=args.device)
        try:
            frame_capturer = _require_frame_capturer(session)
            frame = await frame_capturer.capture_frame()
            recorder = recorder_factory(Path(args.output_dir))
            record = await recorder.save_frame_image_artifact(
                label=args.label,
                frame=frame,
                metadata={
                    "device_id": session.info.device.identity.device_id,
                    "session_id": session.info.session_id,
                },
            )
        finally:
            await session.close()
        _write_payload(
            {
                "device_id": session.info.device.identity.device_id,
                "session_id": session.info.session_id,
                "artifact_id": record.artifact_id,
                "artifact_kind": record.kind.value,
                "persisted_path": record.persisted_path,
                "output_dir": str(Path(args.output_dir)),
                "frame": {
                    "size": {
                        "width": frame.metadata.size.width,
                        "height": frame.metadata.size.height,
                    },
                    "pixel_format": frame.metadata.pixel_format.value,
                    "captured_at": frame.metadata.captured_at.isoformat(),
                    "frame_id": frame.metadata.frame_id,
                },
            },
            as_json=args.json,
            stdout=stdout,
        )
        return 0

    raise CliError(f"Unsupported command {args.command!r}")


async def _open_selected_session(
    backend: _Backend,
    *,
    requested_device_id: str | None,
) -> AsyncDeviceSession:
    if requested_device_id is not None:
        return await backend.open_session(requested_device_id)

    devices = await backend.list_devices()
    if not devices:
        raise CliError("No adb devices are available.")
    if len(devices) > 1:
        raise CliError("Multiple adb devices are available; pass --device.")
    return await backend.open_session(devices[0].identity.device_id)


def _require_frame_capturer(session: AsyncDeviceSession) -> AsyncFrameCapturer:
    if not isinstance(session, AsyncFrameCapturer):
        raise CliError("Selected session does not support frame capture.")
    return session


def _serialize_devices(devices: tuple[DeviceInfo, ...]) -> list[dict[str, Any]]:
    return [
        {
            "device_id": device.identity.device_id,
            "display_name": device.identity.display_name,
            "backend_name": device.identity.backend_name,
            "capabilities": [capability.value for capability in device.capabilities],
            "metadata": dict(device.metadata),
        }
        for device in devices
    ]


async def _serialize_session(session: AsyncDeviceSession) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": session.info.session_id,
        "started_at": session.info.started_at.isoformat(),
        "device": _serialize_devices((session.info.device,))[0],
        "metadata": dict(session.info.metadata),
    }

    get_display_state = getattr(session, "get_display_state", None)
    if callable(get_display_state):
        display_state = await get_display_state()
        payload["display"] = {
            "width": display_state.size.width,
            "height": display_state.size.height,
            "rotation_quadrants": display_state.rotation_quadrants,
        }

    return payload


def _write_payload(payload: object, *, as_json: bool, stdout: TextIO) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return

    if isinstance(payload, list):
        if not payload:
            print("No adb devices found.", file=stdout)
            return
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            device_id = entry["device_id"]
            display_name = entry["display_name"] or device_id
            target_kind = entry["metadata"].get("adb.target_kind", "unknown")
            print(f"{device_id} | {display_name} | {target_kind}", file=stdout)
        return

    if isinstance(payload, dict) and "artifact_id" in payload:
        frame_payload = payload.get("frame")
        size_payload = frame_payload.get("size") if isinstance(frame_payload, dict) else None
        if not isinstance(frame_payload, dict) or not isinstance(size_payload, dict):
            raise CliError("Capture payload is missing frame details.")
        print(
            f"Captured {payload['device_id']} to {payload['persisted_path']} "
            f"({size_payload['width']}x{size_payload['height']}, "
            f"{frame_payload['pixel_format']}).",
            file=stdout,
        )
        return

    if isinstance(payload, dict) and "session_id" in payload:
        device = payload["device"]
        if not isinstance(device, dict):
            raise CliError("Session payload is missing device details.")
        print(f"Session: {payload['session_id']}", file=stdout)
        print(f"Device: {device['device_id']}", file=stdout)
        if payload.get("display") is not None:
            display = payload["display"]
            if not isinstance(display, dict):
                raise CliError("Session payload is missing display details.")
            print(
                f"Display: {display['width']}x{display['height']} "
                f"rotation={display['rotation_quadrants']}",
                file=stdout,
            )
        return

    print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)


def main() -> int:
    """Process CLI args and return an exit code."""
    return run()
