"""CLI and renderer tests for the read-only live debug command."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from io import StringIO

import botto.live as live_module
import pytest
from android_game_automator.image import FrameImage
from android_game_automator.types import (
    DeviceIdentity,
    DeviceInfo,
    NormalizedPoint,
    PixelFormat,
    Point,
    SessionInfo,
    Size,
)
from botto.cli import run
from botto.live import LiveAnalysisSnapshot, render_debug_overlay, run_live_debug
from botto.runner import DEFAULT_CLASH_PACKAGE
from botto.screens import BaseScreen, Evidence, Overlay, RecommendedAction, ScreenAnalysis


def test_live_debug_launches_default_package_and_starts_scrcpy_source() -> None:
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession(device_id="emulator-5554")
    backend = FakeBackend(session=session)
    source = FakeLiveSource(frames=(make_frame("frame-1"),))
    source_factory = FakeLiveSourceFactory(source)
    preview = FakePreviewWindow(keys=(ord("q"),))
    analyzer = FakeAnalyzer()

    exit_code = run(
        [
            "live-debug",
            "--device",
            "emulator-5554",
            "--max-fps",
            "7",
            "--analyze-every-seconds",
            "1.5",
        ],
        backend_factory=lambda: backend,
        live_source_factory=source_factory,
        preview_window=preview,
        screen_analyzer=analyzer,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""
    assert backend.opened_device_ids == ["emulator-5554"]
    assert session.launched_packages == [DEFAULT_CLASH_PACKAGE]
    assert source_factory.created == [("emulator-5554", 7)]
    assert analyzer.frame_ids == ["frame-1"]
    assert source.start_calls == 1
    assert source.stop_calls == 1
    assert session.closed is True
    assert preview.opened == ["Botto live debug"]
    assert preview.closed == ["Botto live debug"]
    assert [frame.frame_id for frame in preview.shown_frames] == ["frame-1"]


def test_live_debug_skip_launch_keeps_current_screen() -> None:
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession(device_id="emulator-5554")
    backend = FakeBackend(session=session)
    source = FakeLiveSource(frames=(make_frame("frame-1"),))
    source_factory = FakeLiveSourceFactory(source)
    preview = FakePreviewWindow(keys=(27,))

    exit_code = run(
        [
            "live-debug",
            "--serial",
            "emulator-5554",
            "--skip-launch",
            "--package",
            "example.package",
            "--window-title",
            "Custom debug title",
        ],
        backend_factory=lambda: backend,
        live_source_factory=source_factory,
        preview_window=preview,
        screen_analyzer=FakeAnalyzer(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert backend.opened_device_ids == ["emulator-5554"]
    assert session.launched_packages == []
    assert source_factory.created == [("emulator-5554", 30)]
    assert preview.opened == ["Custom debug title"]
    assert preview.closed == ["Custom debug title"]
    assert len(preview.shown_frames) == 1


def test_live_debug_throttles_analysis_and_reuses_latest_result_between_frames() -> None:
    session = FakeSession(device_id="emulator-5554")
    backend = FakeBackend(session=session)
    source = FakeLiveSource(
        frames=(make_frame("frame-1"), make_frame("frame-2"), make_frame("frame-3"))
    )
    source_factory = FakeLiveSourceFactory(source)
    preview = FakePreviewWindow(keys=(-1, -1, ord("q")))
    analyzer = FakeAnalyzer()

    asyncio.run(
        run_live_debug(
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
    snapshot: LiveAnalysisSnapshot | None,
    *,
    now: float | None = None,
    analysis_running: bool = False,
) -> FrameImage:
    _ = snapshot, now, analysis_running
    return frame


def test_live_debug_renders_newer_frames_while_slow_analysis_runs_single_flight() -> None:
    session = FakeSession(device_id="emulator-5554")
    backend = FakeBackend(session=session)
    source = FakeLiveSource(
        frames=(make_frame("frame-1"), make_frame("frame-2"), make_frame("frame-3"))
    )
    source_factory = FakeLiveSourceFactory(source)
    analyzer = BlockingAnalyzer()
    preview = FakePreviewWindow(
        keys=(-1, -1, ord("q")),
        wait_callbacks=(analyzer.wait_until_started, None, analyzer.release),
    )
    renderer = CapturingRenderer()

    asyncio.run(
        run_live_debug(
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


def test_live_debug_uses_latest_frame_without_consuming_stale_frame_queue() -> None:
    session = FakeSession(device_id="emulator-5554")
    backend = FakeBackend(session=session)
    source = FakeLiveSource(
        frames=(make_frame("queued-stale-frame"),),
        latest_frames=(make_frame("latest-frame"),),
        fail_on_frames=True,
    )
    source_factory = FakeLiveSourceFactory(source)
    preview = FakePreviewWindow(keys=(ord("q"),))

    asyncio.run(
        run_live_debug(
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


def test_debug_status_lines_indicate_analysis_running_with_timing() -> None:
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.NONE,
        confidence=0.0,
    )
    snapshot = LiveAnalysisSnapshot(
        analysis=analysis,
        analyzed_at=1.0,
        duration_seconds=0.25,
        frame_id="frame-1",
    )

    assert live_module._debug_status_lines(None, now=1.0, analysis_running=True) == (
        "analysis: running",
    )
    lines = live_module._debug_status_lines(snapshot, now=2.0, analysis_running=True)

    assert lines[-1] == "analysis age: 1.0s  took: 0.25s  running"


def test_debug_overlay_renderer_annotates_copy_with_evidence_and_target() -> None:
    frame = make_frame("frame-1", width=80, height=60, rgba=(10, 20, 30, 255))
    original_data = frame.data
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.CONNECTION_LOST,
        confidence=0.9,
        evidence=(
            Evidence(
                kind="ocr",
                label="modal.connection_lost",
                confidence=0.9,
                text="Connection lost",
                details={
                    "bounds": {"left": 10, "top": 10, "width": 20, "height": 12},
                    "region": {"left": 0.5, "top": 0.2, "width": 0.25, "height": 0.3},
                },
            ),
        ),
        recommended_action=RecommendedAction(
            label="tap_try_again",
            tap_target=NormalizedPoint(x=0.5, y=0.88),
        ),
    )

    annotated = render_debug_overlay(
        frame,
        LiveAnalysisSnapshot(
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
def test_live_debug_exits_on_q_or_escape_cleans_up_background_work_and_remains_read_only(
    exit_key: int,
) -> None:
    session = FakeSession(device_id="emulator-5554")
    backend = FakeBackend(session=session)
    source = FakeLiveSource(frames=(make_frame("1"), make_frame("2"), make_frame("3")))
    source_factory = FakeLiveSourceFactory(source)
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.ANYONE_THERE,
        confidence=0.9,
        recommended_action=RecommendedAction(
            label="tap_reload_game",
            tap_target=NormalizedPoint(x=0.5, y=0.88),
        ),
    )
    analyzer = BlockingAnalyzer(analysis)
    preview = FakePreviewWindow(
        keys=(exit_key,),
        wait_callbacks=(analyzer.wait_until_started_and_release,),
    )

    exit_code = run(
        ["live-debug", "--device", "emulator-5554", "--skip-launch"],
        backend_factory=lambda: backend,
        live_source_factory=source_factory,
        preview_window=preview,
        screen_analyzer=analyzer,
    )

    assert exit_code == 0
    assert [frame.frame_id for frame in preview.shown_frames] == ["1"]
    assert session.input_actions == []
    assert session.recovery_actions == []
    assert analyzer.frame_ids == ["1"]
    assert analyzer.finished.is_set()
    assert source.stop_calls == 1
    assert session.closed is True


def make_frame(
    frame_id: str = "frame-1",
    *,
    width: int = 40,
    height: int = 30,
    rgba: tuple[int, int, int, int] = (1, 2, 3, 255),
) -> FrameImage:
    return FrameImage(
        size=Size(width=width, height=height),
        pixel_format=PixelFormat.RGBA32,
        data=bytes(rgba) * width * height,
        captured_at=datetime.now(UTC),
        frame_id=frame_id,
    )


def make_device_info(device_id: str) -> DeviceInfo:
    return DeviceInfo(
        identity=DeviceIdentity(
            backend_name="adb",
            device_id=device_id,
            display_name=device_id,
        ),
        metadata={"adb.target_kind": "emulator"},
    )


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
        snapshot: LiveAnalysisSnapshot | None,
        *,
        now: float | None = None,
        analysis_running: bool = False,
    ) -> FrameImage:
        _ = snapshot, now
        self.calls.append(RenderCall(frame_id=frame.frame_id, analysis_running=analysis_running))
        return frame


class FakeBackend:
    def __init__(self, *, session: FakeSession) -> None:
        self._session = session
        self.opened_device_ids: list[str | None] = []

    async def list_devices(self) -> tuple[DeviceInfo, ...]:
        return (self._session.info.device,)

    async def open_session(self, device_id: str | None = None) -> FakeSession:
        self.opened_device_ids.append(device_id)
        return self._session


class FakeSession:
    def __init__(self, *, device_id: str) -> None:
        self._info = SessionInfo(
            session_id=f"adb:{device_id}:live-debug",
            device=make_device_info(device_id),
            started_at=datetime.now(UTC),
            metadata={"adb.target_kind": "emulator"},
        )
        self.closed = False
        self.launched_packages: list[str] = []
        self.input_actions: list[str] = []
        self.recovery_actions: list[str] = []

    @property
    def info(self) -> SessionInfo:
        return self._info

    async def close(self) -> None:
        self.closed = True

    async def launch_app(self, package_name: str) -> None:
        self.launched_packages.append(package_name)

    async def close_app(self, package_name: str) -> None:
        self.recovery_actions.append(f"close_app:{package_name}")

    async def tap(self, *args: object, **kwargs: object) -> None:
        _ = args, kwargs
        self.input_actions.append("tap")

    async def swipe(self, *args: object, **kwargs: object) -> None:
        _ = args, kwargs
        self.input_actions.append("swipe")


class FakeLiveSource:
    def __init__(
        self,
        *,
        frames: tuple[FrameImage, ...],
        latest_frames: tuple[FrameImage, ...] | None = None,
        fail_on_frames: bool = False,
    ) -> None:
        self._frames = frames
        self._latest_frames = latest_frames if latest_frames is not None else frames
        self._latest_frame_index = 0
        self._fail_on_frames = fail_on_frames
        self.start_calls = 0
        self.stop_calls = 0
        self.latest_frame_calls = 0
        self.frames_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def latest_frame(self) -> FrameImage | None:
        self.latest_frame_calls += 1
        if self._latest_frame_index >= len(self._latest_frames):
            return None
        frame = self._latest_frames[self._latest_frame_index]
        self._latest_frame_index += 1
        return frame

    def frames(self) -> Iterator[FrameImage]:
        self.frames_calls += 1
        if self._fail_on_frames:
            raise AssertionError("live-debug must not consume queued frames for display")
        yield from self._frames


class FakeLiveSourceFactory:
    def __init__(self, source: FakeLiveSource) -> None:
        self._source = source
        self.created: list[tuple[str, int]] = []

    def __call__(self, *, serial: str, max_fps: int) -> FakeLiveSource:
        self.created.append((serial, max_fps))
        return self._source


class FakePreviewWindow:
    def __init__(
        self,
        *,
        keys: tuple[int, ...],
        wait_callbacks: tuple[Callable[[], None] | None, ...] = (),
    ) -> None:
        self._keys = list(keys)
        self._wait_callbacks = list(wait_callbacks)
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.shown_frames: list[FrameImage] = []

    def open(self, window_title: str) -> None:
        self.opened.append(window_title)

    def show(self, window_title: str, frame: FrameImage) -> None:
        _ = window_title
        self.shown_frames.append(frame)

    def wait_key(self, delay_ms: int) -> int:
        _ = delay_ms
        if self._wait_callbacks:
            callback = self._wait_callbacks.pop(0)
            if callback is not None:
                callback()
        if self._keys:
            return self._keys.pop(0)
        return -1

    def close(self, window_title: str) -> None:
        self.closed.append(window_title)
