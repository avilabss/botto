"""Reference CLI entrypoints for the Botto app."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import metadata
from types import FrameType
from typing import Any, Protocol, TextIO

from android_game_automator.artifacts import ArtifactStore
from android_game_automator.ocr import warm_up_ocr
from android_game_automator.types import DeviceInfo

from android_game_automator.adb import AdbDeviceBackend
from botto.automation.config import (
    BottoConfig,
    BottoConfigError,
    LoadedBottoConfig,
    load_botto_config,
)
from botto.automation.controller import AutomationController
from botto.automation.strategy import AttackStrategy, StrategyConfigError, load_attack_strategy
from botto.detection import BaseScreen, Overlay, analyze_screen
from botto.live import (
    DebugPreviewBackend,
    DebugPreviewFrameSourceFactory,
    DebugPreviewScreenAnalyzer,
    PreviewWindow,
    run_debug_preview,
)
from botto.runtime import RuntimeLoopState, run_read_only_runtime

DEFAULT_RUN_ARTIFACT_ROOT = ".botto-artifacts"
_RUN_LOG_ARTIFACT_LABEL = "run-log"
_RUN_CONSOLE_LOG_DATE_FORMAT = "%H:%M:%S"
_RUN_FILE_LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
_LOGGER = logging.getLogger(__name__)


class _UtcLogFormatter(logging.Formatter):
    def converter(self, timestamp: float | None) -> time.struct_time:
        if timestamp is None:
            return time.gmtime()
        return time.gmtime(timestamp)


class _Backend(DebugPreviewBackend, Protocol):
    async def list_devices(self) -> tuple[DeviceInfo, ...]: ...


class _BackendFactory(Protocol):
    def __call__(self) -> _Backend: ...


class CliError(Exception):
    """Raised when CLI input or runtime state prevents completion."""


@dataclass(frozen=True, slots=True)
class _RunLoggingContext:
    artifact_store: ArtifactStore


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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  botto devices
  botto devices --json
  botto run
  botto run --debug
  botto run --serial <serial> -v
  botto run --skip-launch --debug

Run 'botto run --help' to see all run-specific flags.""",
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

    run_parser = subparsers.add_parser(
        "run",
        help="Run the read-only Clash runtime; see 'botto run --help' for flags.",
    )
    run_parser.add_argument(
        "--debug",
        action="store_true",
        help="Show the debug preview instead of headless state logs.",
    )
    run_parser.add_argument(
        "--serial",
        "--device",
        dest="device",
        help="ADB device serial. If omitted, the only connected device is used.",
    )
    run_parser.add_argument(
        "--skip-launch",
        action="store_true",
        help="Run against the current screen without launching the app first.",
    )
    run_parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase run logging verbosity; repeat for more detail (-vv, -vvv).",
    )
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    backend_factory: _BackendFactory = AdbDeviceBackend,
    screen_analyzer: DebugPreviewScreenAnalyzer | None = None,
    frame_source_factory: DebugPreviewFrameSourceFactory | None = None,
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
                frame_source_factory=frame_source_factory,
                preview_window=preview_window,
                stdout=resolved_stdout,
                stderr=resolved_stderr,
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
    screen_analyzer: DebugPreviewScreenAnalyzer | None,
    frame_source_factory: DebugPreviewFrameSourceFactory | None,
    preview_window: PreviewWindow | None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if args.command == "devices":
        backend = backend_factory()
        devices = await backend.list_devices()
        _write_payload(_serialize_devices(devices), as_json=args.json, stdout=stdout)
        return 0

    if args.command == "run":
        try:
            loaded_config = load_botto_config()
            loaded_strategy = load_attack_strategy(
                loaded_config.config.attack.strategy,
                base_dir=loaded_config.path.parent,
            )
        except (BottoConfigError, StrategyConfigError) as exc:
            raise CliError(str(exc)) from exc

        with _configured_run_logging(verbosity=args.verbose, stderr=stderr) as logging_context:
            try:
                _log_loaded_config(loaded_config)
                backend = backend_factory()
                resolved_screen_analyzer = (
                    screen_analyzer if screen_analyzer is not None else analyze_screen
                )
                launch = not args.skip_launch
                _LOGGER.debug(
                    "Starting run command (debug=%s, device=%s, launch=%s)",
                    args.debug,
                    args.device,
                    launch,
                )
                if args.debug:
                    _LOGGER.debug("Warming up OCR")
                    warm_up_ocr()
                    _LOGGER.debug("OCR warmup completed")
                    await run_debug_preview(
                        device_id=args.device,
                        launch=launch,
                        artifact_root=logging_context.artifact_store.root,
                        run_name=logging_context.artifact_store.run_dir.name,
                        backend=backend,
                        source_factory=frame_source_factory,
                        preview_window=preview_window,
                        screen_analyzer=resolved_screen_analyzer,
                        runtime_state_hook=AutomationController(
                            loaded_config.config,
                            strategy=loaded_strategy.strategy,
                        ),
                    )
                else:
                    await _run_headless(
                        device_id=args.device,
                        launch=launch,
                        backend=backend,
                        source_factory=frame_source_factory,
                        screen_analyzer=resolved_screen_analyzer,
                        config=loaded_config.config,
                        strategy=loaded_strategy.strategy,
                    )
            except ValueError as exc:
                raise CliError(str(exc)) from exc
        return 0

    raise CliError(f"Unsupported command {args.command!r}")


