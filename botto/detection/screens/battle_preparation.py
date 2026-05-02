"""Battle preparation/search base-screen template anchors."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TemplateMatcher, template_evidence
from ..evidence import Evidence
from ..templates import (
    BATTLE_PREPARATION_BATTLE_STARTS_IN_TEMPLATE,
    BATTLE_PREPARATION_NEXT_BUTTON_TEMPLATE,
    attack_flow_template_scales,
)
from .models import BaseScreen, ScreenElement

_BATTLE_STARTS_IN_REGION = NormalizedRect(left=0.42, top=0.00, width=0.20, height=0.14)
_NEXT_BUTTON_REGION = NormalizedRect(left=0.82, top=0.58, width=0.17, height=0.22)
_BATTLE_PREPARATION_TEMPLATE_CONFIDENCE = 0.82


def detect_battle_preparation(
    image: FrameImage,
    *,
    find_template_fn: TemplateMatcher,
) -> tuple[Evidence, ...]:
    """Return battle-preparation/search anchor evidence found in a frame."""

    scales = attack_flow_template_scales(image.size)
    return tuple(
        evidence
        for evidence in (
            template_evidence(
                image,
                template_path=BATTLE_PREPARATION_BATTLE_STARTS_IN_TEMPLATE,
                subject=BaseScreen.BATTLE_PREPARATION,
                anchor=ScreenElement.BATTLE_STARTS_IN_TEXT,
                region=_BATTLE_STARTS_IN_REGION,
                min_confidence=_BATTLE_PREPARATION_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
            template_evidence(
                image,
                template_path=BATTLE_PREPARATION_NEXT_BUTTON_TEMPLATE,
                subject=BaseScreen.BATTLE_PREPARATION,
                anchor=ScreenElement.BATTLE_NEXT_BUTTON,
                region=_NEXT_BUTTON_REGION,
                min_confidence=_BATTLE_PREPARATION_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
        )
        if evidence is not None
    )


__all__ = ["detect_battle_preparation"]
