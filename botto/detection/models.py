"""Botto screen and overlay classification models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from android_game_automator.types import NormalizedPoint


class BaseScreen(StrEnum):
    """High-level Clash screen states Botto can currently identify."""

    SUPERCELL_LOGO = "supercell_logo"
    LOADING = "loading"
    HOME_VILLAGE = "home_village"
    UNKNOWN = "unknown"


class Overlay(StrEnum):
    """Blocking overlays Botto can currently identify."""

    NONE = "none"
    CONNECTION_LOST = "connection_lost"
    ANOTHER_DEVICE_CONNECTED = "another_device_connected"
    ANYONE_THERE = "anyone_there"
    UNKNOWN_MODAL = "unknown_modal"


@dataclass(frozen=True, slots=True)
class Evidence:
    """Small evidence record explaining why a screen or overlay was classified."""

    kind: str
    label: str
    confidence: float
    text: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("kind must be non-empty")
        if not self.label.strip():
            raise ValueError("label must be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True, slots=True)
class RecommendedAction:
    """Read-only recovery suggestion for future automation code."""

    label: str
    tap_target: NormalizedPoint | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("label must be non-empty")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True, slots=True)
class ScreenAnalysis:
    """Combined base screen and overlay analysis for one screenshot."""

    base_screen: BaseScreen
    overlay: Overlay
    confidence: float
    evidence: tuple[Evidence, ...] = ()
    recommended_action: RecommendedAction | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")


__all__ = [
    "BaseScreen",
    "Evidence",
    "Overlay",
    "RecommendedAction",
    "ScreenAnalysis",
]
