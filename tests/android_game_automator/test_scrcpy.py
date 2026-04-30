"""Tests for scrcpy live frame conversion and lifecycle."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
from android_game_automator.scrcpy import (
    ScrcpyFrameArray,
    ScrcpyFrameSource,
    frame_image_from_scrcpy_frame,
)
from android_game_automator.types import PixelFormat


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


class FakeScrcpyClient:
    def __init__(self) -> None:
        self.latest_frame: ScrcpyFrameArray | None = None
        self.frame_counter = 0
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

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
