"""Supercell logo base-screen template anchor."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TemplateMatcher, template_evidence
from ..models import Evidence
from ..templates import SUPERCELL_LOGO_TEMPLATE

_SUPERCELL_LOGO_REGION = NormalizedRect(left=0.20, top=0.20, width=0.60, height=0.60)
_SUPERCELL_TEMPLATE_CONFIDENCE = 0.88


def detect_supercell_logo(
    image: FrameImage,
    *,
    find_template_fn: TemplateMatcher,
) -> Evidence | None:
    """Detect the Supercell logo screen from its logo template."""

    return template_evidence(
        image,
        template_path=SUPERCELL_LOGO_TEMPLATE,
        label="supercell_logo",
        region=_SUPERCELL_LOGO_REGION,
        min_confidence=_SUPERCELL_TEMPLATE_CONFIDENCE,
        find_template_fn=find_template_fn,
        template_detail_name="supercell_logo.png",
    )


__all__ = ["detect_supercell_logo"]
