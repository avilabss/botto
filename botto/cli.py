"""Reference CLI entrypoints for the Botto app."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from importlib import metadata
from typing import Any, Protocol, TextIO

from android_game_automator.ocr import warm_up_ocr
from android_game_automator.types import DeviceInfo

from android_game_automator.adb import AdbDeviceBackend
from botto.detection import analyze_screen
from botto.live import (
    LiveDebugBackend,
    LiveDebugFrameSourceFactory,
    LiveScreenAnalyzer,
    PreviewWindow,
    run_live_debug,
)


class _Backend(LiveDebugBackend, Protocol):
    async def list_devices(self) -> tuple[DeviceInfo, ...]: ...


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

    debug_parser = subparsers.add_parser(
        "debug",
        help="Show read-only live scrcpy video with throttled detector annotations.",
    )
    debug_parser.add_argument(
        "--serial",
        "--device",
        dest="device",
        help="ADB device serial. If omitted, the only connected device is used.",
    )
    debug_parser.add_argument(
        "--skip-launch",
        action="store_true",
        help="Debug the current screen without launching the app first.",
    )
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    backend_factory: _BackendFactory = AdbDeviceBackend,
    screen_analyzer: LiveScreenAnalyzer | None = None,
    live_source_factory: LiveDebugFrameSourceFactory | None = None,
    preview_window: PreviewWindow | None = None,
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
                screen_analyzer=screen_analyzer,
                live_source_factory=live_source_factory,
                preview_window=preview_window,
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
    screen_analyzer: LiveScreenAnalyzer | None,
    live_source_factory: LiveDebugFrameSourceFactory | None,
    preview_window: PreviewWindow | None,
    stdout: TextIO,
) -> int:
    backend = backend_factory()

    if args.command == "devices":
        devices = await backend.list_devices()
        _write_payload(_serialize_devices(devices), as_json=args.json, stdout=stdout)
        return 0

    if args.command == "debug":
        warm_up_ocr()
        try:
            await run_live_debug(
                device_id=args.device,
                launch=not args.skip_launch,
                backend=backend,
                source_factory=live_source_factory,
                preview_window=preview_window,
                screen_analyzer=screen_analyzer if screen_analyzer is not None else analyze_screen,
                status_writer=lambda message: print(message, file=stdout),
            )
        except ValueError as exc:
            raise CliError(str(exc)) from exc
        return 0

    raise CliError(f"Unsupported command {args.command!r}")


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

    print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)


def main() -> int:
    """Process CLI args and return an exit code."""
    return run()
