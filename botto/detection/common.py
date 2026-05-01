"""Small shared helpers for Botto detection modules."""

from __future__ import annotations

import re
from collections.abc import Iterable
from os import PathLike
from pathlib import Path
from typing import Protocol

from android_game_automator.image import FrameImage
from android_game_automator.types import Match, NormalizedPoint, ScreenRect


class TextReader(Protocol):
    """Callable shape used for OCR so tests can inject fakes."""

    def __call__(self, image: FrameImage, *, region: ScreenRect | None = None) -> str: ...


class TemplateMatcher(Protocol):
    """Callable shape used for template matching so tests can inject fakes."""

    def __call__(
        self,
        source: FrameImage,
        template: str | PathLike[str],
        *,
        region: ScreenRect | None = None,
        min_confidence: float = 0.9,
        scales: Iterable[float] = (1.0,),
    ) -> Match | None: ...


type BaseScreenDetection = tuple[BaseScreen, float, tuple[Evidence, ...]]
type OverlayDetection = tuple[Overlay, float, tuple[Evidence, ...], RecommendedAction]
type OverlayResult = tuple[Overlay, float, tuple[Evidence, ...], RecommendedAction | None]

_BLOCKING_POPUP_BUTTON_TAP_TARGET = NormalizedPoint(x=0.50, y=0.88)
_OCR_CONFIDENCE = 0.9


def blocking_overlay_result(
    overlay: Overlay,
    *,
    target: PopupButton,
    text: str,
    phrases: tuple[str, ...],
    region: ScreenRect,
) -> OverlayDetection:
    """Build the shared evidence/action tuple for known blocking popups."""

    evidence = Evidence(
        kind=EvidenceKind.OCR,
        subject=overlay,
        confidence=_OCR_CONFIDENCE,
        text=text,
        details={"region": region, "phrases": phrases},
    )
    action = RecommendedAction(
        kind=ActionKind.TAP,
        target=target,
        reason=overlay,
        tap_target=_BLOCKING_POPUP_BUTTON_TAP_TARGET,
    )
    return overlay, _OCR_CONFIDENCE, (evidence,), action


def template_evidence(
    image: FrameImage,
    *,
    template_path: Path,
    subject: EvidenceSubject,
    anchor: EvidenceAnchor | None = None,
    region: ScreenRect,
    min_confidence: float,
    find_template_fn: TemplateMatcher,
    scales: Iterable[float] | None = None,
    template_detail_name: str | None = None,
) -> Evidence | None:
    """Return template-match evidence when a detector anchor is present."""

    if scales is None:
        match = find_template_fn(
            image,
            template_path,
            region=region,
            min_confidence=min_confidence,
        )
    else:
        match = find_template_fn(
            image,
            template_path,
            region=region,
            min_confidence=min_confidence,
            scales=scales,
        )
    if match is None:
        return None

    return Evidence(
        kind=EvidenceKind.TEMPLATE,
        subject=subject,
        anchor=anchor,
        confidence=match.confidence,
        details={
            "bounds": match.bounds,
            "region": region,
            "template": template_detail_name
            if template_detail_name is not None
            else template_path.name,
        },
    )


def matching_phrases(text: str, phrases: Iterable[str]) -> tuple[str, ...] | None:
    """Return all phrases found in text, preserving phrase order."""

    matches = tuple(phrase for phrase in phrases if contains_phrase(text, phrase))
    if not matches:
        return None
    return matches


def first_matching_phrase(text: str, phrases: Iterable[str]) -> str | None:
    """Return the first phrase found in text."""

    for phrase in phrases:
        if contains_phrase(text, phrase):
            return phrase
    return None


def contains_phrase(text: str, phrase: str) -> bool:
    """Case/punctuation-tolerant substring phrase matching."""

    normalized_text = _normalize_text(text)
    if not normalized_text:
        return False
    return _normalize_text(phrase) in normalized_text


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


# Bind detection model classes after helpers are defined so package-level
# orchestration exports can import this module during package initialization.
from .actions import ActionKind, RecommendedAction  # noqa: E402, I001
from .evidence import Evidence, EvidenceAnchor, EvidenceKind, EvidenceSubject  # noqa: E402
from .overlays.models import Overlay, PopupButton  # noqa: E402
from .screens.models import BaseScreen  # noqa: E402


__all__ = [
    "BaseScreenDetection",
    "OverlayDetection",
    "OverlayResult",
    "TemplateMatcher",
    "TextReader",
    "blocking_overlay_result",
    "contains_phrase",
    "first_matching_phrase",
    "matching_phrases",
    "template_evidence",
]
