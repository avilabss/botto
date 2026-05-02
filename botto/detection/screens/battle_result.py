"""Battle-result base-screen template anchors."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TemplateMatcher, template_evidence
from ..evidence import Evidence
from ..templates import (
    BATTLE_END_CLAIM_REWARD_BUTTON_TEMPLATE,
    BATTLE_END_RETURN_HOME_BUTTON_TEMPLATE,
    attack_flow_template_scales,
)
from .models import BaseScreen, ScreenElement

_RETURN_HOME_BUTTON_REGION = NormalizedRect(left=0.42, top=0.78, width=0.17, height=0.15)
_CLAIM_REWARD_BUTTON_REGION = NormalizedRect(left=0.40, top=0.78, width=0.22, height=0.15)
_BATTLE_RESULT_TEMPLATE_CONFIDENCE = 0.82


def detect_battle_result(
    image: FrameImage,
    *,
    find_template_fn: TemplateMatcher,
) -> tuple[Evidence, ...]:
    """Return battle-result anchor evidence found in a frame."""

    scales = attack_flow_template_scales(image.size)
    return tuple(
        evidence
        for evidence in (
            template_evidence(
                image,
                template_path=BATTLE_END_RETURN_HOME_BUTTON_TEMPLATE,
                subject=BaseScreen.BATTLE_RESULT,
                anchor=ScreenElement.BATTLE_RETURN_HOME_BUTTON,
                region=_RETURN_HOME_BUTTON_REGION,
                min_confidence=_BATTLE_RESULT_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
            template_evidence(
                image,
                template_path=BATTLE_END_CLAIM_REWARD_BUTTON_TEMPLATE,
                subject=BaseScreen.BATTLE_RESULT,
                anchor=ScreenElement.BATTLE_CLAIM_REWARD_BUTTON,
                region=_CLAIM_REWARD_BUTTON_REGION,
                min_confidence=_BATTLE_RESULT_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
        )
        if evidence is not None
    )


__all__ = ["detect_battle_result"]
