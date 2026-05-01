"""Known blocking overlay detection orchestration."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import OverlayResult, TextReader
from ..models import Overlay
from .another_device import detect_another_device
from .anyone_there import detect_anyone_there
from .connection_lost import detect_connection_lost

_MODAL_TEXT_REGION = NormalizedRect(left=0.22, top=0.58, width=0.56, height=0.39)


def detect_overlay(
    image: FrameImage,
    *,
    read_text_fn: TextReader,
) -> OverlayResult:
    """Detect current known overlays in the existing short-circuit order."""

    modal_text = read_text_fn(image, region=_MODAL_TEXT_REGION).strip()
    if not modal_text:
        return Overlay.NONE, 0.0, (), None

    another_device = detect_another_device(modal_text, region=_MODAL_TEXT_REGION)
    if another_device is not None:
        return another_device

    anyone_there = detect_anyone_there(modal_text, region=_MODAL_TEXT_REGION)
    if anyone_there is not None:
        return anyone_there

    connection_lost = detect_connection_lost(modal_text, region=_MODAL_TEXT_REGION)
    if connection_lost is not None:
        return connection_lost

    return Overlay.NONE, 0.0, (), None


__all__ = ["detect_overlay"]
