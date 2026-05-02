"""Tests for scrcpy live frame conversion and lifecycle."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest
from android_game_automator.scrcpy import (
    ScrcpyFrameArray,
    ScrcpyFrameSource,
    frame_image_from_scrcpy_frame,
)
from android_game_automator.types import NormalizedPoint, PixelFormat, Point


def test_frame_image_from_scrcpy_bgr_frame_preserves_size_and_channel_order() -> None:
    frame = np.array(
        [
            [[10, 20, 30], [1, 2, 3]],
            [[200, 150, 100], [9, 8, 7]],
        ],
        dtype=np.uint8,
    )

    image = frame_image_from_scrcpy_frame(frame, frame_id="frame-1")

    assert image.size.width == 2
    assert image.size.height == 2
    assert image.pixel_format is PixelFormat.RGBA32
    assert image.frame_id == "frame-1"
    assert image.to_array() == (
        ((30, 20, 10, 255), (3, 2, 1, 255)),
        ((100, 150, 200, 255), (7, 8, 9, 255)),
    )


def test_scrcpy_frame_source_start_stop_are_idempotent() -> None:
    client = FakeScrcpyClient()
    created_configs = []
    source = ScrcpyFrameSource(
        serial="emulator-5554",
        max_fps=12,
        client_factory=lambda config: created_configs.append(config) or client,
    )

    source.start()
    source.start()
    source.stop()
    source.stop()

    assert len(created_configs) == 1
    assert created_configs[0].serial == "emulator-5554"
    assert created_configs[0].max_fps == 12
    assert client.start_calls == 1
    assert client.stop_calls == 1
    assert source.started is False


def test_scrcpy_frame_source_tap_swipe_map_normalized_points_to_frame_size() -> None:
    client = FakeScrcpyClient(frame_size=(200, 100))
    source = ScrcpyFrameSource(client_factory=lambda config: client)
    source.start()

    tap_pixel = source.tap(NormalizedPoint(x=0.25, y=0.5), hold_seconds=0.2)
    swipe_pixels = source.swipe(
        NormalizedPoint(x=0.0, y=1.0),
        NormalizedPoint(x=1.0, y=0.0),
        duration_ms=400,
        steps=5,
    )

    assert tap_pixel == Point(x=50, y=50)
    assert swipe_pixels == (Point(x=0, y=99), Point(x=199, y=0))
    assert client.taps == [(50, 50, 0.2)]
    assert client.swipes == [(0, 99, 199, 0, 400, 5)]


def test_scrcpy_frame_source_tap_requires_available_frame_size() -> None:
    client = FakeScrcpyClient(frame_size_error=RuntimeError("no frame yet"))
    source = ScrcpyFrameSource(client_factory=lambda config: client)
    source.start()

    with pytest.raises(RuntimeError, match="scrcpy frame size is not available"):
        source.tap(NormalizedPoint(x=0.5, y=0.5))


class FakeScrcpyClient:
    def __init__(
        self,
        *,
        frame_size: tuple[int, int] = (1, 1),
        frame_size_error: Exception | None = None,
    ) -> None:
        self.latest_frame: ScrcpyFrameArray | None = None
        self.frame_counter = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.taps: list[tuple[int, int, float]] = []
        self.swipes: list[tuple[int, int, int, int, int, int]] = []
        self._frame_size = frame_size
        self._frame_size_error = frame_size_error

    @property
    def frame_size(self) -> tuple[int, int]:
        if self._frame_size_error is not None:
            raise self._frame_size_error
        return self._frame_size

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def tap(self, x: int, y: int, *, hold_seconds: float = 0.05) -> None:
        self.taps.append((x, y, hold_seconds))

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        duration_ms: int = 300,
        steps: int = 12,
    ) -> None:
        self.swipes.append((x1, y1, x2, y2, duration_ms, steps))

    def get_frame(self, *, timeout: float | None = None, copy: bool = True) -> ScrcpyFrameArray:
        _ = timeout, copy
        self.frame_counter += 1
        return np.zeros((1, 1, 3), dtype=np.uint8)

    def frames(
        self, *, copy: bool = True, timeout: float | None = None
    ) -> Iterator[ScrcpyFrameArray]:
        _ = copy, timeout
        self.frame_counter += 1
        yield np.zeros((1, 1, 3), dtype=np.uint8)
