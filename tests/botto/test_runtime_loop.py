"""Tests for Botto's read-only runtime loop primitive."""

from __future__ import annotations

import asyncio
import threading

import botto.runtime.loop as runtime_loop_module
import pytest
from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedPoint, Point, Size
from botto.detection import BaseScreen, Overlay, ScreenAnalysis
from botto.runtime import (
    DEFAULT_CLASH_PACKAGE,
    DEFAULT_RUNTIME_MAX_FPS,
    RuntimeAnalysisSnapshot,
    RuntimeLoopState,
    run_read_only_runtime,
)

from tests.botto.fakes import (
    FakeAdbBackend,
    FakeAdbSession,
    FakeFrameSource,
    FakeFrameSourceFactory,
    make_frame,
)


def test_runtime_uses_wait_for_frame_and_emits_matching_snapshots() -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(
        frames=(make_frame("frame-1"), make_frame("frame-2")),
        latest_frames=(make_frame("live-frame-1"), make_frame("live-frame-2")),
    )
    source_factory = FakeFrameSourceFactory(source)
    analyzer = RecordingAnalyzer()
    delivered_pairs: list[tuple[str | None, str | None]] = []

    def sink(state: RuntimeLoopState) -> bool:
        assert state.frame is not None
        assert state.analysis_snapshot is not None
        assert state.analysis_running is False
        delivered_pairs.append((state.frame.frame_id, state.analysis_snapshot.frame_id))
        return len(delivered_pairs) < 2

    asyncio.run(
        run_read_only_runtime(
            sink=sink,
            device_id="emulator-5554",
            launch=False,
            analyze_every_seconds=0.1,
            backend=backend,
            source_factory=source_factory,
            screen_analyzer=analyzer,
            clock=IncrementingClock(),
        )
    )

    assert delivered_pairs == [("frame-1", "frame-1"), ("frame-2", "frame-2")]
    assert analyzer.frame_ids == ["frame-1", "frame-2"]
    assert source.wait_for_frame_calls == 2
    assert source.latest_frame_calls == 0


def test_runtime_throttles_fast_decision_ticks_without_busy_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(
        frames=(make_frame("frame-1"), make_frame("frame-2")),
    )
    source_factory = FakeFrameSourceFactory(source)
    analyzer = RecordingAnalyzer()
    sleep_seconds: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_seconds.append(seconds)

    def sink(state: RuntimeLoopState) -> bool:
        assert state.frame is not None
        return state.frame.frame_id == "frame-1"

    monkeypatch.setattr(runtime_loop_module.asyncio, "sleep", fake_sleep)

    asyncio.run(
        run_read_only_runtime(
            sink=sink,
            device_id="emulator-5554",
            launch=False,
            analyze_every_seconds=0.25,
            backend=backend,
            source_factory=source_factory,
            screen_analyzer=analyzer,
            clock=lambda: 10.0,
        )
    )

    assert sleep_seconds == [0.25]
    assert analyzer.frame_ids == ["frame-1", "frame-2"]
    assert source.wait_for_frame_calls == 2
    assert source.latest_frame_calls == 0


def test_runtime_exit_callback_stops_source_and_closes_session() -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeFrameSource(frames=(make_frame("frame-1"), make_frame("frame-2")))
    source_factory = FakeFrameSourceFactory(source)
    analyzer = RecordingAnalyzer()

    def sink(state: RuntimeLoopState) -> bool:
        assert state.frame is not None
        assert state.analysis_snapshot is not None
        assert state.analysis_snapshot.frame_id == state.frame.frame_id
        return False

    asyncio.run(
        run_read_only_runtime(
            sink=sink,
            device_id="emulator-5554",
            backend=backend,
            source_factory=source_factory,
            screen_analyzer=analyzer,
        )
    )

    assert session.launched_packages == [DEFAULT_CLASH_PACKAGE]
    assert source_factory.created == [("emulator-5554", DEFAULT_RUNTIME_MAX_FPS)]
    assert source.start_calls == 1
    assert source.stop_calls == 1
    assert source.wait_for_frame_calls == 1
    assert source.latest_frame_calls == 0
    assert session.closed is True
    assert session.recovery_actions == []
    assert not hasattr(session, "tap")
    assert not hasattr(session, "swipe")
    assert analyzer.frame_ids == ["frame-1"]


def test_runtime_exposes_action_executor_when_frame_source_supports_actions() -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = ActionFrameSource(frames=(make_frame("frame-1", width=200, height=100),))
    source_factory = FakeFrameSourceFactory(source)

    def sink(state: RuntimeLoopState) -> bool:
        assert state.frame is not None
        assert state.action_executor is not None
        state.action_executor.tap(NormalizedPoint(x=0.5, y=0.5), label="test")
        state.action_executor.swipe(
            NormalizedPoint(x=0.0, y=1.0),
            NormalizedPoint(x=1.0, y=0.0),
            label="test",
            duration_ms=400,
            steps=5,
        )
        return False

    asyncio.run(
        run_read_only_runtime(
            sink=sink,
            device_id="emulator-5554",
            launch=False,
            backend=backend,
            source_factory=source_factory,
            screen_analyzer=lambda image: ScreenAnalysis(
                base_screen=BaseScreen.UNKNOWN,
                overlay=Overlay.NONE,
                confidence=0.0,
            ),
        )
    )

    assert source.taps == [(Point(x=100, y=50), 0.05)]
    assert source.swipes == [(Point(x=0, y=99), Point(x=199, y=0), 400, 5)]
    assert source.wait_for_frame_calls == 1
    assert source.latest_frame_calls == 0


def test_runtime_loop_state_rejects_legacy_analysis_refresher() -> None:
    snapshot = RuntimeAnalysisSnapshot(
        analysis=ScreenAnalysis(
            base_screen=BaseScreen.UNKNOWN,
            overlay=Overlay.NONE,
            confidence=0.0,
        ),
        analyzed_at=0.0,
        frame_id="frame-1",
    )

    with pytest.raises(TypeError, match="_analysis_snapshot_refresher"):
        RuntimeLoopState(
            frame=make_frame("frame-1"),
            analysis_snapshot=snapshot,
            now=0.0,
            analysis_running=False,
            session_info=FakeAdbSession(device_id="emulator-5554").info,
            _analysis_snapshot_refresher=lambda: None,
        )


class RecordingAnalyzer:
    def __init__(self) -> None:
        self._analysis = ScreenAnalysis(
            base_screen=BaseScreen.UNKNOWN,
            overlay=Overlay.NONE,
            confidence=0.0,
        )
        self._lock = threading.Lock()
        self.frame_ids: list[str | None] = []

    def __call__(self, image: FrameImage) -> ScreenAnalysis:
        with self._lock:
            self.frame_ids.append(image.frame_id)
        return self._analysis


class IncrementingClock:
    def __init__(self) -> None:
        self._value = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            value = self._value
            self._value += 1.0
        return value


class ActionFrameSource(FakeFrameSource):
    def __init__(self, *, frames: tuple[FrameImage, ...]) -> None:
        super().__init__(frames=frames)
        self.taps: list[tuple[Point, float]] = []
        self.swipes: list[tuple[Point, Point, int, int]] = []

    @property
    def action_surface_size(self) -> Size:
        return Size(width=200, height=100)

    def tap_pixels(self, point: Point, *, hold_seconds: float = 0.05) -> None:
        self.taps.append((point, hold_seconds))

    def swipe_pixels(
        self,
        start: Point,
        end: Point,
        *,
        duration_ms: int = 300,
        steps: int = 12,
    ) -> None:
        self.swipes.append((start, end, duration_ms, steps))
