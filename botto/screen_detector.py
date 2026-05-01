"""Read-only Clash screen and overlay detector for Botto."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from os import PathLike
from pathlib import Path
from typing import Protocol

from android_game_automator.image import FrameImage
from android_game_automator.ocr import read_text
from android_game_automator.types import Match, NormalizedPoint, NormalizedRect, ScreenRect, Size
from android_game_automator.vision import find_template

from botto.screens import BaseScreen, Evidence, Overlay, RecommendedAction, ScreenAnalysis


class TextReader(Protocol):
    """Callable shape used for OCR so tests can inject fakes."""

    def __call__(self, image: FrameImage, *, region: ScreenRect | None = None) -> str: ...


class TemplateMatcher(Protocol):
    """Callable shape used for template matching so tests can inject fakes."""

    def __call__(
        self,
        source: FrameImage,
        template: str | PathLike[str],
        *,
        region: ScreenRect | None = None,
        min_confidence: float = 0.9,
        scales: Iterable[float] = (1.0,),
    ) -> Match | None: ...


_TEMPLATE_DIR = Path(__file__).resolve().parent / "assets" / "templates"
_SUPERCELL_LOGO_TEMPLATE = _TEMPLATE_DIR / "supercell_logo.png"
_ATTACK_BUTTON_TEMPLATE = _TEMPLATE_DIR / "attack_button.png"
_SHOP_BUTTON_TEMPLATE = _TEMPLATE_DIR / "shop_button.png"

_MODAL_TEXT_REGION = NormalizedRect(left=0.22, top=0.58, width=0.56, height=0.39)
_LOADING_TEXT_REGION = NormalizedRect(left=0.28, top=0.70, width=0.44, height=0.20)
_SUPERCELL_LOGO_REGION = NormalizedRect(left=0.20, top=0.20, width=0.60, height=0.60)
_ATTACK_BUTTON_REGION = NormalizedRect(left=0.00, top=0.74, width=0.25, height=0.26)
_SHOP_BUTTON_REGION = NormalizedRect(left=0.80, top=0.72, width=0.20, height=0.28)

_HOME_TEMPLATE_REFERENCE_SIZE = Size(width=1080, height=504)
_HOME_TEMPLATE_SCALE_MULTIPLIERS = (0.95, 1.0, 1.05)

_BLOCKING_POPUP_BUTTON_TAP_TARGET = NormalizedPoint(x=0.50, y=0.88)
_OCR_CONFIDENCE = 0.9
_LOADING_CONFIDENCE = 0.8
_SUPERCELL_TEMPLATE_CONFIDENCE = 0.88
_HOME_ANCHOR_CONFIDENCE = 0.82


def analyze_screen(
    image: FrameImage,
    *,
    read_text_fn: TextReader = read_text,
    find_template_fn: TemplateMatcher = find_template,
) -> ScreenAnalysis:
    """Classify a Clash screenshot without performing any game input actions."""

    overlay, overlay_confidence, overlay_evidence, recommended_action = _detect_overlay(
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

    base_screen, base_confidence, base_evidence = _detect_base_screen(
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


def _detect_overlay(
    image: FrameImage,
    *,
    read_text_fn: TextReader,
) -> tuple[Overlay, float, tuple[Evidence, ...], RecommendedAction | None]:
    modal_text = read_text_fn(image, region=_MODAL_TEXT_REGION).strip()
    if not modal_text:
        return Overlay.NONE, 0.0, (), None

    another_device_phrases = _another_device_popup_phrases(modal_text)
    if another_device_phrases is not None:
        return _blocking_overlay_result(
            Overlay.ANOTHER_DEVICE_CONNECTED,
            evidence_label="modal.another_device_connected",
            action_label="tap_reload",
            text=modal_text,
            phrases=another_device_phrases,
        )

    anyone_there_phrases = _anyone_there_popup_phrases(modal_text)
    if anyone_there_phrases is not None:
        return _blocking_overlay_result(
            Overlay.ANYONE_THERE,
            evidence_label="modal.anyone_there",
            action_label="tap_reload_game",
            text=modal_text,
            phrases=anyone_there_phrases,
        )

    connection_lost_phrases = _connection_lost_popup_phrases(modal_text)
    if connection_lost_phrases is not None:
        return _blocking_overlay_result(
            Overlay.CONNECTION_LOST,
            evidence_label="modal.connection_lost",
            action_label="tap_try_again",
            text=modal_text,
            phrases=connection_lost_phrases,
        )

    return Overlay.NONE, 0.0, (), None


def _detect_base_screen(
    image: FrameImage,
    *,
    read_text_fn: TextReader,
    find_template_fn: TemplateMatcher,
) -> tuple[BaseScreen, float, tuple[Evidence, ...]]:
    supercell_evidence = _template_evidence(
        image,
        template_path=_SUPERCELL_LOGO_TEMPLATE,
        label="supercell_logo",
        region=_SUPERCELL_LOGO_REGION,
        min_confidence=_SUPERCELL_TEMPLATE_CONFIDENCE,
        find_template_fn=find_template_fn,
    )
    if supercell_evidence is not None:
        return BaseScreen.SUPERCELL_LOGO, supercell_evidence.confidence, (supercell_evidence,)

    home_scales = _home_template_scales(image.size)
    home_evidence = tuple(
        evidence
        for evidence in (
            _template_evidence(
                image,
                template_path=_ATTACK_BUTTON_TEMPLATE,
                label="attack_button",
                region=_ATTACK_BUTTON_REGION,
                min_confidence=_HOME_ANCHOR_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=home_scales,
            ),
            _template_evidence(
                image,
                template_path=_SHOP_BUTTON_TEMPLATE,
                label="shop_button",
                region=_SHOP_BUTTON_REGION,
                min_confidence=_HOME_ANCHOR_CONFIDENCE,
                find_template_fn=find_template_fn,
                scales=home_scales,
            ),
        )
        if evidence is not None
    )
    if len(home_evidence) >= 2:
        confidence = sum(evidence.confidence for evidence in home_evidence) / len(home_evidence)
        return BaseScreen.HOME_VILLAGE, confidence, home_evidence

    loading_text = read_text_fn(image, region=_LOADING_TEXT_REGION).strip()
    if _contains_phrase(loading_text, "Loading"):
        return (
            BaseScreen.LOADING,
            _LOADING_CONFIDENCE,
            (
                Evidence(
                    kind="ocr",
                    label="loading_text",
                    confidence=_LOADING_CONFIDENCE,
                    text=loading_text,
                    details={"region": _LOADING_TEXT_REGION, "phrase": "Loading"},
                ),
            ),
        )

    return BaseScreen.UNKNOWN, 0.0, home_evidence


def _blocking_overlay_result(
    overlay: Overlay,
    *,
    evidence_label: str,
    action_label: str,
    text: str,
    phrases: tuple[str, ...],
) -> tuple[Overlay, float, tuple[Evidence, ...], RecommendedAction]:
    evidence = Evidence(
        kind="ocr",
        label=evidence_label,
        confidence=_OCR_CONFIDENCE,
        text=text,
        details={"region": _MODAL_TEXT_REGION, "phrases": phrases},
    )
    action = RecommendedAction(
        label=action_label,
        tap_target=_BLOCKING_POPUP_BUTTON_TAP_TARGET,
        details={"overlay": overlay.value},
    )
    return overlay, _OCR_CONFIDENCE, (evidence,), action


def _template_evidence(
    image: FrameImage,
    *,
    template_path: Path,
    label: str,
    region: ScreenRect,
    min_confidence: float,
    find_template_fn: TemplateMatcher,
    scales: Iterable[float] | None = None,
) -> Evidence | None:
    if scales is None:
        match = find_template_fn(
            image,
            template_path,
            region=region,
            min_confidence=min_confidence,
        )
    else:
        match = find_template_fn(
            image,
            template_path,
            region=region,
            min_confidence=min_confidence,
            scales=scales,
        )
    if match is None:
        return None

    return Evidence(
        kind="template",
        label=label,
        confidence=match.confidence,
        details={
            "bounds": match.bounds,
            "region": region,
            "template": template_path.name,
        },
    )


def _home_template_scales(frame_size: Size) -> tuple[float, ...]:
    width_scale = frame_size.width / _HOME_TEMPLATE_REFERENCE_SIZE.width
    height_scale = frame_size.height / _HOME_TEMPLATE_REFERENCE_SIZE.height
    expected_scale = (width_scale + height_scale) / 2.0

    scales: list[float] = []
    seen: set[float] = set()
    for multiplier in _HOME_TEMPLATE_SCALE_MULTIPLIERS:
        scale = expected_scale * multiplier
        if not math.isfinite(scale) or scale <= 0.0 or scale in seen:
            continue
        seen.add(scale)
        scales.append(scale)

    return tuple(scales)


def _anyone_there_popup_phrases(text: str) -> tuple[str, ...] | None:
    return _matching_phrases(
        text,
        (
            "Anyone there",
            "disconnected due to inactivity",
        ),
    )


def _another_device_popup_phrases(text: str) -> tuple[str, ...] | None:
    if not _contains_phrase(text, "Another device"):
        return None

    connection_phrase = _first_matching_phrase(text, ("connecting", "connect"))
    if connection_phrase is None:
        return None

    return ("Another device", connection_phrase)


def _connection_lost_popup_phrases(text: str) -> tuple[str, ...] | None:
    return _matching_phrases(
        text,
        (
            "Connection lost",
            "lost connection with the server",
            "internet connection",
        ),
    )


def _matching_phrases(text: str, phrases: Iterable[str]) -> tuple[str, ...] | None:
    matches = tuple(phrase for phrase in phrases if _contains_phrase(text, phrase))
    if not matches:
        return None
    return matches


def _first_matching_phrase(text: str, phrases: Iterable[str]) -> str | None:
    for phrase in phrases:
        if _contains_phrase(text, phrase):
            return phrase
    return None


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return False
    return _normalize_text(phrase) in normalized_text


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


__all__ = ["analyze_screen"]
