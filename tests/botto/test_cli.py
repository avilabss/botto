"""Focused tests for the simplified Botto reference CLI."""

from __future__ import annotations

import asyncio
import json
import re
import signal
from io import StringIO
from pathlib import Path
from typing import Any

import botto.cli as cli_module
import pytest
from botto.cli import build_parser, run
from botto.detection import BaseScreen, Overlay, ScreenAnalysis
from botto.runtime import RuntimeAnalysisSnapshot, RuntimeLoopState

from tests.botto.fakes import (
    FakeAdbBackend,
    FakeAdbSession,
    FakeFrameSource,
    FakeFrameSourceFactory,
    make_device_info,
)

_CONSOLE_LOG_RE = re.compile(r"^\d{2}:\d{2}:\d{2} \| (?P<message>.*)$")
_VERBOSE_CONSOLE_LOG_RE = re.compile(r"^\d{2}:\d{2}:\d{2} (?P<level>[A-Z]+) \| (?P<message>.*)$")
_ARTIFACT_LOG_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z \| "
    r"(?P<level>[A-Z]+) \| (?P<logger>[A-Za-z0-9_.]+) \| (?P<message>.*)$"
)


def test_help_lists_current_public_commands() -> None:
    help_text = build_parser().format_help()

    assert "{devices,run}" in help_text
    assert "devices" in help_text
    assert "run" in help_text
    assert "Examples:" in help_text
    assert "botto devices" in help_text
    assert "botto devices --json" in help_text
    assert "botto run" in help_text
    assert "botto run --debug" in help_text
    assert "botto run --serial <serial> -v" in help_text
    assert "botto run --skip-launch --debug" in help_text
    assert "botto run --help" in help_text


def test_run_help_lists_run_specific_flags(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["run", "--help"])

    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert "--debug" in help_text
    assert "--serial" in help_text
    assert "--device" in help_text
    assert "--skip-launch" in help_text
    assert "-v" in help_text
    assert "--verbose" in help_text


@pytest.mark.parametrize(
    "removed_command",
    ["debug", "session", "capture", "analyze", "live-preview", "live-debug"],
)
def test_removed_commands_are_not_accepted(removed_command: str) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args([removed_command])

    assert excinfo.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "--package", "example.package"],
        ["run", "--debug", "--max-fps", "7"],
        ["run", "--debug", "--window-title", "Custom title"],
        ["run", "--debug", "--analyze-every-seconds", "1.5"],
        ["run", "--debug", "--analyze-interval", "1.5"],
        ["run", "--debug", "--output-dir", ".botto-artifacts"],
        ["run", "--debug", "--run-name", "debug-run"],
    ],
)
def test_run_removed_options_are_not_accepted(argv: list[str]) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(argv)

    assert excinfo.value.code == 2


