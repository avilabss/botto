"""Active battle base-screen template and OCR anchors."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TemplateMatcher, TextReader, contains_phrase, template_evidence
from ..evidence import Evidence, EvidenceKind
from ..templates import (
    BATTLE_ACTIVE_END_BATTLE_BUTTON_TEMPLATE,
    BATTLE_ACTIVE_OVERALL_DAMAGE_TEMPLATE,
    BATTLE_ACTIVE_SURRENDER_BUTTON_TEMPLATE,
    attack_flow_template_scales,
)
from .models import BaseScreen, ScreenElement

_BATTLE_END_BATTLE_BUTTON_REGION = NormalizedRect(left=0.03, top=0.69, width=0.12, height=0.12)
_BATTLE_SURRENDER_BUTTON_REGION = NormalizedRect(left=0.03, top=0.69, width=0.12, height=0.12)
_OVERALL_DAMAGE_REGION = NormalizedRect(left=0.84, top=0.66, width=0.15, height=0.15)
_BATTLE_ENDS_IN_REGION = NormalizedRect(left=0.42, top=0.00, width=0.20, height=0.14)
_BATTLE_ACTIVE_TEMPLATE_CONFIDENCE = 0.82
_BATTLE_ENDS_IN_OCR_CONFIDENCE = 0.8
_ACTIVE_GATE_ANCHORS = {
    ScreenElement.BATTLE_ENDS_IN_TEXT,
    ScreenElement.BATTLE_OVERALL_DAMAGE,
    ScreenElement.BATTLE_SURRENDER_BUTTON,
}


def detect_battle_in_progress(
    image: FrameImage,
    *,
    read_text_fn: TextReader,
    find_template_fn: TemplateMatcher,
) -> tuple[Evidence, ...]:
    """Return active-battle anchor evidence found in a frame."""

    scales = attack_flow_template_scales(image.size)
    evidence_items = [
        evidence
        for evidence in (
            template_evidence(
                image,
                template_path=BATTLE_ACTIVE_END_BATTLE_BUTTON_TEMPLATE,
                subject=BaseScreen.BATTLE_IN_PROGRESS,
                anchor=ScreenElement.BATTLE_END_BATTLE_BUTTON,
                region=_BATTLE_END_BATTLE_BUTTON_REGION,
                min_confidence=_BATTLE_ACTIVE_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
            template_evidence(
                image,
                template_path=BATTLE_ACTIVE_SURRENDER_BUTTON_TEMPLATE,
                subject=BaseScreen.BATTLE_IN_PROGRESS,
                anchor=ScreenElement.BATTLE_SURRENDER_BUTTON,
                region=_BATTLE_SURRENDER_BUTTON_REGION,
                min_confidence=_BATTLE_ACTIVE_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
            template_evidence(
                image,
                template_path=BATTLE_ACTIVE_OVERALL_DAMAGE_TEMPLATE,
                subject=BaseScreen.BATTLE_IN_PROGRESS,
                anchor=ScreenElement.BATTLE_OVERALL_DAMAGE,
                region=_OVERALL_DAMAGE_REGION,
                min_confidence=_BATTLE_ACTIVE_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
        )
        if evidence is not None
    ]

    if not _has_active_gate(evidence_items):
        battle_ends_evidence = _detect_battle_ends_in_text(image, read_text_fn=read_text_fn)
        if battle_ends_evidence is not None:
            evidence_items.append(battle_ends_evidence)

    if not _has_active_gate(evidence_items):
        return ()
    return tuple(evidence_items)


def _has_active_gate(evidence_items: list[Evidence]) -> bool:
    return any(evidence.anchor in _ACTIVE_GATE_ANCHORS for evidence in evidence_items)


def _detect_battle_ends_in_text(
    image: FrameImage,
    *,
    read_text_fn: TextReader,
) -> Evidence | None:
    text = read_text_fn(image, region=_BATTLE_ENDS_IN_REGION).strip()
    if not contains_phrase(text, "Battle ends in"):
        return None

    return Evidence(
        kind=EvidenceKind.OCR,
        subject=BaseScreen.BATTLE_IN_PROGRESS,
        anchor=ScreenElement.BATTLE_ENDS_IN_TEXT,
        confidence=_BATTLE_ENDS_IN_OCR_CONFIDENCE,
        text=text,
        details={"region": _BATTLE_ENDS_IN_REGION, "phrase": "Battle ends in"},
    )


__all__ = ["detect_battle_in_progress"]
