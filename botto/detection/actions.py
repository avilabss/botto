"""Read-only recommended action models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from android_game_automator.types import NormalizedPoint


class ActionKind(StrEnum):
    """Kinds of read-only recommended actions Botto can describe."""

    TAP = "tap"


@dataclass(frozen=True, slots=True)
class RecommendedAction:
    """Read-only recovery suggestion for future automation code."""

    kind: ActionKind
    target: PopupButton
    reason: Overlay | None = None
    tap_target: NormalizedPoint | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ActionKind):
            raise TypeError("kind must be an ActionKind")
        if not isinstance(self.target, PopupButton):
            raise TypeError("target must be a PopupButton")
        if self.reason is not None and not isinstance(self.reason, Overlay):
            raise TypeError("reason must be an Overlay or None")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    @property
    def display_label(self) -> str:
        """Human-readable label for debug overlays and logs."""

        return f"{self.kind.value}_{self.target.value}"


# Bind overlay model classes after RecommendedAction is defined so package-level
# overlay orchestration exports can load without circular imports.
from .overlays.models import Overlay, PopupButton  # noqa: E402, I001


__all__ = ["ActionKind", "RecommendedAction"]
