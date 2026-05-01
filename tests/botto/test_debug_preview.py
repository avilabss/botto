"""CLI and renderer tests for the read-only debug preview."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from io import StringIO
from pathlib import Path

import botto.cli as cli_module
import botto.live as live_module
import botto.live.overlay as overlay_module
import pytest
from android_game_automator.image import FrameImage
from android_game_automator.scrcpy import DEFAULT_SCRCPY_MAX_FPS
from android_game_automator.types import (
    NormalizedPoint,
    NormalizedRect,
    PixelFormat,
    Point,
    Rect,
)
from botto.cli import run
from botto.detection import (
    ActionKind,
    BaseScreen,
    Evidence,
    EvidenceKind,
    HomeElement,
    Overlay,
    PopupButton,
    RecommendedAction,
    ScreenAnalysis,
)
from botto.live import (
    DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE,
    DebugPreviewAnalysisSnapshot,
    render_debug_overlay,
    run_debug_preview,
)
from PIL import Image

from tests.botto.fakes import (
    FakeAdbBackend,
    FakeAdbSession,
    FakeFrameSource,
    FakeFrameSourceFactory,
    FakePreviewWindow,
    make_frame,
)

_CONSOLE_LOG_RE = re.compile(r"^\d{2}:\d{2}:\d{2} \| (?P<message>.*)$")
_ARTIFACT_LOG_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z \| "
    r"(?P<level>[A-Z]+) \| (?P<logger>[A-Za-z0-9_.]+) \| (?P<message>.*)$"
)


def test_live_package_exports_debug_preview_api() -> None:
    exported = set(live_module.__all__)

    assert DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE == "Botto debug preview"

    assert {
        "DEFAULT_DEBUG_PREVIEW_ANALYZE_EVERY_SECONDS",
        "DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE",
        "DebugPreviewAnalysisSnapshot",
        "DebugPreviewBackend",
        "DebugPreviewFrameSource",
        "DebugPreviewFrameSourceFactory",
        "DebugPreviewScreenAnalyzer",
        "DebugPreviewSession",
        "run_debug_preview",
    } <= exported


def test_run_debug_preview_launches_default_package_and_starts_scrcpy_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "warm_up_ocr", lambda: None)
    stdout = StringIO()
    stderr = StringIO()
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(frames=(make_frame("frame-1"),))
    source_factory = FakeFrameSourceFactory(source)
    preview = FakePreviewWindow(keys=(ord("q"),))
    analyzer = FakeAnalyzer()

    exit_code = run(
        [
            "run",
            "--debug",
            "--device",
            "emulator-5554",
        ],
        backend_factory=lambda: backend,
        frame_source_factory=source_factory,
        preview_window=preview,
        screen_analyzer=analyzer,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == ""
    assert _console_messages(stderr.getvalue()) == [
        "Starting debug preview",
        "Debug preview exit requested",
    ]
    assert backend.opened_device_ids == ["emulator-5554"]
    assert session.launched_packages == ["com.supercell.clashofclans"]
    assert source_factory.created == [("emulator-5554", DEFAULT_SCRCPY_MAX_FPS)]
    assert analyzer.frame_ids == ["frame-1"]
    assert source.start_calls == 1
    assert source.stop_calls == 1
    assert session.closed is True
    assert preview.opened == [DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE]
    assert preview.closed == [DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE]
    assert [frame.frame_id for frame in preview.shown_frames] == ["frame-1"]


def test_run_debug_preview_skip_launch_keeps_current_screen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "warm_up_ocr", lambda: None)
    stdout = StringIO()
    stderr = StringIO()
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(frames=(make_frame("frame-1"),))
    source_factory = FakeFrameSourceFactory(source)
    preview = FakePreviewWindow(keys=(27,))

    exit_code = run(
        [
            "run",
            "--debug",
            "--serial",
            "emulator-5554",
            "--skip-launch",
        ],
        backend_factory=lambda: backend,
        frame_source_factory=source_factory,
        preview_window=preview,
        screen_analyzer=FakeAnalyzer(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert _console_messages(stderr.getvalue()) == [
        "Starting debug preview",
        "Debug preview exit requested",
    ]
    assert backend.opened_device_ids == ["emulator-5554"]
    assert session.launched_packages == []
    assert source_factory.created == [("emulator-5554", DEFAULT_SCRCPY_MAX_FPS)]
    assert preview.opened == [DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE]
    assert preview.closed == [DEFAULT_DEBUG_PREVIEW_WINDOW_TITLE]
    assert len(preview.shown_frames) == 1


def test_run_debug_preview_log_and_hotkey_artifacts_share_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "warm_up_ocr", lambda: None)
    stdout = StringIO()
    stderr = StringIO()
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(frames=(make_frame("frame-1"), make_frame("frame-2")))
    source_factory = FakeFrameSourceFactory(source)
    analyzer = BlockingAnalyzer()
    preview = FakePreviewWindow(keys=(ord("s"), ord("q")), wait_callbacks=(None, analyzer.release))

    exit_code = run(
        ["run", "--debug", "--device", "emulator-5554", "--skip-launch"],
        backend_factory=lambda: backend,
        frame_source_factory=source_factory,
        preview_window=preview,
        screen_analyzer=analyzer,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == ""
    run_dirs = list((tmp_path / ".botto-artifacts").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    image_path = run_dir / "images" / "debug-preview-raw-000001.png"
    log_path = run_dir / "text" / "run-log.txt"
    assert image_path.is_file()
    assert log_path.is_file()
    logged_image_path = Path(".botto-artifacts") / run_dir.name / "images" / image_path.name
    saved_message = (
        f"saved debug-preview raw artifact debug-preview-raw-000001: image={logged_image_path}"
    )
    expected_messages = [
        "Starting debug preview",
        saved_message,
        "Debug preview exit requested",
    ]
    assert _console_messages(stderr.getvalue()) == expected_messages
    assert _artifact_log_records(log_path) == [
        ("INFO", "botto.live.debug_preview", message) for message in expected_messages
    ]


def test_run_debug_preview_warms_up_ocr_before_first_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    events: list[str] = []

    def fake_warmup() -> None:
        events.append("warmup")

    class RecordingAnalyzer(FakeAnalyzer):
        def __call__(self, image: FrameImage) -> ScreenAnalysis:
            events.append("analysis")
            return super().__call__(image)

    monkeypatch.setattr(cli_module, "warm_up_ocr", fake_warmup)
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(frames=(make_frame("frame-1"),))
    source_factory = FakeFrameSourceFactory(source)
    preview = FakePreviewWindow(keys=(ord("q"),))
    analyzer = RecordingAnalyzer()

    exit_code = run(
        ["run", "--debug", "--device", "emulator-5554", "--skip-launch"],
        backend_factory=lambda: backend,
        frame_source_factory=source_factory,
        preview_window=preview,
        screen_analyzer=analyzer,
    )

    assert exit_code == 0
    assert events == ["warmup", "analysis"]


def test_debug_preview_throttles_analysis_and_reuses_latest_result_between_frames() -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(
        frames=(make_frame("frame-1"), make_frame("frame-2"), make_frame("frame-3"))
    )
    source_factory = FakeFrameSourceFactory(source)
    preview = FakePreviewWindow(keys=(-1, -1, ord("q")))
    analyzer = FakeAnalyzer()

    asyncio.run(
        run_debug_preview(
            device_id="emulator-5554",
            launch=False,
            analyze_every_seconds=1.0,
            backend=backend,
            source_factory=source_factory,
            preview_window=preview,
            screen_analyzer=analyzer,
            overlay_renderer=passthrough_renderer,
            clock=lambda: 0.0,
        )
    )

    assert analyzer.frame_ids == ["frame-1"]
    assert [frame.frame_id for frame in preview.shown_frames] == [
        "frame-1",
        "frame-2",
        "frame-3",
    ]
    assert source.stop_calls == 1
    assert session.closed is True


def passthrough_renderer(
    frame: FrameImage,
    snapshot: DebugPreviewAnalysisSnapshot | None,
    *,
    now: float | None = None,
    analysis_running: bool = False,
) -> FrameImage:
    _ = snapshot, now, analysis_running
    return frame


def test_debug_preview_renders_newer_frames_while_slow_analysis_runs_single_flight() -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(
        frames=(make_frame("frame-1"), make_frame("frame-2"), make_frame("frame-3"))
    )
    source_factory = FakeFrameSourceFactory(source)
    analyzer = BlockingAnalyzer()
    preview = FakePreviewWindow(
        keys=(-1, -1, ord("q")),
        wait_callbacks=(analyzer.wait_until_started, None, analyzer.release),
    )
    renderer = CapturingRenderer()

    asyncio.run(
        run_debug_preview(
            device_id="emulator-5554",
            launch=False,
            analyze_every_seconds=0.5,
            backend=backend,
            source_factory=source_factory,
            preview_window=preview,
            screen_analyzer=analyzer,
            overlay_renderer=renderer,
            clock=IncrementingClock(),
        )
    )

    assert [frame.frame_id for frame in preview.shown_frames] == [
        "frame-1",
        "frame-2",
        "frame-3",
    ]
    assert analyzer.frame_ids == ["frame-1"]
    assert analyzer.finished.is_set()
    assert [call.frame_id for call in renderer.calls] == ["frame-1", "frame-2", "frame-3"]
    assert [call.analysis_running for call in renderer.calls] == [True, True, True]


def test_debug_preview_uses_latest_frame_without_consuming_stale_frame_queue() -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(
        frames=(make_frame("queued-stale-frame"),),
        latest_frames=(make_frame("latest-frame"),),
        fail_on_frames=True,
    )
    source_factory = FakeFrameSourceFactory(source)
    preview = FakePreviewWindow(keys=(ord("q"),))

    asyncio.run(
        run_debug_preview(
            device_id="emulator-5554",
            launch=False,
            backend=backend,
            source_factory=source_factory,
            preview_window=preview,
            screen_analyzer=FakeAnalyzer(),
            overlay_renderer=passthrough_renderer,
        )
    )

    assert [frame.frame_id for frame in preview.shown_frames] == ["latest-frame"]
    assert source.latest_frame_calls == 1
    assert source.frames_calls == 0


def test_debug_preview_s_hotkey_saves_raw_frame_and_latest_analysis(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="botto.live.debug_preview")
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(
        frames=(
            make_frame("frame-1", rgba=(1, 2, 3, 255)),
            make_frame("frame-2", rgba=(40, 50, 60, 255)),
        )
    )
    source_factory = FakeFrameSourceFactory(source)
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.HOME_VILLAGE,
        overlay=Overlay.NONE,
        confidence=0.8,
        evidence=(
            Evidence(
                kind=EvidenceKind.TEMPLATE,
                subject=BaseScreen.HOME_VILLAGE,
                anchor=HomeElement.ATTACK_BUTTON,
                confidence=0.93,
                details={
                    "bounds": Rect(left=1, top=2, width=3, height=4),
                    "region": NormalizedRect(left=0.1, top=0.2, width=0.3, height=0.4),
                    "phrases": ("Attack", "Shop"),
                },
            ),
        ),
        recommended_action=RecommendedAction(
            kind=ActionKind.TAP,
            target=PopupButton.TRY_AGAIN,
            reason=Overlay.CONNECTION_LOST,
            tap_target=NormalizedPoint(x=0.5, y=0.88),
            details={"overlay": Overlay.CONNECTION_LOST},
        ),
    )
    analyzer = BlockingAnalyzer(analysis)
    preview = FakePreviewWindow(
        keys=(-1, ord("s"), ord("q")),
        wait_callbacks=(analyzer.wait_until_started_release_and_finish,),
    )

    asyncio.run(
        run_debug_preview(
            device_id="emulator-5554",
            launch=False,
            artifact_root=tmp_path,
            run_name="debug-preview-run",
            backend=backend,
            source_factory=source_factory,
            preview_window=preview,
            screen_analyzer=analyzer,
        )
    )

    image_path = tmp_path / "debug-preview-run" / "images" / "debug-preview-raw-000001.png"
    analysis_path = tmp_path / "debug-preview-run" / "json" / "debug-preview-raw-000001.json"
    assert image_path.is_file()
    assert analysis_path.is_file()
    assert [record.getMessage() for record in caplog.records] == [
        "Starting debug preview",
        f"saved debug-preview raw artifact debug-preview-raw-000001: "
        f"image={image_path}, analysis={analysis_path}",
        "Debug preview exit requested",
    ]
    with Image.open(image_path) as saved_image:
        assert saved_image.getpixel((0, 0)) == (40, 50, 60, 255)
    payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert payload["analysis"] == {
        "base_screen": "home_village",
        "overlay": "none",
        "confidence": 0.8,
        "evidence": [
            {
                "kind": "template",
                "subject": "home_village",
                "confidence": 0.93,
                "anchor": "attack_button",
                "text": None,
                "details": {
                    "bounds": {"left": 1, "top": 2, "width": 3, "height": 4},
                    "region": {"left": 0.1, "top": 0.2, "width": 0.3, "height": 0.4},
                    "phrases": ["Attack", "Shop"],
                },
            }
        ],
        "recommended_action": {
            "kind": "tap",
            "target": "try_again",
            "reason": "connection_lost",
            "tap_target": {"x": 0.5, "y": 0.88},
            "details": {"overlay": "connection_lost"},
        },
    }
    assert payload["analysis_frame_id"] == "frame-1"
    assert payload["frame"]["frame_id"] == "frame-2"
    manifest_entries = [
        json.loads(line)
        for line in (tmp_path / "debug-preview-run" / "manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {entry["run_name"] for entry in manifest_entries} == {"debug-preview-run"}
    assert {entry["run_dir"] for entry in manifest_entries} == {"debug-preview-run"}


def test_debug_preview_hotkey_harvests_analysis_completed_during_wait_before_save(
    tmp_path: Path,
) -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(frames=(make_frame("frame-1", rgba=(10, 20, 30, 255)),))
    source_factory = FakeFrameSourceFactory(source)
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.HOME_VILLAGE,
        overlay=Overlay.NONE,
        confidence=0.8,
    )
    analyzer = BlockingAnalyzer(analysis)
    preview = FakePreviewWindow(
        keys=(ord("s"), ord("q")),
        wait_callbacks=(analyzer.wait_until_started_release_and_finish,),
    )

    asyncio.run(
        run_debug_preview(
            device_id="emulator-5554",
            launch=False,
            artifact_root=tmp_path,
            run_name="fresh-hotkey-run",
            backend=backend,
            source_factory=source_factory,
            preview_window=preview,
            screen_analyzer=analyzer,
            overlay_renderer=passthrough_renderer,
        )
    )

    analysis_path = tmp_path / "fresh-hotkey-run" / "json" / "debug-preview-raw-000001.json"
    assert analysis_path.is_file()
    payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert payload["analysis"]["base_screen"] == "home_village"
    assert payload["analysis_frame_id"] == "frame-1"
    assert payload["frame"]["frame_id"] == "frame-1"


def test_debug_preview_d_hotkey_saves_annotated_frame_and_latest_analysis(
    tmp_path: Path,
) -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(
        frames=(
            make_frame("frame-1", rgba=(1, 2, 3, 255)),
            make_frame("frame-2", rgba=(40, 50, 60, 255)),
            make_frame("frame-3", rgba=(70, 80, 90, 255)),
        )
    )
    source_factory = FakeFrameSourceFactory(source)
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.CONNECTION_LOST,
        confidence=0.9,
    )
    analyzer = BlockingAnalyzer(analysis)
    preview = FakePreviewWindow(
        keys=(-1, ord("d"), ord("q")),
        wait_callbacks=(analyzer.wait_until_started_release_and_finish,),
    )

    asyncio.run(
        run_debug_preview(
            device_id="emulator-5554",
            launch=False,
            artifact_root=tmp_path,
            run_name="debug-run",
            backend=backend,
            source_factory=source_factory,
            preview_window=preview,
            screen_analyzer=analyzer,
            overlay_renderer=SolidDebugRenderer(rgba=(9, 8, 7, 255)),
        )
    )

    image_path = tmp_path / "debug-run" / "images" / "debug-preview-debug-000001.png"
    analysis_path = tmp_path / "debug-run" / "json" / "debug-preview-debug-000001.json"
    assert image_path.is_file()
    assert analysis_path.is_file()
    with Image.open(image_path) as saved_image:
        assert saved_image.getpixel((0, 0)) == (9, 8, 7, 255)
    payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert payload["analysis"]["overlay"] == "connection_lost"
    assert payload["frame"]["frame_id"] == "frame-2-debug"
    assert [frame.frame_id for frame in preview.shown_frames] == [
        "frame-1-debug",
        "frame-2-debug",
        "frame-3-debug",
    ]
    assert session.recovery_actions == []
    assert not hasattr(session, "tap")
    assert not hasattr(session, "swipe")


def test_debug_preview_hotkey_skips_analysis_json_when_no_snapshot_exists(
    tmp_path: Path,
) -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(frames=(make_frame("frame-1", rgba=(10, 20, 30, 255)),))
    source_factory = FakeFrameSourceFactory(source)
    analyzer = BlockingAnalyzer()
    preview = FakePreviewWindow(
        keys=(ord("s"), ord("q")),
        wait_callbacks=(analyzer.wait_until_started, analyzer.release),
    )

    asyncio.run(
        run_debug_preview(
            device_id="emulator-5554",
            launch=False,
            artifact_root=tmp_path,
            run_name="no-analysis-run",
            backend=backend,
            source_factory=source_factory,
            preview_window=preview,
            screen_analyzer=analyzer,
            overlay_renderer=passthrough_renderer,
        )
    )

    image_path = tmp_path / "no-analysis-run" / "images" / "debug-preview-raw-000001.png"
    assert image_path.is_file()
    assert not (tmp_path / "no-analysis-run" / "json").exists()
    assert source.latest_frame_calls == 2
    assert session.recovery_actions == []
    assert not hasattr(session, "tap")
    assert not hasattr(session, "swipe")


def test_debug_status_lines_indicate_analysis_running_with_timing() -> None:
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.NONE,
        confidence=0.0,
    )
    snapshot = DebugPreviewAnalysisSnapshot(
        analysis=analysis,
        analyzed_at=1.0,
        duration_seconds=0.25,
        frame_id="frame-1",
    )

    assert overlay_module._debug_status_lines(None, now=1.0, analysis_running=True) == (
        "analysis: running",
    )
    lines = overlay_module._debug_status_lines(snapshot, now=2.0, analysis_running=True)

    assert lines[-1] == "analysis age: 1.0s  took: 0.25s  running"


def test_debug_overlay_status_includes_frame_size(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_lines: list[tuple[str, ...]] = []

    def capture_status_lines(bgr: object, lines: tuple[str, ...]) -> None:
        _ = bgr
        captured_lines.append(lines)

    monkeypatch.setattr(overlay_module, "_draw_status_lines", capture_status_lines)

    render_debug_overlay(
        make_frame("frame-1", width=108, height=50),
        None,
        now=1.0,
        analysis_running=True,
    )

    assert captured_lines[0][0] == "frame: 108x50"
    assert captured_lines[0][1] == "analysis: running"


def test_debug_overlay_renderer_annotates_copy_with_evidence_and_target() -> None:
    frame = make_frame("frame-1", width=80, height=60, rgba=(10, 20, 30, 255))
    original_data = frame.data
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.CONNECTION_LOST,
        confidence=0.9,
        evidence=(
            Evidence(
                kind=EvidenceKind.OCR,
                subject=Overlay.CONNECTION_LOST,
                confidence=0.9,
                text="Connection lost",
                details={
                    "bounds": {"left": 10, "top": 10, "width": 20, "height": 12},
                    "region": {"left": 0.5, "top": 0.2, "width": 0.25, "height": 0.3},
                },
            ),
        ),
        recommended_action=RecommendedAction(
            kind=ActionKind.TAP,
            target=PopupButton.TRY_AGAIN,
            reason=Overlay.CONNECTION_LOST,
            tap_target=NormalizedPoint(x=0.5, y=0.88),
        ),
    )

    annotated = render_debug_overlay(
        frame,
        DebugPreviewAnalysisSnapshot(
            analysis=analysis,
            analyzed_at=1.0,
            duration_seconds=0.05,
            frame_id=frame.frame_id,
        ),
        now=2.0,
    )

    assert annotated is not frame
    assert frame.data == original_data
    assert annotated.data != original_data
    assert annotated.frame_id == frame.frame_id
    assert annotated.pixel_format is PixelFormat.RGBA32
    assert annotated.pixel(Point(x=10, y=10)) != frame.pixel(Point(x=10, y=10))
    assert annotated.pixel(Point(x=40, y=12)) != frame.pixel(Point(x=40, y=12))
    assert annotated.pixel(Point(x=40, y=52)) != frame.pixel(Point(x=40, y=52))


@pytest.mark.parametrize("exit_key", [ord("q"), 27])
def test_debug_preview_exits_on_q_or_escape_cleans_up_background_work_and_remains_read_only(
    exit_key: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "warm_up_ocr", lambda: None)
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(frames=(make_frame("1"), make_frame("2"), make_frame("3")))
    source_factory = FakeFrameSourceFactory(source)
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.ANYONE_THERE,
        confidence=0.9,
        recommended_action=RecommendedAction(
            kind=ActionKind.TAP,
            target=PopupButton.RELOAD_GAME,
            reason=Overlay.ANYONE_THERE,
            tap_target=NormalizedPoint(x=0.5, y=0.88),
        ),
    )
    analyzer = BlockingAnalyzer(analysis)
    preview = FakePreviewWindow(
        keys=(exit_key,),
        wait_callbacks=(analyzer.wait_until_started_and_release,),
    )

    exit_code = run(
        ["run", "--debug", "--device", "emulator-5554", "--skip-launch"],
        backend_factory=lambda: backend,
        frame_source_factory=source_factory,
        preview_window=preview,
        screen_analyzer=analyzer,
    )

    assert exit_code == 0
    assert [frame.frame_id for frame in preview.shown_frames] == ["1"]
    assert session.recovery_actions == []
    assert not hasattr(session, "tap")
    assert not hasattr(session, "swipe")
    assert analyzer.frame_ids == ["1"]
    assert analyzer.finished.is_set()
    assert source.stop_calls == 1
    assert session.closed is True


def _console_messages(log_text: str) -> list[str]:
    messages: list[str] = []
    for line in log_text.splitlines():
        match = _CONSOLE_LOG_RE.fullmatch(line)
        assert match is not None
        messages.append(match.group("message"))
    return messages


def _artifact_log_records(log_path: Path) -> list[tuple[str, str, str]]:
    records: list[tuple[str, str, str]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        match = _ARTIFACT_LOG_RE.fullmatch(line)
        assert match is not None
        records.append((match.group("level"), match.group("logger"), match.group("message")))
    return records


class FakeAnalyzer:
    def __init__(self, analysis: ScreenAnalysis | None = None) -> None:
        self._analysis = analysis or ScreenAnalysis(
            base_screen=BaseScreen.UNKNOWN,
            overlay=Overlay.NONE,
            confidence=0.0,
        )
        self.frame_ids: list[str | None] = []

    def __call__(self, image: FrameImage) -> ScreenAnalysis:
        self.frame_ids.append(image.frame_id)
        return self._analysis


class BlockingAnalyzer:
    def __init__(self, analysis: ScreenAnalysis | None = None) -> None:
        self._analysis = analysis or ScreenAnalysis(
            base_screen=BaseScreen.UNKNOWN,
            overlay=Overlay.NONE,
            confidence=0.0,
        )
        self.started = threading.Event()
        self._release = threading.Event()
        self.finished = threading.Event()
        self._lock = threading.Lock()
        self.frame_ids: list[str | None] = []

    def __call__(self, image: FrameImage) -> ScreenAnalysis:
        with self._lock:
            self.frame_ids.append(image.frame_id)
        self.started.set()
        if not self._release.wait(timeout=5.0):
            raise AssertionError("test did not release the blocking analyzer")
        self.finished.set()
        return self._analysis

    def wait_until_started(self) -> None:
        if not self.started.wait(timeout=2.0):
            raise AssertionError("analysis did not start")

    def release(self) -> None:
        self._release.set()

    def wait_until_started_and_release(self) -> None:
        self.wait_until_started()
        self.release()

    def wait_until_started_release_and_finish(self) -> None:
        self.wait_until_started()
        self.release()
        if not self.finished.wait(timeout=2.0):
            raise AssertionError("analysis did not finish")


class IncrementingClock:
    def __init__(self) -> None:
        self._value = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            value = self._value
            self._value += 1.0
        return value


class RenderCall:
    def __init__(self, *, frame_id: str | None, analysis_running: bool) -> None:
        self.frame_id = frame_id
        self.analysis_running = analysis_running


class CapturingRenderer:
    def __init__(self) -> None:
        self.calls: list[RenderCall] = []

    def __call__(
        self,
        frame: FrameImage,
        snapshot: DebugPreviewAnalysisSnapshot | None,
        *,
        now: float | None = None,
        analysis_running: bool = False,
    ) -> FrameImage:
        _ = snapshot, now
        self.calls.append(RenderCall(frame_id=frame.frame_id, analysis_running=analysis_running))
        return frame


class SolidDebugRenderer:
    def __init__(self, *, rgba: tuple[int, int, int, int]) -> None:
        self._rgba = rgba

    def __call__(
        self,
        frame: FrameImage,
        snapshot: DebugPreviewAnalysisSnapshot | None,
        *,
        now: float | None = None,
        analysis_running: bool = False,
    ) -> FrameImage:
        _ = snapshot, now, analysis_running
        return make_frame(
            f"{frame.frame_id}-debug" if frame.frame_id is not None else "debug-frame",
            width=frame.width,
            height=frame.height,
            rgba=self._rgba,
        )
