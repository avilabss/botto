"""Tests for Botto's normalized action executor."""

from __future__ import annotations

from android_game_automator.types import NormalizedPoint, Point, Size
from botto.automation.actions import ActionExecutor


def test_action_executor_maps_normalized_tap_and_calls_backend() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    executor = ActionExecutor(backend)

    pixel = executor.tap(
        NormalizedPoint(x=0.25, y=0.5),
        label="attack-button",
        reason="test",
        hold_seconds=0.2,
    )

    assert pixel == Point(x=50, y=50)
    assert backend.taps == [(Point(x=50, y=50), 0.2)]
    assert backend.swipes == []


def test_action_executor_maps_normalized_swipe_and_calls_backend() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    executor = ActionExecutor(backend)

    pixels = executor.swipe(
        NormalizedPoint(x=0.0, y=1.0),
        NormalizedPoint(x=1.0, y=0.0),
        label="pan",
        reason="test",
        duration_ms=400,
        steps=5,
    )

    assert pixels == (Point(x=0, y=99), Point(x=199, y=0))
    assert backend.swipes == [(Point(x=0, y=99), Point(x=199, y=0), 400, 5)]
    assert backend.taps == []


class FakeActionBackend:
    def __init__(self, size: Size) -> None:
        self._size = size
        self.taps: list[tuple[Point, float]] = []
        self.swipes: list[tuple[Point, Point, int, int]] = []

    @property
    def action_surface_size(self) -> Size:
        return self._size

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
