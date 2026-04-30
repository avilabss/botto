"""Reusable template descriptors for ROI-first vision detectors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from android_game_automator.core import ScreenRect
from android_game_automator.core._immutables import freeze_mapping

from .image import FrameImage


@dataclass(frozen=True, slots=True)
class VisionTemplate:
    """Single labeled template with local search constraints."""

    label: str
    image: FrameImage
    min_confidence: float = 0.9
    scales: tuple[float, ...] = (1.0,)
    region: ScreenRect | None = None
    attributes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("label must be non-empty")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within [0.0, 1.0]")

        scales = tuple(self.scales)
        if not scales:
            raise ValueError("scales must contain at least one value")
        if any(scale <= 0.0 for scale in scales):
            raise ValueError("scales must be > 0.0")

        object.__setattr__(self, "scales", scales)
        object.__setattr__(self, "attributes", freeze_mapping(self.attributes))
