"""Detection request and result contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from ._immutables import freeze_mapping
from .geometry import NormalizedRect, ScreenRect


@dataclass(frozen=True, slots=True)
class DetectionRequest:
    """Query constraints for a detection pass."""

    labels: tuple[str, ...] = ()
    min_confidence: float = 0.0
    max_results: int | None = None
    region: ScreenRect | None = None

    def __post_init__(self) -> None:
        labels = tuple(self.labels)
        object.__setattr__(self, "labels", labels)
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within [0.0, 1.0]")
        if self.max_results is not None and self.max_results <= 0:
            raise ValueError("max_results must be > 0 when provided")
        for label in labels:
            if not label.strip():
                raise ValueError("labels must not contain empty values")


@dataclass(frozen=True, slots=True)
class Detection:
    """Single detected entity from a detector backend."""

    label: str
    confidence: float
    bounds: NormalizedRect | None = None
    attributes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("label must be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        object.__setattr__(self, "attributes", freeze_mapping(self.attributes))


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Batch detection output for a frame."""

    detections: tuple[Detection, ...]
    produced_at: datetime
    frame_id: str | None = None
    detector_name: str | None = None

    def __post_init__(self) -> None:
        detections = tuple(self.detections)
        object.__setattr__(self, "detections", detections)
        if self.frame_id is not None and not self.frame_id.strip():
            raise ValueError("frame_id must be non-empty when provided")
        if self.detector_name is not None and not self.detector_name.strip():
            raise ValueError("detector_name must be non-empty when provided")
