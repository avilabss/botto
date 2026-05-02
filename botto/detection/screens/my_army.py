"""My Army base-screen template anchors."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TemplateMatcher, template_evidence
from ..evidence import Evidence
from ..templates import (
    MY_ARMY_ATTACK_BUTTON_TEMPLATE,
    MY_ARMY_TITLE_TEMPLATE,
    attack_flow_template_scales,
)
from .models import BaseScreen, ScreenElement

_MY_ARMY_TITLE_REGION = NormalizedRect(left=0.10, top=0.03, width=0.30, height=0.12)
_ATTACK_BUTTON_REGION = NormalizedRect(left=0.74, top=0.80, width=0.20, height=0.17)
_MY_ARMY_TEMPLATE_CONFIDENCE = 0.82


def detect_my_army(
    image: FrameImage,
    *,
    find_template_fn: TemplateMatcher,
) -> tuple[Evidence, ...]:
    """Return My Army anchor evidence found in a frame."""

    scales = attack_flow_template_scales(image.size)
    return tuple(
        evidence
        for evidence in (
            template_evidence(
                image,
                template_path=MY_ARMY_TITLE_TEMPLATE,
                subject=BaseScreen.MY_ARMY,
                anchor=ScreenElement.MY_ARMY_TITLE,
                region=_MY_ARMY_TITLE_REGION,
                min_confidence=_MY_ARMY_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
            template_evidence(
                image,
                template_path=MY_ARMY_ATTACK_BUTTON_TEMPLATE,
                subject=BaseScreen.MY_ARMY,
                anchor=ScreenElement.MY_ARMY_ATTACK_BUTTON,
                region=_ATTACK_BUTTON_REGION,
                min_confidence=_MY_ARMY_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
        )
        if evidence is not None
    )


__all__ = ["detect_my_army"]