def test_run_headless_uses_runtime_and_logs_state_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    stdout = StringIO()
    stderr = StringIO()
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source_factory = FakeFrameSourceFactory(FakeFrameSource(frames=()))
    analyzer = object()
    runtime_kwargs: dict[str, Any] = {}

    async def fake_run_read_only_runtime(**kwargs: Any) -> None:
        runtime_kwargs.update(kwargs)
        sink = kwargs["sink"]
        for state in (
            _runtime_state(BaseScreen.LOADING, Overlay.NONE, session=session),
            _runtime_state(BaseScreen.LOADING, Overlay.NONE, session=session),
            _runtime_state(BaseScreen.HOME_VILLAGE, Overlay.NONE, session=session),
            _runtime_state(BaseScreen.SUPERCELL_LOGO, Overlay.NONE, session=session),
            _runtime_state(BaseScreen.HOME_VILLAGE, Overlay.CONNECTION_LOST, session=session),
            _runtime_state(BaseScreen.UNKNOWN, Overlay.CONNECTION_LOST, session=session),
            _runtime_state(BaseScreen.UNKNOWN, Overlay.NONE, session=session),
        ):
            assert sink(state) is True

    monkeypatch.setattr(cli_module, "run_read_only_runtime", fake_run_read_only_runtime)

    exit_code = run(
        ["run", "--device", "emulator-5554"],
        backend_factory=lambda: backend,
        frame_source_factory=source_factory,
        screen_analyzer=analyzer,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == ""
    assert runtime_kwargs["device_id"] == "emulator-5554"
    assert runtime_kwargs["launch"] is True
    assert runtime_kwargs["backend"] is backend
    assert runtime_kwargs["source_factory"] is source_factory
    assert runtime_kwargs["screen_analyzer"] is analyzer
    expected_messages = [
        "Launched Clash of Clans",
        "Loading...",
        "On Home Screen",
        "On Supercell splash screen",
        "Overlay: Connection lost",
        "Screen unknown",
    ]
    assert _console_messages(stderr.getvalue()) == expected_messages
    log_files = list((tmp_path / ".botto-artifacts").glob("*/text/run-log.txt"))
    assert len(log_files) == 1
    assert _artifact_log_records(log_files[0]) == [
        ("INFO", "botto.cli", message) for message in expected_messages
    ]


def test_run_headless_serial_skip_launch_does_not_log_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    stdout = StringIO()
    stderr = StringIO()
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    runtime_kwargs: dict[str, Any] = {}

    async def fake_run_read_only_runtime(**kwargs: Any) -> None:
        runtime_kwargs.update(kwargs)

    monkeypatch.setattr(cli_module, "run_read_only_runtime", fake_run_read_only_runtime)

    exit_code = run(
        ["run", "--serial", "emulator-5554", "--skip-launch"],
        backend_factory=lambda: backend,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert runtime_kwargs["device_id"] == "emulator-5554"
    assert runtime_kwargs["launch"] is False
    assert stdout.getvalue() == ""


def test_run_verbosity_flags_count_and_lower_log_level() -> None:
    parser = build_parser()

    assert parser.parse_args(["run"]).verbose == 0
    assert parser.parse_args(["run", "-v"]).verbose == 1
    assert parser.parse_args(["run", "-vv"]).verbose == 2
    assert parser.parse_args(["run", "--verbose", "--verbose", "--verbose"]).verbose == 3
    assert cli_module._run_log_level(0) > cli_module._run_log_level(1)
    assert cli_module._run_log_level(1) > cli_module._run_log_level(2)
    assert cli_module._run_log_level(2) > cli_module._run_log_level(3)


def test_run_verbose_enables_debug_lifecycle_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    stdout = StringIO()
    stderr = StringIO()
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)

    async def fake_run_read_only_runtime(**kwargs: Any) -> None:
        _ = kwargs

    monkeypatch.setattr(cli_module, "run_read_only_runtime", fake_run_read_only_runtime)

    exit_code = run(
        ["run", "-v"],
        backend_factory=lambda: backend,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == ""
    records = _verbose_console_log_records(stderr.getvalue())
    assert ("DEBUG", "Starting run command (debug=False, device=None, launch=True)") in records
    assert ("INFO", "Launched Clash of Clans") in records
    assert ("DEBUG", "Starting headless runtime") in records


def test_headless_sigint_request_exits_runtime_and_restores_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    stderr = StringIO()
    session = FakeAdbSession(device_id="emulator-5554")
    installed_handlers: list[object] = []

    def fake_getsignal(signum: int) -> object:
        assert signum == signal.SIGINT
        return signal.SIG_DFL

    def fake_signal(signum: int, handler: object) -> object:
        assert signum == signal.SIGINT
        installed_handlers.append(handler)
        return signal.SIG_DFL

    class ShutdownFrameSource(FakeFrameSource):
        def latest_frame(self) -> None:
            self.latest_frame_calls += 1
            handler = installed_handlers[0]
            assert callable(handler)
            handler(signal.SIGINT, None)
            return None

    source = ShutdownFrameSource(frames=())

    async def exercise_headless_shutdown() -> None:
        monkeypatch.setattr(cli_module.signal, "getsignal", fake_getsignal)
        monkeypatch.setattr(cli_module.signal, "signal", fake_signal)
        with cli_module._configured_run_logging(verbosity=0, stderr=stderr):
            await cli_module._run_headless(
                device_id=None,
                launch=False,
                backend=FakeAdbBackend(session=session),
                source_factory=FakeFrameSourceFactory(source),
                screen_analyzer=lambda image: ScreenAnalysis(
                    base_screen=BaseScreen.UNKNOWN,
                    overlay=Overlay.NONE,
                    confidence=0.0,
                ),
            )

    asyncio.run(exercise_headless_shutdown())

    assert _console_messages(stderr.getvalue()) == ["Shutdown requested; stopping runtime"]
    assert source.start_calls == 1
    assert source.stop_calls == 1
    assert source.latest_frame_calls == 1
    assert session.closed is True
    assert installed_handlers[-1] == signal.SIG_DFL


def test_devices_json_output_includes_sdk_metadata() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = run(
        ["devices", "--json"],
        backend_factory=lambda: FakeAdbBackend(
            devices=(
                make_device_info(
                    "emulator-5554",
                    display_name="Pixel 8",
                    metadata={
                        "adb.target_kind": "emulator",
                        "adb.android_sdk": "34",
                    },
                ),
            ),
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == [
        {
            "backend_name": "adb",
            "device_id": "emulator-5554",
            "display_name": "Pixel 8",
            "metadata": {
                "adb.android_sdk": "34",
                "adb.target_kind": "emulator",
            },
        }
    ]


def test_devices_does_not_warm_up_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_warmup() -> None:
        raise AssertionError("devices must not initialize OCR")

    monkeypatch.setattr(cli_module, "warm_up_ocr", fail_warmup)
    stdout = StringIO()

    exit_code = run(
        ["devices"],
        backend_factory=lambda: FakeAdbBackend(devices=(make_device_info("emulator-5554"),)),
        stdout=stdout,
    )

    assert exit_code == 0
    assert "emulator-5554" in stdout.getvalue()


def _console_messages(log_text: str) -> list[str]:
    messages: list[str] = []
    for line in log_text.splitlines():
        match = _CONSOLE_LOG_RE.fullmatch(line)
        assert match is not None
        messages.append(match.group("message"))
    return messages


def _verbose_console_log_records(log_text: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for line in log_text.splitlines():
        match = _VERBOSE_CONSOLE_LOG_RE.fullmatch(line)
        assert match is not None
        records.append((match.group("level"), match.group("message")))
    return records


def _artifact_log_records(log_path: Path) -> list[tuple[str, str, str]]:
    records: list[tuple[str, str, str]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        match = _ARTIFACT_LOG_RE.fullmatch(line)
        assert match is not None
        records.append((match.group("level"), match.group("logger"), match.group("message")))
    return records


def _runtime_state(
    base_screen: BaseScreen,
    overlay: Overlay,
    *,
    session: FakeAdbSession,
) -> RuntimeLoopState:
    return RuntimeLoopState(
        frame=None,
        analysis_snapshot=RuntimeAnalysisSnapshot(
            analysis=ScreenAnalysis(
                base_screen=base_screen,
                overlay=overlay,
                confidence=0.9,
            ),
            analyzed_at=0.0,
        ),
        now=0.0,
        analysis_running=False,
        session_info=session.info,
    )
