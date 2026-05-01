"""Tests for Botto's read-only runtime loop primitive."""

from __future__ import annotations

import asyncio
import threading

from android_game_automator.image import FrameImage
from botto.detection.models import BaseScreen, Overlay, ScreenAnalysis
from botto.runtime import (
    DEFAULT_CLASH_PACKAGE,
    DEFAULT_RUNTIME_MAX_FPS,
    RuntimeLoopState,
    run_read_only_runtime,
)

from tests.botto.fakes import (
    FakeAdbBackend,
    FakeAdbSession,
    FakeLiveSource,
    FakeLiveSourceFactory,
    make_frame,
)


def test_runtime_delivers_newer_frames_while_slow_analysis_runs() -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeLiveSource(
        frames=(make_frame("frame-1"), make_frame("frame-2"), make_frame("frame-3"))
    )
    source_factory = FakeLiveSourceFactory(source)
    analyzer = BlockingAnalyzer()
    delivered_frame_ids: list[str | None] = []
    analysis_running: list[bool] = []

    def sink(state: RuntimeLoopState) -> bool:
        if state.frame is None:
            return True
        if not delivered_frame_ids:
            analyzer.wait_until_started()
        delivered_frame_ids.append(state.frame.frame_id)
        analysis_running.append(state.analysis_running)
        if len(delivered_frame_ids) == 3:
            analyzer.release()
            return False
        return True

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

    assert delivered_frame_ids == ["frame-1", "frame-2", "frame-3"]
    assert analysis_running == [True, True, True]
    assert analyzer.frame_id_snapshot() == ["frame-1"]
    assert analyzer.finished.is_set()


def test_runtime_analyzer_is_single_flight_with_no_queued_jobs() -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeLiveSource(
        frames=(
            make_frame("frame-1"),
            make_frame("frame-2"),
            make_frame("frame-3"),
            make_frame("frame-4"),
            make_frame("frame-5"),
        )
    )
    source_factory = FakeLiveSourceFactory(source)
    analyzer = BlockingAnalyzer()
    delivered_frame_ids: list[str | None] = []

    def sink(state: RuntimeLoopState) -> bool:
        if state.frame is None:
            return True
        if not delivered_frame_ids:
            analyzer.wait_until_started()
        delivered_frame_ids.append(state.frame.frame_id)
        assert analyzer.frame_id_snapshot() == ["frame-1"]
        if len(delivered_frame_ids) == 5:
            analyzer.release()
            return False
        return True

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

    assert delivered_frame_ids == ["frame-1", "frame-2", "frame-3", "frame-4", "frame-5"]
    assert analyzer.frame_id_snapshot() == ["frame-1"]
    assert analyzer.finished.is_set()


def test_runtime_exit_callback_stops_source_closes_session_and_waits_for_analysis() -> None:
    session = FakeAdbSession(device_id="emulator-5554")
    backend = FakeAdbBackend(session=session)
    source = FakeLiveSource(frames=(make_frame("frame-1"), make_frame("frame-2")))
    source_factory = FakeLiveSourceFactory(source)
    analyzer = BlockingAnalyzer()

    def sink(state: RuntimeLoopState) -> bool:
        assert state.frame is not None
        analyzer.wait_until_started()
        analyzer.release()
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
    assert source.latest_frame_calls == 1
    assert session.closed is True
    assert session.recovery_actions == []
    assert not hasattr(session, "tap")
    assert not hasattr(session, "swipe")
    assert analyzer.finished.is_set()


class BlockingAnalyzer:
    def __init__(self) -> None:
        self._analysis = ScreenAnalysis(
            base_screen=BaseScreen.UNKNOWN,
            overlay=Overlay.NONE,
            confidence=0.0,
        )
        self.started = threading.Event()
        self._release = threading.Event()
        self.finished = threading.Event()
        self._lock = threading.Lock()
        self._frame_ids: list[str | None] = []

    def __call__(self, image: FrameImage) -> ScreenAnalysis:
        with self._lock:
            self._frame_ids.append(image.frame_id)
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

    def frame_id_snapshot(self) -> list[str | None]:
        with self._lock:
            return list(self._frame_ids)


class IncrementingClock:
    def __init__(self) -> None:
        self._value = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            value = self._value
            self._value += 1.0
        return value
