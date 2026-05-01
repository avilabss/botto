"""Focused tests for the simplified Botto reference CLI."""

from __future__ import annotations

from io import StringIO

import botto.cli as cli_module
import pytest
from botto.cli import build_parser, run

from tests.botto.fakes import FakeAdbBackend, make_device_info


def test_help_lists_only_current_public_commands() -> None:
    help_text = build_parser().format_help()

    assert "devices" in help_text
    assert "debug" in help_text
    for removed_command in ("session", "capture", "analyze", "live-preview", "live-debug"):
        assert removed_command not in help_text


@pytest.mark.parametrize(
    "removed_command",
    ["session", "capture", "analyze", "live-preview", "live-debug"],
)
def test_removed_commands_are_not_accepted(removed_command: str) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args([removed_command])

    assert excinfo.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["debug", "--package", "example.package"],
        ["debug", "--max-fps", "7"],
        ["debug", "--window-title", "Custom title"],
        ["debug", "--analyze-every-seconds", "1.5"],
        ["debug", "--analyze-interval", "1.5"],
        ["debug", "--output-dir", ".botto-artifacts"],
        ["debug", "--run-name", "debug-run"],
    ],
)
def test_debug_removed_options_are_not_accepted(argv: list[str]) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(argv)

    assert excinfo.value.code == 2


def test_devices_json_output_includes_sdk_metadata() -> None:
    stdout = StringIO()

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
    )

    assert exit_code == 0
    assert '"device_id": "emulator-5554"' in stdout.getvalue()
    assert '"adb.target_kind": "emulator"' in stdout.getvalue()
    assert '"adb.android_sdk": "34"' in stdout.getvalue()


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
