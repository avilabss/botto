"""CLI tests for the read-only live preview command."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from io import StringIO

import pytest
from android_game_automator.image import FrameImage
from android_game_automator.types import DeviceIdentity, DeviceInfo, PixelFormat, SessionInfo, Size
from botto.cli import run
from botto.runner import DEFAULT_CLASH_PACKAGE


def test_live_preview_launches_default_package_and_starts_scrcpy_source() -> None:
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession(device_id="emulator-5554")
    backend = FakeBackend(session=session)
    source = FakeLiveSource(frames=(make_frame(),))
    source_factory = FakeLiveSourceFactory(source)
    preview = FakePreviewWindow(keys=(ord("q"),))

    exit_code = run(
        ["live-preview", "--device", "emulator-5554", "--max-fps", "7"],
        backend_factory=lambda: backend,
        live_source_factory=source_factory,
        preview_window=preview,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""
    assert backend.opened_device_ids == ["emulator-5554"]
    assert session.launched_packages == [DEFAULT_CLASH_PACKAGE]
    assert source_factory.created == [("emulator-5554", 7)]
    assert source.start_calls == 1
    assert source.stop_calls == 1
    assert session.closed is True
    assert preview.opened == ["Botto live preview"]
    assert preview.closed == ["Botto live preview"]
    assert len(preview.shown_frames) == 1


def test_live_preview_skip_launch_keeps_current_screen() -> None:
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession(device_id="emulator-5554")
    backend = FakeBackend(session=session)
    source = FakeLiveSource(frames=(make_frame(),))
    source_factory = FakeLiveSourceFactory(source)
    preview = FakePreviewWindow(keys=(27,))

    exit_code = run(
        [
            "live-preview",
            "--serial",
            "emulator-5554",
            "--skip-launch",
            "--package",
            "example.package",
            "--window-title",
            "Custom title",
        ],
        backend_factory=lambda: backend,
        live_source_factory=source_factory,
        preview_window=preview,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert backend.opened_device_ids == ["emulator-5554"]
    assert session.launched_packages == []
    assert source_factory.created == [("emulator-5554", 30)]
    assert preview.opened == ["Custom title"]
    assert preview.closed == ["Custom title"]
    assert len(preview.shown_frames) == 1


@pytest.mark.parametrize("exit_key", [ord("q"), 27])
def test_live_preview_exits_on_q_or_escape_without_input_or_recovery_actions(exit_key: int) -> None:
    session = FakeSession(device_id="emulator-5554")
    backend = FakeBackend(session=session)
    source = FakeLiveSource(frames=(make_frame("1"), make_frame("2"), make_frame("3")))
    source_factory = FakeLiveSourceFactory(source)
    preview = FakePreviewWindow(keys=(exit_key,))

    exit_code = run(
        ["live-preview", "--device", "emulator-5554", "--skip-launch"],
        backend_factory=lambda: backend,
        live_source_factory=source_factory,
        preview_window=preview,
    )

    assert exit_code == 0
    assert [frame.frame_id for frame in preview.shown_frames] == ["1"]
    assert session.input_actions == []
    assert session.recovery_actions == []
    assert source.stop_calls == 1
    assert session.closed is True


def make_frame(frame_id: str = "frame-1") -> FrameImage:
    return FrameImage(
        size=Size(width=1, height=1),
        pixel_format=PixelFormat.RGBA32,
        data=bytes((1, 2, 3, 255)),
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
            session_id=f"adb:{device_id}:live-preview",
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
    def __init__(self, *, frames: tuple[FrameImage, ...]) -> None:
        self._frames = frames
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def frames(self) -> Iterator[FrameImage]:
        yield from self._frames


class FakeLiveSourceFactory:
    def __init__(self, source: FakeLiveSource) -> None:
        self._source = source
        self.created: list[tuple[str, int]] = []

    def __call__(self, *, serial: str, max_fps: int) -> FakeLiveSource:
        self.created.append((serial, max_fps))
        return self._source


class FakePreviewWindow:
    def __init__(self, *, keys: tuple[int, ...]) -> None:
        self._keys = list(keys)
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
        if self._keys:
            return self._keys.pop(0)
        return -1

    def close(self, window_title: str) -> None:
        self.closed.append(window_title)
