"""Reward-chest base-screen template anchors."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TemplateMatcher, template_evidence
from ..evidence import Evidence
from ..templates import (
    REWARD_CHEST_CLOSED_CHEST_TEMPLATE,
    REWARD_CHEST_CONTINUE_BUTTON_TEMPLATE,
    attack_flow_template_scales,
)
from .models import BaseScreen, ScreenElement

_OPEN_CHEST_REGION = NormalizedRect(left=0.40, top=0.37, width=0.22, height=0.30)
_CONTINUE_BUTTON_REGION = NormalizedRect(left=0.42, top=0.78, width=0.17, height=0.15)
_OPEN_CHEST_TEMPLATE_CONFIDENCE = 0.88
_REWARD_CHEST_TEMPLATE_CONFIDENCE = 0.82


def detect_reward_chest(
    image: FrameImage,
    *,
    find_template_fn: TemplateMatcher,
) -> tuple[Evidence, ...]:
    """Return reward-chest anchor evidence found in a frame."""

    scales = attack_flow_template_scales(image.size)
    return tuple(
        evidence
        for evidence in (
            template_evidence(
                image,
                template_path=REWARD_CHEST_CLOSED_CHEST_TEMPLATE,
                subject=BaseScreen.REWARD_CHEST,
                anchor=ScreenElement.REWARD_CHEST_OPEN_CHEST,
                region=_OPEN_CHEST_REGION,
                min_confidence=_OPEN_CHEST_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
            template_evidence(
                image,
                template_path=REWARD_CHEST_CONTINUE_BUTTON_TEMPLATE,
                subject=BaseScreen.REWARD_CHEST,
                anchor=ScreenElement.REWARD_CHEST_CONTINUE_BUTTON,
                region=_CONTINUE_BUTTON_REGION,
                min_confidence=_REWARD_CHEST_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
        )
        if evidence is not None
    )


__all__ = ["detect_reward_chest"]
