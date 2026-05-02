"""Read-only active-battle loot progress tracking helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from android_game_automator.image import FrameImage
from android_game_automator.ocr import read_text
from android_game_automator.types import NormalizedRect, ScreenRect

from .search import AvailableLoot, parse_available_loot_text

_ACTIVE_BATTLE_AVAILABLE_LOOT_REGION = NormalizedRect(left=0.0, top=0.0, width=0.32, height=0.30)


class BattleLootTextReader(Protocol):
    """Callable shape used for active-battle OCR so tests can inject fakes."""

    def __call__(self, image: FrameImage, *, region: ScreenRect | None = None) -> str: ...


@dataclass(frozen=True, slots=True)
class BattleLootProgress:
    """Read-only summary of active-battle available-loot progress."""

    initial_available_loot: AvailableLoot | None
    latest_available_loot: AvailableLoot | None
    total_remaining: int | None
    total_gained: int | None
    last_progress_at: float | None
    stalled: bool


class BattleLootTracker:
    """Track active-battle loot changes without taking gameplay actions."""

    def __init__(self) -> None:
        self._initial_available_loot: AvailableLoot | None = None
        self._latest_available_loot: AvailableLoot | None = None
        self._last_progress_at: float | None = None
        self._stalled = False

    @property
    def progress(self) -> BattleLootProgress:
        """Return the current read-only loot-progress summary."""

        return self._progress_snapshot()

    def reset(self) -> None:
        """Clear state for a new search/attack session."""

        self._initial_available_loot = None
        self._latest_available_loot = None
        self._last_progress_at = None
        self._stalled = False

    def update(
        self,
        available_loot: AvailableLoot | None,
        *,
        now: float,
        resource_stall_seconds: float,
    ) -> BattleLootProgress:
        """Record a readable loot sample and report whether progress has stalled.

        ``None`` represents unreadable OCR and leaves tracker state unchanged; unreadable
        frames must not create initial data or advance the stall decision.
        """

        if available_loot is None:
            return self._progress_snapshot()

        if self._initial_available_loot is None:
            self._initial_available_loot = available_loot
            self._latest_available_loot = available_loot
            self._last_progress_at = now
            self._stalled = False
            return self._progress_snapshot()

        previous_latest = self._latest_available_loot
        if previous_latest is None:
            raise RuntimeError("battle loot tracker missing latest sample")

        current_total = total_available_loot(available_loot)
        previous_total = total_available_loot(previous_latest)
        if current_total < previous_total:
            self._last_progress_at = now
            self._stalled = False
        elif self._last_progress_at is not None:
            self._stalled = now - self._last_progress_at >= resource_stall_seconds

        self._latest_available_loot = available_loot
        return self._progress_snapshot()

    def _progress_snapshot(self) -> BattleLootProgress:
        latest = self._latest_available_loot
        initial = self._initial_available_loot
        total_remaining = total_available_loot(latest) if latest is not None else None
        total_gained = _total_gained(initial, latest)
        return BattleLootProgress(
            initial_available_loot=initial,
            latest_available_loot=latest,
            total_remaining=total_remaining,
            total_gained=total_gained,
            last_progress_at=self._last_progress_at,
            stalled=self._stalled,
        )


def read_active_battle_available_loot(
    image: FrameImage,
    *,
    read_text_fn: BattleLootTextReader = read_text,
) -> AvailableLoot | None:
    """OCR and parse the top-left active-battle Available Loot values."""

    text = read_text_fn(image, region=_ACTIVE_BATTLE_AVAILABLE_LOOT_REGION)
    return parse_available_loot_text(text)


def total_available_loot(available_loot: AvailableLoot) -> int:
    """Return the mixed-resource available-loot total used for progress estimates."""

    return available_loot.gold + available_loot.elixir + available_loot.dark_elixir


def _total_gained(
    initial: AvailableLoot | None,
    latest: AvailableLoot | None,
) -> int | None:
    if initial is None or latest is None:
        return None
    return max(total_available_loot(initial) - total_available_loot(latest), 0)


__all__ = [
    "BattleLootProgress",
    "BattleLootTextReader",
    "BattleLootTracker",
    "read_active_battle_available_loot",
    "total_available_loot",
]