def _log_loaded_config(loaded_config: LoadedBottoConfig) -> None:
    effective_values = ", ".join(
        f"{name}={_format_config_value(value)}"
        for name, value in loaded_config.config.effective_values().items()
    )
    _LOGGER.info("Loaded Botto config %s: %s", loaded_config.path, effective_values)


def _format_config_value(value: str | int | float) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


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


async def _run_headless(
    *,
    device_id: str | None,
    launch: bool,
    backend: DebugPreviewBackend,
    source_factory: DebugPreviewFrameSourceFactory | None,
    screen_analyzer: DebugPreviewScreenAnalyzer,
    config: BottoConfig,
    strategy: AttackStrategy | None = None,
) -> None:
    shutdown_requested = False
    shutdown_logged = False

    def request_shutdown() -> None:
        nonlocal shutdown_requested
        shutdown_requested = True

    restore_sigint_handler = _install_headless_sigint_handler(request_shutdown)
    if launch:
        _LOGGER.info("Launched Clash of Clans")

    last_state: BaseScreen | Overlay | None = None
    controller = AutomationController(config, strategy=strategy)

    def handle_runtime_state(state: RuntimeLoopState) -> bool:
        nonlocal last_state, shutdown_logged

        if shutdown_requested:
            if not shutdown_logged:
                _LOGGER.info("Shutdown requested; stopping runtime")
                shutdown_logged = True
            return False

        snapshot = state.analysis_snapshot
        if snapshot is None:
            return controller(state)

        analysis = snapshot.analysis
        current_state = _headless_state_key(analysis.base_screen, analysis.overlay)
        if current_state != last_state:
            last_state = current_state
            _LOGGER.info(_headless_state_message(analysis.base_screen, analysis.overlay))
        return controller(state)

    _LOGGER.debug("Starting headless runtime")
    try:
        await run_read_only_runtime(
            sink=handle_runtime_state,
            device_id=device_id,
            launch=launch,
            backend=backend,
            source_factory=source_factory,
            screen_analyzer=screen_analyzer,
        )
    finally:
        restore_sigint_handler()
        _LOGGER.debug("Headless runtime finished")


@contextmanager
def _configured_run_logging(*, verbosity: int, stderr: TextIO) -> Iterator[_RunLoggingContext]:
    artifact_store = ArtifactStore(DEFAULT_RUN_ARTIFACT_ROOT)
    log_path = artifact_store.save_text(
        _RUN_LOG_ARTIFACT_LABEL,
        "",
        metadata={"source": "botto run"},
    )
    level = _run_log_level(verbosity)
    console_handler = logging.StreamHandler(stderr)
    console_handler.setFormatter(_run_console_formatter(verbosity=verbosity))
    console_handler.setLevel(level)
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(_run_file_formatter())
    file_handler.setLevel(level)

    logger = logging.getLogger("botto")
    previous_level = logger.level
    previous_propagate = logger.propagate
    previous_disabled = logger.disabled
    logger.setLevel(level)
    logger.propagate = False
    logger.disabled = False
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    try:
        _LOGGER.debug("Configured run logging at level %s", level)
        yield _RunLoggingContext(artifact_store=artifact_store)
    finally:
        logger.removeHandler(console_handler)
        logger.removeHandler(file_handler)
        console_handler.close()
        file_handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        logger.disabled = previous_disabled


def _run_console_formatter(*, verbosity: int) -> logging.Formatter:
    fmt = "%(asctime)s | %(message)s"
    if verbosity > 0:
        fmt = "%(asctime)s %(levelname)s | %(message)s"
    return logging.Formatter(fmt=fmt, datefmt=_RUN_CONSOLE_LOG_DATE_FORMAT)


def _run_file_formatter() -> logging.Formatter:
    return _UtcLogFormatter(
        fmt="%(asctime)sZ | %(levelname)s | %(name)s | %(message)s",
        datefmt=_RUN_FILE_LOG_DATE_FORMAT,
    )


def _run_log_level(verbosity: int) -> int:
    levels = (logging.INFO, logging.DEBUG, 5, 1)
    bounded_verbosity = min(max(verbosity, 0), len(levels) - 1)
    return levels[bounded_verbosity]


def _install_headless_sigint_handler(request_shutdown: Callable[[], None]) -> Callable[[], None]:
    previous_handler = signal.getsignal(signal.SIGINT)

    def handle_sigint(signum: int, frame: FrameType | None) -> None:
        _ = signum, frame
        request_shutdown()

    try:
        signal.signal(signal.SIGINT, handle_sigint)
    except ValueError:
        _LOGGER.debug("SIGINT handler not installed outside the main thread")
        return lambda: None

    def restore_handler() -> None:
        if previous_handler is not None:
            signal.signal(signal.SIGINT, previous_handler)

    return restore_handler


def _headless_state_message(base_screen: BaseScreen, overlay: Overlay) -> str:
    if overlay is not Overlay.NONE:
        return f"Overlay: {_overlay_display_name(overlay)}"
    if base_screen is BaseScreen.LOADING:
        return "Loading..."
    if base_screen is BaseScreen.HOME_VILLAGE:
        return "On Home Screen"
    if base_screen is BaseScreen.SUPERCELL_LOGO:
        return "On Supercell splash screen"
    return "Screen unknown"


def _headless_state_key(base_screen: BaseScreen, overlay: Overlay) -> BaseScreen | Overlay:
    if overlay is not Overlay.NONE:
        return overlay
    return base_screen


def _overlay_display_name(overlay: Overlay) -> str:
    return overlay.value.replace("_", " ").capitalize()


def main() -> int:
    """Process CLI args and return an exit code."""
    return run()
