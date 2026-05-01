"""Detection for the 'anyone there' inactivity blocking overlay."""

from __future__ import annotations

from android_game_automator.types import ScreenRect

from ..common import OverlayDetection, blocking_overlay_result, matching_phrases
from .models import Overlay, PopupButton


def detect_anyone_there(text: str, *, region: ScreenRect) -> OverlayDetection | None:
    """Detect the inactivity popup from OCR text."""

    phrases = matching_phrases(
        text,
        (
            "Anyone there",
            "disconnected due to inactivity",
        ),
    )
    if phrases is None:
        return None

    return blocking_overlay_result(
        Overlay.ANYONE_THERE,
        target=PopupButton.RELOAD_GAME,
        text=text,
        phrases=phrases,
        region=region,
    )


__all__ = ["detect_anyone_there"]
