"""Loading base-screen OCR detection."""

from __future__ import annotations

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect

from ..common import TextReader, contains_phrase
from ..evidence import Evidence, EvidenceKind
from .models import BaseScreen, ScreenElement

_LOADING_TEXT_REGION = NormalizedRect(left=0.28, top=0.70, width=0.44, height=0.20)
_LOADING_CONFIDENCE = 0.8


def detect_loading_screen(
    image: FrameImage,
    *,
    read_text_fn: TextReader,
) -> Evidence | None:
    """Detect the loading screen from OCR text."""

    loading_text = read_text_fn(image, region=_LOADING_TEXT_REGION).strip()
    if not contains_phrase(loading_text, "Loading"):
        return None

    return Evidence(
        kind=EvidenceKind.OCR,
        subject=BaseScreen.LOADING,
        anchor=ScreenElement.LOADING_TEXT,
        confidence=_LOADING_CONFIDENCE,
        text=loading_text,
        details={"region": _LOADING_TEXT_REGION, "phrase": "Loading"},
    )


__all__ = ["detect_loading_screen"]
