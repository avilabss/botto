"""Detection for the connection-lost blocking overlay."""

from __future__ import annotations

from android_game_automator.types import ScreenRect

from ..common import OverlayDetection, blocking_overlay_result, matching_phrases
from ..models import Overlay


def detect_connection_lost(text: str, *, region: ScreenRect) -> OverlayDetection | None:
    """Detect the connection-lost popup from OCR text."""

    phrases = matching_phrases(
        text,
        (
            "Connection lost",
            "lost connection with the server",
            "internet connection",
        ),
    )
    if phrases is None:
        return None

    return blocking_overlay_result(
        Overlay.CONNECTION_LOST,
        evidence_label="modal.connection_lost",
        action_label="tap_try_again",
        text=text,
        phrases=phrases,
        region=region,
    )


__all__ = ["detect_connection_lost"]
