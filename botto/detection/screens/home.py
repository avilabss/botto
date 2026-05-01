"""Home-village base-screen template anchors."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TemplateMatcher, template_evidence
from ..evidence import Evidence
from ..templates import ATTACK_BUTTON_TEMPLATE, SHOP_BUTTON_TEMPLATE, home_template_scales
from .models import BaseScreen, HomeElement

_ATTACK_BUTTON_REGION = NormalizedRect(left=0.00, top=0.74, width=0.25, height=0.26)
_SHOP_BUTTON_REGION = NormalizedRect(left=0.80, top=0.72, width=0.20, height=0.28)
_HOME_ANCHOR_CONFIDENCE = 0.82


def detect_home_village(
    image: FrameImage,
    *,
    find_template_fn: TemplateMatcher,
) -> tuple[Evidence, ...]:
    """Return home-village anchor evidence found in a frame."""

    home_scales = home_template_scales(image.size)
    return tuple(
        evidence
        for evidence in (
            template_evidence(
                image,
                template_path=ATTACK_BUTTON_TEMPLATE,
                subject=BaseScreen.HOME_VILLAGE,
                anchor=HomeElement.ATTACK_BUTTON,
                region=_ATTACK_BUTTON_REGION,
                min_confidence=_HOME_ANCHOR_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=home_scales,
            ),
            template_evidence(
                image,
                template_path=SHOP_BUTTON_TEMPLATE,
                subject=BaseScreen.HOME_VILLAGE,
                anchor=HomeElement.SHOP_BUTTON,
                region=_SHOP_BUTTON_REGION,
                min_confidence=_HOME_ANCHOR_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=home_scales,
            ),
        )
        if evidence is not None
    )


__all__ = ["detect_home_village"]
