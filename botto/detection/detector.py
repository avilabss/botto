"""Read-only Clash screen and overlay detector for Botto."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.ocr import read_text
from android_game_automator.vision import find_template

from .common import TemplateMatcher, TextReader
from .models import BaseScreen, Overlay, ScreenAnalysis
from .overlays import detect_overlay
from .screens import detect_base_screen


def analyze_screen(
    image: FrameImage,
    *,
    read_text_fn: TextReader = read_text,
    find_template_fn: TemplateMatcher = find_template,
) -> ScreenAnalysis:
    """Classify a Clash screenshot without performing any game input actions."""

    overlay, overlay_confidence, overlay_evidence, recommended_action = detect_overlay(
        image,
        read_text_fn=read_text_fn,
    )
    if overlay is not Overlay.NONE:
        return ScreenAnalysis(
            base_screen=BaseScreen.UNKNOWN,
            overlay=overlay,
            confidence=overlay_confidence,
            evidence=overlay_evidence,
            recommended_action=recommended_action,
        )

    base_screen, base_confidence, base_evidence = detect_base_screen(
        image,
        read_text_fn=read_text_fn,
        find_template_fn=find_template_fn,
    )

    return ScreenAnalysis(
        base_screen=base_screen,
        overlay=overlay,
        confidence=overlay_confidence if overlay is not Overlay.NONE else base_confidence,
        evidence=(*overlay_evidence, *base_evidence),
        recommended_action=recommended_action,
    )


__all__ = ["analyze_screen"]
