"""Tests for the read-only screen analysis runner."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from android_game_automator.image import FrameImage
from android_game_automator.types import (
    DeviceIdentity,
    DeviceInfo,
    NormalizedPoint,
    NormalizedRect,
    PixelFormat,
    Rect,
    SessionInfo,
    Size,
)
from botto.runner import DEFAULT_CLASH_PACKAGE, analyze_once, serialize_screen_analysis
from botto.screens import BaseScreen, Evidence, Overlay, RecommendedAction, ScreenAnalysis

_TIMING_FIELDS = {
    "open_session",
    "launch_app",
    "launch_wait",
    "screenshot",
    "analysis",
    "artifact_save",
    "total",
}


def test_serialize_screen_analysis_handles_enums_dataclasses_and_normalized_points() -> None:
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.HOME_VILLAGE,
        overlay=Overlay.CONNECTION_LOST,
        confidence=0.91,
        evidence=(
            Evidence(
                kind="template",
                label="attack_button",
                confidence=0.93,
                details={
                    "bounds": Rect(left=1, top=2, width=3, height=4),
                    "region": NormalizedRect(left=0.1, top=0.2, width=0.3, height=0.4),
                    "phrases": ("Attack", "Shop"),
                },
            ),
        ),
        recommended_action=RecommendedAction(
            label="tap_try_again",
            tap_target=NormalizedPoint(x=0.5, y=0.78),
            details={"overlay": Overlay.CONNECTION_LOST},
        ),
    )

    payload = serialize_screen_analysis(analysis)

    assert payload == {
        "base_screen": "home_village",
        "overlay": "connection_lost",
        "confidence": 0.91,
        "evidence": [
            {
                "kind": "template",
                "label": "attack_button",
                "confidence": 0.93,
                "text": None,
                "details": {
                    "bounds": {"left": 1, "top": 2, "width": 3, "height": 4},
                    "region": {"left": 0.1, "top": 0.2, "width": 0.3, "height": 0.4},
                    "phrases": ["Attack", "Shop"],
                },
            }
        ],
        "recommended_action": {
            "label": "tap_try_again",
            "tap_target": {"x": 0.5, "y": 0.78},
            "details": {"overlay": "connection_lost"},
        },
    }


def test_analyze_once_launches_by_default_and_saves_artifacts_in_one_run(
    tmp_path: Path,
) -> None:
    session = FakeSession(device_id="emulator-5554")
    analyzer = FakeAnalyzer(_analysis())

    result = asyncio.run(
        analyze_once(
            device_id="emulator-5554",
            artifact_root=tmp_path,
            run_name="run-1",
            backend=FakeBackend(session),
            screen_analyzer=analyzer,
            launch_wait_seconds=0,
        )
    )

    screenshot_path = tmp_path / "run-1" / "images" / "screenshot.png"
    analysis_path = tmp_path / "run-1" / "json" / "screen-analysis.json"
    assert session.launched_packages == [DEFAULT_CLASH_PACKAGE]
    assert session.closed is True
    assert analyzer.images == [session.image]
    assert Path(result["artifacts"]["screenshot"]) == screenshot_path
    assert Path(result["artifacts"]["analysis_json"]) == analysis_path
    assert Path(result["run_dir"]) == tmp_path / "run-1"
    assert screenshot_path.is_file()
    assert analysis_path.is_file()
    _assert_timings(result["timings"])

    saved_analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert saved_analysis["analysis"] == result["analysis"]
    assert saved_analysis["device_id"] == "emulator-5554"
    assert saved_analysis["session_id"] == "adb:emulator-5554:test"
    _assert_timings(saved_analysis["timings"])

    manifest_entries = [
        json.loads(line)
        for line in (tmp_path / "run-1" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(entry["kind"], entry["path"]) for entry in manifest_entries] == [
        ("image", "run-1/images/screenshot.png"),
        ("json", "run-1/json/screen-analysis.json"),
    ]
    assert {Path(result["artifacts"]["screenshot"]).parent.parent} == {
        Path(result["artifacts"]["analysis_json"]).parent.parent
    }


def test_analyze_once_can_skip_launch_and_never_executes_input_actions(
    tmp_path: Path,
) -> None:
    session = FakeSession(device_id="emulator-5554")

    result = asyncio.run(
        analyze_once(
            artifact_root=tmp_path,
            run_name="run-1",
            launch=False,
            launch_wait_seconds=30,
            backend=FakeBackend(session),
            screen_analyzer=FakeAnalyzer(_analysis_with_recommended_action()),
            sleep_fn=FailingSleep(),
        )
    )

    assert result["launched"] is False
    assert session.launched_packages == []
    assert session.closed is True
    assert result["analysis"]["recommended_action"] == {
        "label": "tap_reload",
        "tap_target": {"x": 0.5, "y": 0.78},
        "details": {"overlay": "connection_lost"},
    }
    _assert_timings(result["timings"])


def _assert_timings(timings: object) -> None:
    assert isinstance(timings, dict)
    assert set(timings) == _TIMING_FIELDS
    for value in timings.values():
        assert isinstance(value, int | float)
        assert value >= 0.0


def _analysis() -> ScreenAnalysis:
    return ScreenAnalysis(
        base_screen=BaseScreen.LOADING,
        overlay=Overlay.NONE,
        confidence=0.8,
        evidence=(
            Evidence(
                kind="ocr",
                label="loading_text",
                confidence=0.8,
                text="Loading",
                details={"region": NormalizedRect(left=0.2, top=0.7, width=0.5, height=0.2)},
            ),
        ),
    )


def _analysis_with_recommended_action() -> ScreenAnalysis:
    return ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.CONNECTION_LOST,
        confidence=0.9,
        recommended_action=RecommendedAction(
            label="tap_reload",
            tap_target=NormalizedPoint(x=0.5, y=0.78),
            details={"overlay": Overlay.CONNECTION_LOST},
        ),
    )


def _device_info(device_id: str) -> DeviceInfo:
    return DeviceInfo(
        identity=DeviceIdentity(
            backend_name="adb",
            device_id=device_id,
            display_name=device_id,
        ),
        metadata={"adb.target_kind": "emulator"},
    )


class FakeBackend:
    def __init__(self, session: FakeSession) -> None:
        self._session = session
        self.opened_device_ids: list[str | None] = []

    async def open_session(self, device_id: str | None = None) -> FakeSession:
        self.opened_device_ids.append(device_id)
        return self._session


class FakeSession:
    def __init__(self, *, device_id: str) -> None:
        self.image = FrameImage(
            size=Size(width=1, height=1),
            pixel_format=PixelFormat.RGBA32,
            data=bytes((0, 0, 0, 255)),
            captured_at=datetime.now(UTC),
            frame_id="frame-1",
        )
        self._info = SessionInfo(
            session_id=f"adb:{device_id}:test",
            device=_device_info(device_id),
            started_at=datetime.now(UTC),
        )
        self.closed = False
        self.launched_packages: list[str] = []

    @property
    def info(self) -> SessionInfo:
        return self._info

    async def close(self) -> None:
        self.closed = True

    async def launch_app(self, package_name: str) -> None:
        self.launched_packages.append(package_name)

    async def screenshot(self) -> FrameImage:
        return self.image

    async def tap(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("analyze_once must not tap")

    async def swipe(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("analyze_once must not swipe")


class FakeAnalyzer:
    def __init__(self, analysis: ScreenAnalysis) -> None:
        self._analysis = analysis
        self.images: list[FrameImage] = []

    def __call__(self, image: FrameImage) -> ScreenAnalysis:
        self.images.append(image)
        return self._analysis


class FailingSleep:
    async def __call__(self, seconds: float) -> None:
        raise AssertionError(f"sleep should not be called, got {seconds}")
