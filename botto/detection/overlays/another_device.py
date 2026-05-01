"""Detection for the 'another device connected' blocking overlay."""

from __future__ import annotations

from android_game_automator.types import ScreenRect

from ..common import (
    OverlayDetection,
    blocking_overlay_result,
    contains_phrase,
    first_matching_phrase,
)
from ..models import Overlay


def detect_another_device(text: str, *, region: ScreenRect) -> OverlayDetection | None:
    """Detect the another-device popup from OCR text."""

    if not contains_phrase(text, "Another device"):
        return None

    connection_phrase = first_matching_phrase(text, ("connecting", "connect"))
    if connection_phrase is None:
        return None

    return blocking_overlay_result(
        Overlay.ANOTHER_DEVICE_CONNECTED,
        evidence_label="modal.another_device_connected",
        action_label="tap_reload",
        text=text,
        phrases=("Another device", connection_phrase),
        region=region,
    )


__all__ = ["detect_another_device"]
