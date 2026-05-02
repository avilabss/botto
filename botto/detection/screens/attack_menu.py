"""Attack-menu base-screen template anchors."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TemplateMatcher, template_evidence
from ..evidence import Evidence
from ..templates import (
    ATTACK_MENU_FIND_A_MATCH_BUTTON_TEMPLATE,
    ATTACK_MENU_MULTIPLAYER_TITLE_TEMPLATE,
    attack_flow_template_scales,
)
from .models import BaseScreen, ScreenElement

_MULTIPLAYER_TITLE_REGION = NormalizedRect(left=0.04, top=0.02, width=0.18, height=0.12)
_FIND_A_MATCH_BUTTON_REGION = NormalizedRect(left=0.06, top=0.62, width=0.22, height=0.20)
_ATTACK_MENU_TEMPLATE_CONFIDENCE = 0.82


def detect_attack_menu(
    image: FrameImage,
    *,
    find_template_fn: TemplateMatcher,
) -> tuple[Evidence, ...]:
    """Return attack-menu anchor evidence found in a frame."""

    scales = attack_flow_template_scales(image.size)
    return tuple(
        evidence
        for evidence in (
            template_evidence(
                image,
                template_path=ATTACK_MENU_MULTIPLAYER_TITLE_TEMPLATE,
                subject=BaseScreen.ATTACK_MENU,
                anchor=ScreenElement.ATTACK_MENU_MULTIPLAYER_TITLE,
                region=_MULTIPLAYER_TITLE_REGION,
                min_confidence=_ATTACK_MENU_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
            template_evidence(
                image,
                template_path=ATTACK_MENU_FIND_A_MATCH_BUTTON_TEMPLATE,
                subject=BaseScreen.ATTACK_MENU,
                anchor=ScreenElement.ATTACK_MENU_FIND_A_MATCH_BUTTON,
                region=_FIND_A_MATCH_BUTTON_REGION,
                min_confidence=_ATTACK_MENU_TEMPLATE_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=scales,
            ),
        )
        if evidence is not None
    )


__all__ = ["detect_attack_menu"]
