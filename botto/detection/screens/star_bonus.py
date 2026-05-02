"""Star-bonus reward base-screen template and OCR anchors."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TemplateMatcher, TextReader, contains_phrase, template_evidence
from ..evidence import Evidence, EvidenceKind
from ..templates import STAR_BONUS_OKAY_BUTTON_TEMPLATE, attack_flow_template_scales
from .models import BaseScreen, ScreenElement

_STAR_BONUS_TITLE_REGION = NormalizedRect(left=0.28, top=0.04, width=0.44, height=0.12)
_OKAY_BUTTON_REGION = NormalizedRect(left=0.42, top=0.78, width=0.17, height=0.15)
_STAR_BONUS_TEMPLATE_CONFIDENCE = 0.82
_STAR_BONUS_OCR_CONFIDENCE = 0.88


def detect_star_bonus(
    image: FrameImage,
    *,
    read_text_fn: TextReader,
    find_template_fn: TemplateMatcher,
) -> tuple[Evidence, ...]:
    """Return star-bonus reward anchor evidence found in a frame."""

    okay_evidence = template_evidence(
        image,
        template_path=STAR_BONUS_OKAY_BUTTON_TEMPLATE,
        subject=BaseScreen.STAR_BONUS,
        anchor=ScreenElement.STAR_BONUS_OKAY_BUTTON,
        region=_OKAY_BUTTON_REGION,
        min_confidence=_STAR_BONUS_TEMPLATE_CONFIDENCE,
        find_template_fn=find_template_fn,
        scales=attack_flow_template_scales(image.size),
    )
    if okay_evidence is None:
        return ()

    title_evidence = _detect_star_bonus_title(image, read_text_fn=read_text_fn)
    if title_evidence is None:
        return ()
    return (title_evidence, okay_evidence)


def _detect_star_bonus_title(
    image: FrameImage,
    *,
    read_text_fn: TextReader,
) -> Evidence | None:
    text = read_text_fn(image, region=_STAR_BONUS_TITLE_REGION).strip()
    if not contains_phrase(text, "Star Bonus Received"):
        return None

    return Evidence(
        kind=EvidenceKind.OCR,
        subject=BaseScreen.STAR_BONUS,
        anchor=ScreenElement.STAR_BONUS_TITLE,
        confidence=_STAR_BONUS_OCR_CONFIDENCE,
        text=text,
        details={"region": _STAR_BONUS_TITLE_REGION, "phrase": "Star Bonus Received"},
    )


__all__ = ["detect_star_bonus"]
