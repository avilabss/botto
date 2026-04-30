"""Reference CLI entrypoints for the Botto app."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path, PureWindowsPath
from typing import Any, Protocol, TextIO

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.artifacts import ArtifactStore
from android_game_automator.image import FrameImage
from android_game_automator.types import DeviceInfo, SessionInfo


class _Session(Protocol):
    @property
    def info(self) -> SessionInfo: ...

    async def close(self) -> None: ...

    async def screenshot(self) -> FrameImage: ...


class _Backend(Protocol):
    async def list_devices(self) -> tuple[DeviceInfo, ...]: ...

    async def open_session(self, device_id: str | None = None) -> _Session: ...


class _BackendFactory(Protocol):
    def __call__(self) -> _Backend: ...


class CliError(Exception):
    """Raised when CLI input or runtime state prevents completion."""


def _package_version() -> str:
    try:
        return metadata.version("botto")
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
        help="Capture a screenshot and save it as a PNG file.",
    )
    capture_parser.add_argument(
        "--device",
        help="ADB device serial. If omitted, the only connected device is used.",
    )
    capture_parser.add_argument(
        "--output-dir",
        default=".botto-output",
        help="Directory where the PNG screenshot is saved.",
    )
    capture_parser.add_argument(
        "--label",
        default="device-capture",
        help="Filename stem for the saved screenshot under the run's images/ directory.",
    )
    capture_parser.add_argument(
        "--run-name",
        help="Run directory name under --output-dir. Defaults to a timestamped unique name.",
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
        _validate_capture_label(args.label)
        try:
            artifact_store = ArtifactStore(Path(args.output_dir), run_name=args.run_name)
        except ValueError as exc:
            raise CliError(str(exc)) from exc
        session = await _open_selected_session(backend, requested_device_id=args.device)
        try:
            image = await session.screenshot()
            try:
                saved_path = artifact_store.save_image(
                    args.label,
                    image,
                    metadata=_capture_artifact_metadata(session=session, image=image),
                )
            except ValueError as exc:
                raise CliError(str(exc)) from exc
        finally:
            await session.close()
        _write_payload(
            {
                "device_id": session.info.device.identity.device_id,
                "session_id": session.info.session_id,
                "saved_path": str(saved_path),
                "output_dir": str(artifact_store.root),
                "run_dir": str(artifact_store.run_dir),
                "frame": {
                    "size": {
                        "width": image.size.width,
                        "height": image.size.height,
                    },
                    "pixel_format": image.pixel_format.value,
                    "captured_at": image.captured_at.isoformat()
                    if image.captured_at is not None
                    else None,
                    "frame_id": image.frame_id,
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
) -> _Session:
    return await backend.open_session(requested_device_id)


def _validate_capture_label(label: str) -> None:
    cleaned_label = label.strip()
    if not cleaned_label:
        raise CliError("--label must be non-empty.")
    if "\x00" in cleaned_label:
        raise CliError("--label must not contain NUL bytes.")

    label_path = Path(cleaned_label)
    if (
        label_path.name != cleaned_label
        or PureWindowsPath(cleaned_label).name != cleaned_label
        or cleaned_label in {".", ".."}
    ):
        raise CliError("--label must be a filename stem, not a path.")


def _capture_artifact_metadata(*, session: _Session, image: FrameImage) -> dict[str, Any]:
    return {
        "device_id": session.info.device.identity.device_id,
        "session_id": session.info.session_id,
        "frame_id": image.frame_id,
        "pixel_format": image.pixel_format.value,
        "width": image.size.width,
        "height": image.size.height,
    }


def _serialize_devices(devices: tuple[DeviceInfo, ...]) -> list[dict[str, Any]]:
    return [
        {
            "device_id": device.identity.device_id,
            "display_name": device.identity.display_name,
            "backend_name": device.identity.backend_name,
            "metadata": dict(device.metadata),
        }
        for device in devices
    ]


async def _serialize_session(session: _Session) -> dict[str, Any]:
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

    if isinstance(payload, dict) and "saved_path" in payload:
        frame_payload = payload.get("frame")
        size_payload = frame_payload.get("size") if isinstance(frame_payload, dict) else None
        if not isinstance(frame_payload, dict) or not isinstance(size_payload, dict):
            raise CliError("Capture payload is missing frame details.")
        print(
            f"Captured {payload['device_id']} to {payload['saved_path']} "
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
