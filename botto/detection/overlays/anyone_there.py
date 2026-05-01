"""Detection for the 'anyone there' inactivity blocking overlay."""

from __future__ import annotations

from android_game_automator.types import ScreenRect

from ..common import OverlayDetection, blocking_overlay_result, matching_phrases
from ..models import Overlay


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
        evidence_label="modal.anyone_there",
        action_label="tap_reload_game",
        text=text,
        phrases=phrases,
        region=region,
    )


__all__ = ["detect_anyone_there"]
