"""Shared fakes for Botto tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

from android_game_automator.image import FrameImage
from android_game_automator.types import (
    DeviceIdentity,
    DeviceInfo,
    PixelFormat,
    SessionInfo,
    Size,
)

DEFAULT_BOTTO_CONFIG_TEXT = """\
[attack]
strategy = "mass-super-minion"

[attack.resources]
min_gold = 500000
min_elixir = 500000
min_dark_elixir = 5000

[attack.search]
max_searches = 50

[attack.battle]
resource_stall_seconds = 20
"""

DEFAULT_STRATEGY_TEXT = """\
[[actions]]
type = "cast_spell_on_detected_targets"
spell = "lightning"
targets = ["air_defense"]
casts_per_target = 3

[[actions]]
type = "deploy_unit_around_perimeter"
unit = "super_minion"
points_per_side = 4
waves = 1

[[actions]]
type = "deploy_group_on_one_side"
group = "cc_and_heroes"
side = "auto"

[[actions]]
type = "activate_hero_abilities"
heroes = [
  "barbarian_king",
  "archer_queen",
  "grand_warden",
  "royal_champion",
]
"""


def write_default_botto_config(directory: Path) -> Path:
    config_path = directory / "botto.toml"
    config_path.write_text(DEFAULT_BOTTO_CONFIG_TEXT, encoding="utf-8")
    return config_path


def write_default_strategy_file(directory: Path, *, name: str = "mass-super-minion") -> Path:
    strategy_dir = directory / "strategies"
    strategy_dir.mkdir(exist_ok=True)
    strategy_path = strategy_dir / f"{name}.toml"
    strategy_path.write_text(DEFAULT_STRATEGY_TEXT, encoding="utf-8")
    return strategy_path


def make_frame(
    frame_id: str | None = "frame-1",
    *,
    width: int = 40,
    height: int = 30,
    rgba: tuple[int, int, int, int] = (1, 2, 3, 255),
    captured_at: datetime | None = None,
) -> FrameImage:
    return FrameImage(
        size=Size(width=width, height=height),
        pixel_format=PixelFormat.RGBA32,
        data=bytes(rgba) * width * height,
        captured_at=captured_at if captured_at is not None else datetime.now(UTC),
        frame_id=frame_id,
    )


def make_device_info(
    device_id: str,
    *,
    display_name: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> DeviceInfo:
    return DeviceInfo(
        identity=DeviceIdentity(
            backend_name="adb",
            device_id=device_id,
            display_name=display_name or device_id,
        ),
        metadata=metadata if metadata is not None else {"adb.target_kind": "emulator"},
    )


class FakeAdbSession:
    def __init__(self, *, device_id: str) -> None:
        self._info = SessionInfo(
            session_id=f"adb:{device_id}:debug-preview",
            device=make_device_info(device_id),
            started_at=datetime.now(UTC),
            metadata={"adb.target_kind": "emulator"},
        )
        self.closed = False
        self.launched_packages: list[str] = []
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


class FakeAdbBackend:
    def __init__(
        self,
        *,
        devices: tuple[DeviceInfo, ...] | None = None,
        session: FakeAdbSession | None = None,
    ) -> None:
        self._session = session
        self._devices = devices if devices is not None else self._devices_for_session(session)
        self.opened_device_ids: list[str | None] = []

    async def list_devices(self) -> tuple[DeviceInfo, ...]:
        return self._devices

    async def open_session(self, device_id: str | None = None) -> FakeAdbSession:
        if self._session is None:
            raise AssertionError("FakeAdbBackend requires a session for open_session")
        self.opened_device_ids.append(device_id)
        return self._session

    @staticmethod
    def _devices_for_session(session: FakeAdbSession | None) -> tuple[DeviceInfo, ...]:
        if session is None:
            return ()
        return (session.info.device,)


class FakeFrameSource:
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
            raise AssertionError("debug preview must not consume queued frames for display")
        yield from self._frames


class FakeFrameSourceFactory:
    def __init__(self, source: FakeFrameSource) -> None:
        self._source = source
        self.created: list[tuple[str, int]] = []

    def __call__(self, *, serial: str, max_fps: int) -> FakeFrameSource:
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
