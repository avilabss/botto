"""Screen analysis aggregate model."""

from __future__ import annotations

from dataclasses import dataclass

from .actions import RecommendedAction
from .evidence import Evidence
from .overlays.models import Overlay
from .screens.models import BaseScreen


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


__all__ = ["ScreenAnalysis"]
