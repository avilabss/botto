"""Tests for read-only active-battle loot progress tracking."""

from __future__ import annotations

import botto.automation as automation
from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect, ScreenRect
from botto.automation.battle import (
    BattleLootTracker,
    read_active_battle_available_loot,
)
from botto.automation.search import AvailableLoot

from tests.botto.fakes import make_frame


def test_read_active_battle_available_loot_uses_top_left_roi_and_parses_values() -> None:
    reader = FakeTextReader(
        """
        Available Loot:
        900 000
        800,000
        1 234
        """
    )

    loot = read_active_battle_available_loot(_frame(), read_text_fn=reader)

    assert loot == AvailableLoot(gold=900000, elixir=800000, dark_elixir=1234)
    assert len(reader.calls) == 1
    region = reader.calls[0]
    assert isinstance(region, NormalizedRect)
    assert region.left == 0.0
    assert region.top == 0.0
    assert region.width <= 0.35
    assert region.height <= 0.35


def test_battle_loot_tracker_reports_progress_when_remaining_decreases() -> None:
    tracker = BattleLootTracker()
    initial_loot = AvailableLoot(gold=100_000, elixir=50_000, dark_elixir=1_000)
    lower_loot = AvailableLoot(gold=99_000, elixir=49_500, dark_elixir=1_000)

    initial = tracker.update(initial_loot, now=1.0, resource_stall_seconds=10.0)
    progress = tracker.update(lower_loot, now=4.0, resource_stall_seconds=10.0)

    assert initial.initial_available_loot == initial_loot
    assert initial.latest_available_loot == initial_loot
    assert initial.total_remaining == 151_000
    assert initial.total_gained == 0
    assert initial.last_progress_at == 1.0
    assert initial.stalled is False

    assert progress.initial_available_loot == initial_loot
    assert progress.latest_available_loot == lower_loot
    assert progress.total_remaining == 149_500
    assert progress.total_gained == 1_500
    assert progress.last_progress_at == 4.0
    assert progress.stalled is False


def test_battle_loot_tracker_reports_stalled_only_after_configured_no_progress_duration() -> None:
    tracker = BattleLootTracker()
    loot = AvailableLoot(gold=100_000, elixir=50_000, dark_elixir=1_000)

    tracker.update(loot, now=1.0, resource_stall_seconds=10.0)
    not_stalled = tracker.update(loot, now=10.9, resource_stall_seconds=10.0)
    stalled = tracker.update(loot, now=11.0, resource_stall_seconds=10.0)

    assert not_stalled.stalled is False
    assert stalled.stalled is True
    assert stalled.last_progress_at == 1.0


def test_battle_loot_tracker_ignores_unreadable_samples_for_stall_state() -> None:
    tracker = BattleLootTracker()
    loot = AvailableLoot(gold=100_000, elixir=50_000, dark_elixir=1_000)

    empty = tracker.update(None, now=100.0, resource_stall_seconds=10.0)
    tracker.update(loot, now=1.0, resource_stall_seconds=10.0)
    unreadable = tracker.update(None, now=20.0, resource_stall_seconds=10.0)
    confirmed_no_progress = tracker.update(loot, now=20.0, resource_stall_seconds=10.0)

    assert empty.initial_available_loot is None
    assert empty.latest_available_loot is None
    assert empty.total_remaining is None
    assert empty.total_gained is None
    assert empty.last_progress_at is None
    assert empty.stalled is False

    assert unreadable.latest_available_loot == loot
    assert unreadable.last_progress_at == 1.0
    assert unreadable.stalled is False
    assert confirmed_no_progress.stalled is True


def test_battle_loot_tracker_reset_starts_a_new_progress_session() -> None:
    tracker = BattleLootTracker()
    first_loot = AvailableLoot(gold=100_000, elixir=50_000, dark_elixir=1_000)
    second_loot = AvailableLoot(gold=200_000, elixir=75_000, dark_elixir=2_000)

    tracker.update(first_loot, now=1.0, resource_stall_seconds=10.0)
    tracker.update(
        AvailableLoot(gold=90_000, elixir=50_000, dark_elixir=1_000),
        now=2.0,
        resource_stall_seconds=10.0,
    )
    tracker.reset()
    reset = tracker.progress
    new_session = tracker.update(second_loot, now=30.0, resource_stall_seconds=10.0)

    assert reset.initial_available_loot is None
    assert reset.latest_available_loot is None
    assert reset.total_remaining is None
    assert reset.total_gained is None
    assert reset.last_progress_at is None
    assert reset.stalled is False

    assert new_session.initial_available_loot == second_loot
    assert new_session.latest_available_loot == second_loot
    assert new_session.total_remaining == 277_000
    assert new_session.total_gained == 0
    assert new_session.last_progress_at == 30.0
    assert new_session.stalled is False


def test_battle_loot_helpers_are_exported_from_automation_package() -> None:
    assert automation.BattleLootTracker is BattleLootTracker
    assert automation.read_active_battle_available_loot is read_active_battle_available_loot


def _frame() -> FrameImage:
    return make_frame(frame_id=None, width=160, height=90, rgba=(0, 0, 0, 255))


class FakeTextReader:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[ScreenRect | None] = []

    def __call__(self, image: FrameImage, *, region: ScreenRect | None = None) -> str:
        _ = image
        self.calls.append(region)
        return self._text
