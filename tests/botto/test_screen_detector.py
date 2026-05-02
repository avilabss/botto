"""Tests for Botto's read-only Clash screen detector."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from os import PathLike
from pathlib import Path

from android_game_automator.image import FrameImage
from android_game_automator.types import Match, Rect, ScreenRect
from botto.detection import (
    ActionKind,
    BaseScreen,
    EvidenceKind,
    HomeElement,
    Overlay,
    PopupButton,
    ScreenAnalysis,
    ScreenElement,
)
from botto.detection.detector import analyze_screen
from botto.detection.templates import TEMPLATE_DIR

from tests.botto.fakes import make_frame

_SUPERCELL_LOGO_TEMPLATE = "screens/supercell/logo.png"
_ATTACK_BUTTON_TEMPLATE = "screens/home/attack_button.png"
_SHOP_BUTTON_TEMPLATE = "screens/home/shop_button.png"
_ATTACK_MENU_MULTIPLAYER_TITLE_TEMPLATE = "screens/attack_menu/multiplayer_title.png"
_ATTACK_MENU_FIND_A_MATCH_BUTTON_TEMPLATE = "screens/attack_menu/find_a_match_button.png"
_MY_ARMY_TITLE_TEMPLATE = "screens/my_army/title.png"
_MY_ARMY_ATTACK_BUTTON_TEMPLATE = "screens/my_army/attack_button.png"
_BATTLE_PREPARATION_BATTLE_STARTS_IN_TEMPLATE = "screens/battle/preparation/battle_starts_in.png"
_BATTLE_PREPARATION_NEXT_BUTTON_TEMPLATE = "screens/battle/preparation/next_button.png"
_BATTLE_ACTIVE_END_BATTLE_BUTTON_TEMPLATE = "screens/battle/active/end_battle_button.png"
_BATTLE_ACTIVE_SURRENDER_BUTTON_TEMPLATE = "screens/battle/active/surrender_button.png"
_BATTLE_ACTIVE_OVERALL_DAMAGE_TEMPLATE = "screens/battle/active/overall_damage.png"
_BATTLE_END_RETURN_HOME_BUTTON_TEMPLATE = "screens/battle/end/return_home_button.png"
_BATTLE_END_CLAIM_REWARD_BUTTON_TEMPLATE = "screens/battle/end/claim_reward_button.png"
_BATTLE_SURRENDER_OKAY_BUTTON_TEMPLATE = "screens/battle/surrender/okay_button.png"
_REWARD_CHEST_CLOSED_CHEST_TEMPLATE = "screens/rewards/chest/closed_chest.png"
_REWARD_CHEST_CONTINUE_BUTTON_TEMPLATE = "screens/rewards/chest/continue_button.png"
_STAR_BONUS_OKAY_BUTTON_TEMPLATE = "screens/rewards/star_bonus/okay_button.png"
_PRE_HOME_TEMPLATE_PROBES = [
    _SUPERCELL_LOGO_TEMPLATE,
    _STAR_BONUS_OKAY_BUTTON_TEMPLATE,
    _MY_ARMY_TITLE_TEMPLATE,
    _MY_ARMY_ATTACK_BUTTON_TEMPLATE,
    _ATTACK_MENU_MULTIPLAYER_TITLE_TEMPLATE,
    _ATTACK_MENU_FIND_A_MATCH_BUTTON_TEMPLATE,
]


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
    assert analysis.evidence[0].kind is EvidenceKind.OCR
    assert analysis.evidence[0].subject is BaseScreen.LOADING
    assert analysis.evidence[0].anchor is ScreenElement.LOADING_TEXT
    assert [call[0] for call in matcher.calls] == [*_PRE_HOME_TEMPLATE_PROBES, *_home_templates()]
    assert len(reader.calls) == 2


def test_analyze_screen_detects_supercell_logo_from_template() -> None:
    matcher = FakeTemplateMatcher({_SUPERCELL_LOGO_TEMPLATE: 0.95})

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader(""),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.SUPERCELL_LOGO
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.95
    assert _evidence_labels(analysis) == {"supercell_logo"}
    assert analysis.evidence[0].kind is EvidenceKind.TEMPLATE
    assert analysis.evidence[0].subject is BaseScreen.SUPERCELL_LOGO
    assert analysis.evidence[0].anchor is ScreenElement.SUPERCELL_LOGO
    assert analysis.evidence[0].details["template"] == "supercell_logo.png"
    assert len(matcher.calls) == 1
    assert matcher.calls[0][0] == _SUPERCELL_LOGO_TEMPLATE
    assert matcher.calls[0][3] == (1.0,)


def test_analyze_screen_detects_home_village_from_anchor_templates() -> None:
    reader = FakeTextReader("")
    matcher = FakeTemplateMatcher(
        {
            _ATTACK_BUTTON_TEMPLATE: 0.91,
            _SHOP_BUTTON_TEMPLATE: 0.89,
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
    assert {evidence.kind for evidence in analysis.evidence} == {EvidenceKind.TEMPLATE}
    assert {evidence.subject for evidence in analysis.evidence} == {BaseScreen.HOME_VILLAGE}
    assert {evidence.anchor for evidence in analysis.evidence} == {
        HomeElement.ATTACK_BUTTON,
        HomeElement.SHOP_BUTTON,
    }
    assert [call[0] for call in matcher.calls] == [*_PRE_HOME_TEMPLATE_PROBES, *_home_templates()]
    assert len(reader.calls) == 1


def test_analyze_screen_detects_attack_menu_from_anchor_templates() -> None:
    matcher = FakeTemplateMatcher(
        {
            _ATTACK_MENU_MULTIPLAYER_TITLE_TEMPLATE: 0.93,
            _ATTACK_MENU_FIND_A_MATCH_BUTTON_TEMPLATE: 0.91,
        }
    )

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader(""),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.ATTACK_MENU
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.92
    assert _evidence_labels(analysis) == {
        "attack_menu_multiplayer_title",
        "attack_menu_find_a_match_button",
    }
    assert {evidence.subject for evidence in analysis.evidence} == {BaseScreen.ATTACK_MENU}
    assert {evidence.anchor for evidence in analysis.evidence} == {
        ScreenElement.ATTACK_MENU_MULTIPLAYER_TITLE,
        ScreenElement.ATTACK_MENU_FIND_A_MATCH_BUTTON,
    }


def test_analyze_screen_detects_my_army_from_anchor_templates() -> None:
    matcher = FakeTemplateMatcher(
        {
            _MY_ARMY_TITLE_TEMPLATE: 0.91,
            _MY_ARMY_ATTACK_BUTTON_TEMPLATE: 0.89,
        }
    )

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader(""),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.MY_ARMY
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.90
    assert _evidence_labels(analysis) == {"my_army_title", "my_army_attack_button"}
    assert {evidence.subject for evidence in analysis.evidence} == {BaseScreen.MY_ARMY}
    assert {evidence.anchor for evidence in analysis.evidence} == {
        ScreenElement.MY_ARMY_TITLE,
        ScreenElement.MY_ARMY_ATTACK_BUTTON,
    }


def test_analyze_screen_detects_battle_preparation_before_active_battle() -> None:
    matcher = FakeTemplateMatcher(
        {
            _BATTLE_PREPARATION_BATTLE_STARTS_IN_TEMPLATE: 0.91,
            _BATTLE_PREPARATION_NEXT_BUTTON_TEMPLATE: 0.89,
            _BATTLE_ACTIVE_OVERALL_DAMAGE_TEMPLATE: 0.93,
        }
    )

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader("", ""),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.BATTLE_PREPARATION
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.90
    assert _evidence_labels(analysis) == {"battle_starts_in_text", "battle_next_button"}
    assert {evidence.subject for evidence in analysis.evidence} == {BaseScreen.BATTLE_PREPARATION}
    assert {evidence.anchor for evidence in analysis.evidence} == {
        ScreenElement.BATTLE_STARTS_IN_TEXT,
        ScreenElement.BATTLE_NEXT_BUTTON,
    }
    assert _BATTLE_ACTIVE_OVERALL_DAMAGE_TEMPLATE not in [call[0] for call in matcher.calls]


def test_analyze_screen_detects_active_battle_from_damage_and_button_templates() -> None:
    matcher = FakeTemplateMatcher(
        {
            _BATTLE_ACTIVE_END_BATTLE_BUTTON_TEMPLATE: 0.91,
            _BATTLE_ACTIVE_SURRENDER_BUTTON_TEMPLATE: 0.90,
            _BATTLE_ACTIVE_OVERALL_DAMAGE_TEMPLATE: 0.89,
        }
    )

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader("", ""),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.BATTLE_IN_PROGRESS
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.90
    assert _evidence_labels(analysis) == {
        "battle_end_battle_button",
        "battle_surrender_button",
        "battle_overall_damage",
    }
    assert {evidence.subject for evidence in analysis.evidence} == {BaseScreen.BATTLE_IN_PROGRESS}
    assert {evidence.anchor for evidence in analysis.evidence} == {
        ScreenElement.BATTLE_END_BATTLE_BUTTON,
        ScreenElement.BATTLE_SURRENDER_BUTTON,
        ScreenElement.BATTLE_OVERALL_DAMAGE,
    }


def test_analyze_screen_detects_active_battle_from_battle_ends_ocr() -> None:
    matcher = FakeTemplateMatcher({_BATTLE_ACTIVE_END_BATTLE_BUTTON_TEMPLATE: 0.91})

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader("", "", "Battle ends in: 2M 57S"),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.BATTLE_IN_PROGRESS
    assert analysis.overlay == Overlay.NONE
    assert _evidence_labels(analysis) == {
        "battle_end_battle_button",
        "battle_ends_in_text",
    }
    assert analysis.evidence[-1].kind is EvidenceKind.OCR
    assert analysis.evidence[-1].anchor is ScreenElement.BATTLE_ENDS_IN_TEXT


def test_analyze_screen_detects_battle_surrender_confirmation_from_okay_template() -> None:
    matcher = FakeTemplateMatcher({_BATTLE_SURRENDER_OKAY_BUTTON_TEMPLATE: 0.91})

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader("", ""),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.BATTLE_SURRENDER_CONFIRMATION
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.91
    assert _evidence_labels(analysis) == {"battle_surrender_okay_button"}
    assert analysis.evidence[0].kind is EvidenceKind.TEMPLATE
    assert analysis.evidence[0].subject is BaseScreen.BATTLE_SURRENDER_CONFIRMATION
    assert analysis.evidence[0].anchor is ScreenElement.BATTLE_SURRENDER_OKAY_BUTTON


def test_analyze_screen_detects_battle_result_from_claim_reward_template() -> None:
    matcher = FakeTemplateMatcher({_BATTLE_END_CLAIM_REWARD_BUTTON_TEMPLATE: 0.93})

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader("", ""),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.BATTLE_RESULT
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.93
    assert _evidence_labels(analysis) == {"battle_claim_reward_button"}
    assert analysis.evidence[0].kind is EvidenceKind.TEMPLATE
    assert analysis.evidence[0].subject is BaseScreen.BATTLE_RESULT
    assert analysis.evidence[0].anchor is ScreenElement.BATTLE_CLAIM_REWARD_BUTTON


def test_analyze_screen_detects_reward_chest_from_continue_template() -> None:
    matcher = FakeTemplateMatcher({_REWARD_CHEST_CONTINUE_BUTTON_TEMPLATE: 0.91})

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader("", ""),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.REWARD_CHEST
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.91
    assert _evidence_labels(analysis) == {"reward_chest_continue_button"}
    assert analysis.evidence[0].kind is EvidenceKind.TEMPLATE
    assert analysis.evidence[0].subject is BaseScreen.REWARD_CHEST
    assert analysis.evidence[0].anchor is ScreenElement.REWARD_CHEST_CONTINUE_BUTTON


def test_analyze_screen_detects_reward_chest_from_closed_chest_template() -> None:
    matcher = FakeTemplateMatcher({_REWARD_CHEST_CLOSED_CHEST_TEMPLATE: 0.91})

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader("", ""),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.REWARD_CHEST
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.91
    assert _evidence_labels(analysis) == {"reward_chest_open_chest"}
    assert analysis.evidence[0].kind is EvidenceKind.TEMPLATE
    assert analysis.evidence[0].subject is BaseScreen.REWARD_CHEST
    assert analysis.evidence[0].anchor is ScreenElement.REWARD_CHEST_OPEN_CHEST


def test_analyze_screen_detects_star_bonus_from_title_ocr_and_okay_template() -> None:
    matcher = FakeTemplateMatcher({_STAR_BONUS_OKAY_BUTTON_TEMPLATE: 0.92})

    analysis = analyze_screen(
        _frame(),
        read_text_fn=FakeTextReader("", "Star Bonus Received!"),
        find_template_fn=matcher,
    )

    assert analysis.base_screen == BaseScreen.STAR_BONUS
    assert analysis.overlay == Overlay.NONE
    assert analysis.confidence == 0.90
    assert _evidence_labels(analysis) == {"star_bonus_title", "star_bonus_okay_button"}
    assert [evidence.kind for evidence in analysis.evidence] == [
        EvidenceKind.OCR,
        EvidenceKind.TEMPLATE,
    ]
    assert {evidence.subject for evidence in analysis.evidence} == {BaseScreen.STAR_BONUS}
    assert {evidence.anchor for evidence in analysis.evidence} == {
        ScreenElement.STAR_BONUS_TITLE,
        ScreenElement.STAR_BONUS_OKAY_BUTTON,
    }


def test_analyze_screen_passes_reference_scales_to_home_templates() -> None:
    matcher = FakeTemplateMatcher(
        {
            _ATTACK_BUTTON_TEMPLATE: 0.91,
            _SHOP_BUTTON_TEMPLATE: 0.89,
        }
    )

    analyze_screen(
        _frame(width=1080, height=504),
        read_text_fn=FakeTextReader(""),
        find_template_fn=matcher,
    )

    scale_calls = _home_scale_calls(matcher)
    assert scale_calls == {
        _ATTACK_BUTTON_TEMPLATE: (0.95, 1.0, 1.05),
        _SHOP_BUTTON_TEMPLATE: (0.95, 1.0, 1.05),
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
    assert set(scale_calls) == {_ATTACK_BUTTON_TEMPLATE, _SHOP_BUTTON_TEMPLATE}
    for scales in scale_calls.values():
        _assert_valid_scale_candidates(scales, expected_center=expected_scale)
        assert math.isclose(scales[1], expected_scale, rel_tol=1e-12)
        assert math.isclose(scales[1], 2.86, rel_tol=0.01)


def test_analyze_screen_detects_connection_lost_without_try_again_and_short_circuits() -> None:
    reader = FakeTextReader("Connection lost\nPlease check your internet connection.")
    matcher = FakeTemplateMatcher(
        {
            _ATTACK_BUTTON_TEMPLATE: 0.91,
            _SHOP_BUTTON_TEMPLATE: 0.89,
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
    assert analysis.recommended_action.kind is ActionKind.TAP
    assert analysis.recommended_action.target is PopupButton.TRY_AGAIN
    assert analysis.recommended_action.reason is Overlay.CONNECTION_LOST
    assert analysis.recommended_action.display_label == "tap_try_again"
    assert analysis.recommended_action.tap_target is None
    assert _evidence_labels(analysis) == {"modal.connection_lost"}
    assert analysis.evidence[0].kind is EvidenceKind.OCR
    assert analysis.evidence[0].subject is Overlay.CONNECTION_LOST
    assert analysis.evidence[0].anchor is None
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
    assert analysis.recommended_action.kind is ActionKind.TAP
    assert analysis.recommended_action.target is PopupButton.RELOAD
    assert analysis.recommended_action.reason is Overlay.ANOTHER_DEVICE_CONNECTED
    assert analysis.recommended_action.display_label == "tap_reload"
    assert analysis.recommended_action.tap_target is None
    assert _evidence_labels(analysis) == {"modal.another_device_connected"}
    assert analysis.evidence[0].kind is EvidenceKind.OCR
    assert analysis.evidence[0].subject is Overlay.ANOTHER_DEVICE_CONNECTED
    assert analysis.evidence[0].anchor is None


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
    assert analysis.recommended_action.kind is ActionKind.TAP
    assert analysis.recommended_action.target is PopupButton.RELOAD_GAME
    assert analysis.recommended_action.reason is Overlay.ANYONE_THERE
    assert analysis.recommended_action.display_label == "tap_reload_game"
    assert analysis.recommended_action.tap_target is None
    assert _evidence_labels(analysis) == {"modal.anyone_there"}
    assert analysis.evidence[0].kind is EvidenceKind.OCR
    assert analysis.evidence[0].subject is Overlay.ANYONE_THERE
    assert analysis.evidence[0].anchor is None


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
    return make_frame(frame_id=None, width=width, height=height, rgba=(0, 0, 0, 255))


def _evidence_labels(analysis: ScreenAnalysis) -> set[str]:
    return {evidence.display_label for evidence in analysis.evidence}


def _home_templates() -> list[str]:
    return [_ATTACK_BUTTON_TEMPLATE, _SHOP_BUTTON_TEMPLATE]


def _home_scale_calls(matcher: FakeTemplateMatcher) -> dict[str, tuple[float, ...]]:
    return {
        template_name: scales
        for template_name, _region, _min_confidence, scales in matcher.calls
        if template_name in {_ATTACK_BUTTON_TEMPLATE, _SHOP_BUTTON_TEMPLATE}
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
        template_name = _template_name(template)
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


def _template_name(template: str | PathLike[str]) -> str:
    template_path = Path(template)
    try:
        return template_path.relative_to(TEMPLATE_DIR).as_posix()
    except ValueError:
        return template_path.name
