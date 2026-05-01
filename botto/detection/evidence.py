"""Detection evidence models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class EvidenceKind(StrEnum):
    """How a detector produced a piece of classification evidence."""

    OCR = "ocr"
    TEMPLATE = "template"


type EvidenceSubject = BaseScreen | Overlay
type EvidenceAnchor = HomeElement | PopupButton | ScreenElement


@dataclass(frozen=True, slots=True)
class Evidence:
    """Small evidence record explaining why a screen or overlay was classified."""

    kind: EvidenceKind
    subject: EvidenceSubject
    confidence: float
    anchor: EvidenceAnchor | None = None
    text: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceKind):
            raise TypeError("kind must be an EvidenceKind")
        if not isinstance(self.subject, (BaseScreen, Overlay)):
            raise TypeError("subject must be a BaseScreen or Overlay")
        if self.anchor is not None and not isinstance(
            self.anchor,
            (HomeElement, PopupButton, ScreenElement),
        ):
            raise TypeError("anchor must be a HomeElement, PopupButton, ScreenElement, or None")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    @property
    def display_label(self) -> str:
        """Human-readable label for debug overlays and logs."""

        subject_label = _subject_display_label(self.subject)
        if self.anchor is None:
            return subject_label
        if isinstance(self.subject, Overlay):
            return f"{subject_label}.{self.anchor.value}"
        return self.anchor.value


def _subject_display_label(subject: EvidenceSubject) -> str:
    if isinstance(subject, Overlay) and subject is not Overlay.NONE:
        return f"modal.{subject.value}"
    return subject.value


# Bind model classes after Evidence is defined so package-level orchestration
# exports can load without circular imports.
from .overlays.models import Overlay, PopupButton  # noqa: E402, I001
from .screens.models import BaseScreen, HomeElement, ScreenElement  # noqa: E402


__all__ = [
    "Evidence",
    "EvidenceAnchor",
    "EvidenceKind",
    "EvidenceSubject",
]
