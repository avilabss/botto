"""Tests for Botto's read-only Clash screen detector."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from os import PathLike
from pathlib import Path

from android_game_automator.image import FrameImage
from android_game_automator.types import Match, NormalizedPoint, PixelFormat, Rect, ScreenRect, Size
from botto.screen_detector import analyze_screen
from botto.screens import BaseScreen, Overlay, ScreenAnalysis


def test_analyze_screen_detects_loading_from_ocr() -> None:
    reader = FakeTextReader("", "Loading")
    matcher = FakeTemplateMatcher({})

    analysis = analyze_screen(
        _frame(),
        read_text_fn=reader,
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.LOADING
    assert analysis.overlay == Overlay.NONE
    assert analysis.recommended_action is None
    assert _evidence_labels(analysis) == {"loading_text"}
    assert [call[0] for call in matcher.calls] == [
        "supercell_logo.png",
        "attack_button.png",
        "shop_button.png",
    ]
    assert len(reader.calls) == 2


def test_analyze_screen_detects_supercell_logo_from_template() -> None:
    matcher = FakeTemplateMatcher({"supercell_logo.png": 0.95})

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader(""),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.SUPERCELL_LOGO
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.95
    assert _evidence_labels(analysis) == {"supercell_logo"}
    assert len(matcher.calls) == 1
    assert matcher.calls[0][0] == "supercell_logo.png"
    assert matcher.calls[0][3] == (1.0,)


def test_analyze_screen_detects_home_village_from_anchor_templates() -> None:
    reader = FakeTextReader("")
    matcher = FakeTemplateMatcher(
        {
            "attack_button.png": 0.91,
            "shop_button.png": 0.89,
        }
    )

    analysis = analyze_screen(
        _frame(),
        read_text_fn=reader,
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.HOME_VILLAGE
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.90
    assert _evidence_labels(analysis) == {"attack_button", "shop_button"}
    assert [call[0] for call in matcher.calls] == [
        "supercell_logo.png",
        "attack_button.png",
        "shop_button.png",
    ]
    assert len(reader.calls) == 1


def test_analyze_screen_passes_reference_scales_to_home_templates() -> None:
    matcher = FakeTemplateMatcher(
        {
            "attack_button.png": 0.91,
            "shop_button.png": 0.89,
        }
    )

    analyze_screen(
        _frame(width=1080, height=504),
        read_text_fn=FakeTextReader(""),
        find_template_fn=matcher,
    )

    scale_calls = _home_scale_calls(matcher)
    assert scale_calls == {
        "attack_button.png": (0.95, 1.0, 1.05),
        "shop_button.png": (0.95, 1.0, 1.05),
    }
    for scales in scale_calls.values():
        _assert_valid_scale_candidates(scales, expected_center=1.0)


def test_analyze_screen_passes_full_resolution_scales_to_home_templates() -> None:
    matcher = FakeTemplateMatcher({})
    expected_scale = ((3088 / 1080) + (1440 / 504)) / 2.0

    analyze_screen(
        _frame(width=3088, height=1440),
        read_text_fn=FakeTextReader("", ""),
        find_template_fn=matcher,
    )

    scale_calls = _home_scale_calls(matcher)
    assert set(scale_calls) == {"attack_button.png", "shop_button.png"}
    for scales in scale_calls.values():
        _assert_valid_scale_candidates(scales, expected_center=expected_scale)
        assert math.isclose(scales[1], expected_scale, rel_tol=1e-12)
        assert math.isclose(scales[1], 2.86, rel_tol=0.01)


def test_analyze_screen_detects_connection_lost_without_try_again_and_short_circuits() -> None:
    reader = FakeTextReader("Connection lost\nPlease check your internet connection.")
    matcher = FakeTemplateMatcher(
        {
            "attack_button.png": 0.91,
            "shop_button.png": 0.89,
        }
    )

    analysis = analyze_screen(
        _frame(),
        read_text_fn=reader,
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.UNKNOWN
    assert analysis.overlay == Overlay.CONNECTION_LOST
    assert analysis.recommended_action is not None
    assert analysis.recommended_action.label == "tap_try_again"
    assert analysis.recommended_action.tap_target == NormalizedPoint(x=0.50, y=0.88)
    assert _evidence_labels(analysis) == {"modal.connection_lost"}
    assert matcher.calls == []
    assert len(reader.calls) == 1


def test_analyze_screen_detects_another_device_before_generic_connection_lost() -> None:
    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader(
            "Connection lost\nAnother device is connecting to this village.",
        ),
        find_template_fn=FakeTemplateMatcher({}),
    )

    assert analysis.base_screen == BaseScreen.UNKNOWN
    assert analysis.overlay == Overlay.ANOTHER_DEVICE_CONNECTED
    assert analysis.recommended_action is not None
    assert analysis.recommended_action.label == "tap_reload"
    assert analysis.recommended_action.tap_target == NormalizedPoint(x=0.50, y=0.88)
    assert _evidence_labels(analysis) == {"modal.another_device_connected"}


def test_analyze_screen_detects_anyone_there_overlay() -> None:
    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader(
            "Anyone there?\nYou have been disconnected due to inactivity.",
        ),
        find_template_fn=FakeTemplateMatcher({}),
    )

    assert analysis.base_screen == BaseScreen.UNKNOWN
    assert analysis.overlay == Overlay.ANYONE_THERE
    assert analysis.recommended_action is not None
    assert analysis.recommended_action.label == "tap_reload_game"
    assert analysis.recommended_action.tap_target == NormalizedPoint(x=0.50, y=0.88)
    assert analysis.recommended_action.tap_target.y != 0.78
    assert _evidence_labels(analysis) == {"modal.anyone_there"}


def test_analyze_screen_returns_unknown_without_known_evidence() -> None:
    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader("", ""),
        find_template_fn=FakeTemplateMatcher({}),
    )

    assert analysis.base_screen == BaseScreen.UNKNOWN
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.0
    assert analysis.evidence == ()
    assert analysis.recommended_action is None


def _frame(*, width: int = 16, height: int = 16) -> FrameImage:
    return FrameImage(
        size=Size(width=width, height=height),
        pixel_format=PixelFormat.RGBA32,
        data=bytes((0, 0, 0, 255)) * (width * height),
    )


def _evidence_labels(analysis: ScreenAnalysis) -> set[str]:
    return {evidence.label for evidence in analysis.evidence}


def _home_scale_calls(matcher: FakeTemplateMatcher) -> dict[str, tuple[float, ...]]:
    return {
        template_name: scales
        for template_name, _region, _min_confidence, scales in matcher.calls
        if template_name in {"attack_button.png", "shop_button.png"}
    }


def _assert_valid_scale_candidates(scales: tuple[float, ...], *, expected_center: float) -> None:
    assert 1 <= len(scales) <= 3
    assert len(scales) == len(set(scales))
    assert all(math.isfinite(scale) and scale > 0.0 for scale in scales)
    assert any(math.isclose(scale, expected_center, rel_tol=1e-12) for scale in scales)


class FakeTextReader:
    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)
        self.calls: list[ScreenRect | None] = []

    def __call__(self, image: FrameImage, *, region: ScreenRect | None = None) -> str:
        self.calls.append(region)
        if not self._texts:
            return ""
        return self._texts.pop(0)


class FakeTemplateMatcher:
    def __init__(self, matches: Mapping[str, float]) -> None:
        self._matches = dict(matches)
        self.calls: list[tuple[str, ScreenRect | None, float, tuple[float, ...]]] = []

    def __call__(
        self,
        source: FrameImage,
        template: str | PathLike[str],
        *,
        region: ScreenRect | None = None,
        min_confidence: float = 0.9,
        scales: Iterable[float] = (1.0,),
    ) -> Match | None:
        template_name = Path(template).name
        resolved_scales = tuple(scales)
        self.calls.append((template_name, region, min_confidence, resolved_scales))
        confidence = self._matches.get(template_name)
        if confidence is None or confidence < min_confidence:
            return None
        return Match(
            bounds=Rect(left=1, top=2, width=3, height=4),
            confidence=confidence,
            scale=resolved_scales[0],
            rotation=0.0,
        )
