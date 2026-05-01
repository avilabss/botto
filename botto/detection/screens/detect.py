"""Known base-screen detection orchestration."""

from __future__ import annotations

from android_game_automator.image import FrameImage

from ..common import BaseScreenDetection, TemplateMatcher, TextReader
from .home import detect_home_village
from .loading import detect_loading_screen
from .models import BaseScreen
from .supercell import detect_supercell_logo


def detect_base_screen(
    image: FrameImage,
    *,
    read_text_fn: TextReader,
    find_template_fn: TemplateMatcher,
) -> BaseScreenDetection:
    """Detect base screens in the existing priority order."""

    supercell_evidence = detect_supercell_logo(image, find_template_fn=find_template_fn)
    if supercell_evidence is not None:
        return BaseScreen.SUPERCELL_LOGO, supercell_evidence.confidence, (supercell_evidence,)

    home_evidence = detect_home_village(image, find_template_fn=find_template_fn)
    if len(home_evidence) >= 2:
        confidence = sum(evidence.confidence for evidence in home_evidence) / len(home_evidence)
        return BaseScreen.HOME_VILLAGE, confidence, home_evidence

    loading_evidence = detect_loading_screen(image, read_text_fn=read_text_fn)
    if loading_evidence is not None:
        return BaseScreen.LOADING, loading_evidence.confidence, (loading_evidence,)

    return BaseScreen.UNKNOWN, 0.0, home_evidence


__all__ = ["detect_base_screen"]
