"""Battle-surrender confirmation popup template anchors."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TemplateMatcher, template_evidence
from ..evidence import Evidence
from ..templates import BATTLE_SURRENDER_OKAY_BUTTON_TEMPLATE, attack_flow_template_scales
from .models import BaseScreen, ScreenElement

_OKAY_BUTTON_REGION = NormalizedRect(left=0.34, top=0.50, width=0.32, height=0.26)
_SURRENDER_CONFIRMATION_TEMPLATE_CONFIDENCE = 0.82


def detect_battle_surrender_confirmation(
    image: FrameImage,
    *,
    find_template_fn: TemplateMatcher,
) -> tuple[Evidence, ...]:
    """Return surrender-confirmation popup anchor evidence found in a frame."""

    evidence = template_evidence(
        image,
        template_path=BATTLE_SURRENDER_OKAY_BUTTON_TEMPLATE,
        subject=BaseScreen.BATTLE_SURRENDER_CONFIRMATION,
        anchor=ScreenElement.BATTLE_SURRENDER_OKAY_BUTTON,
        region=_OKAY_BUTTON_REGION,
        min_confidence=_SURRENDER_CONFIRMATION_TEMPLATE_CONFIDENCE,
        find_template_fn=find_template_fn,
        scales=attack_flow_template_scales(image.size),
    )
    if evidence is None:
        return ()
    return (evidence,)


__all__ = ["detect_battle_surrender_confirmation"]
