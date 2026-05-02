"""Tests for read-only battle deployment and target detection helpers."""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedPoint
from botto.detection.deployment import (
    BattleTargetKind,
    DeployableKind,
    detect_air_defense_targets,
    detect_deployable_slots,
)
from botto.detection.templates import (
    BATTLE_DEPLOYMENT_ARCHER_QUEEN_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_BARBARIAN_KING_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_GRAND_WARDEN_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_LIGHTNING_SPELL_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_RED_CC_SIEGE_SLOT_ASSUMED_CC_TEMPLATE,
    BATTLE_DEPLOYMENT_ROYAL_CHAMPION_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_SUPER_MINION_SLOT_TEMPLATE,
    BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE,
)
from PIL import Image

_FRAME_WIDTH = 1080
_FRAME_HEIGHT = 504
_SLOT_PLACEMENTS = {
    DeployableKind.SUPER_MINION: (BATTLE_DEPLOYMENT_SUPER_MINION_SLOT_TEMPLATE, 155, 415),
    DeployableKind.RED_CC_SIEGE_SLOT_ASSUMED_CC: (
        BATTLE_DEPLOYMENT_RED_CC_SIEGE_SLOT_ASSUMED_CC_TEMPLATE,
        305,
        415,
    ),
    DeployableKind.BARBARIAN_KING: (BATTLE_DEPLOYMENT_BARBARIAN_KING_SLOT_TEMPLATE, 374, 415),
    DeployableKind.ARCHER_QUEEN: (BATTLE_DEPLOYMENT_ARCHER_QUEEN_SLOT_TEMPLATE, 442, 415),
    DeployableKind.GRAND_WARDEN: (BATTLE_DEPLOYMENT_GRAND_WARDEN_SLOT_TEMPLATE, 510, 415),
    DeployableKind.ROYAL_CHAMPION: (BATTLE_DEPLOYMENT_ROYAL_CHAMPION_SLOT_TEMPLATE, 578, 415),
    DeployableKind.LIGHTNING_SPELL: (BATTLE_DEPLOYMENT_LIGHTNING_SPELL_SLOT_TEMPLATE, 654, 415),
}


def test_detect_deployable_slots_finds_committed_templates_in_synthetic_bar() -> None:
    frame = _synthetic_frame(
        (template_path, (left, top)) for template_path, left, top in _SLOT_PLACEMENTS.values()
    )

    detections = detect_deployable_slots(frame)

    assert tuple(detection.kind for detection in detections) == tuple(_SLOT_PLACEMENTS)
    for detection in detections:
        template_path, left, top = _SLOT_PLACEMENTS[detection.kind]
        assert detection.confidence >= 0.90
        assert detection.evidence.template_path == template_path
        assert detection.evidence.source == f"template:{detection.kind.value}"
        assert detection.evidence.search_region.top >= 0.79
        _assert_normalized_points_close(
            detection.center,
            _expected_template_center(template_path, left=left, top=top),
        )


def test_deployable_slot_detection_ignores_matching_template_outside_bar_roi() -> None:
    frame = _synthetic_frame([(BATTLE_DEPLOYMENT_SUPER_MINION_SLOT_TEMPLATE, (155, 120))])

    detections = detect_deployable_slots(frame)

    assert detections == ()


def test_detect_air_defense_targets_finds_committed_template_in_battlefield() -> None:
    left = 335
    top = 222
    frame = _synthetic_frame([(BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE, (left, top))])

    detections = detect_air_defense_targets(frame)

    matching_air_defenses = tuple(
        detection
        for detection in detections
        if detection.evidence.template_path == BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE
    )
    assert len(matching_air_defenses) == 1
    air_defense = matching_air_defenses[0]

    assert air_defense.kind is BattleTargetKind.AIR_DEFENSE
    assert air_defense.confidence >= 0.90
    assert air_defense.evidence.source == "template:air_defense_zoomed_back"
    assert air_defense.evidence.search_region.bottom <= 0.78
    _assert_normalized_points_close(
        air_defense.center,
        _expected_template_center(
            BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE, left=left, top=top
        ),
    )


def test_detect_air_defense_targets_finds_multiple_non_overlapping_targets() -> None:
    placements = (
        (BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE, (260, 124)),
        (BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE, (650, 252)),
    )
    frame = _synthetic_frame(placements)

    detections = detect_air_defense_targets(frame)

    matching_air_defenses = tuple(
        detection
        for detection in detections
        if detection.evidence.template_path == BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE
    )
    assert len(matching_air_defenses) == 2
    for detection, (_, (left, top)) in zip(matching_air_defenses, placements, strict=True):
        assert detection.kind is BattleTargetKind.AIR_DEFENSE
        _assert_normalized_points_close(
            detection.center,
            _expected_template_center(
                BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE, left=left, top=top
            ),
        )


def test_air_defense_detection_ignores_matching_template_in_deployment_bar_roi() -> None:
    frame = _synthetic_frame([(BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE, (335, 420))])

    detections = detect_air_defense_targets(frame)

    assert detections == ()


def _synthetic_frame(placements: Iterable[tuple[Path, tuple[int, int]]]) -> FrameImage:
    image = Image.new("RGBA", (_FRAME_WIDTH, _FRAME_HEIGHT), (17, 19, 23, 255))
    try:
        for template_path, (left, top) in placements:
            with Image.open(template_path) as loaded_template:
                template = loaded_template.convert("RGBA")
                try:
                    image.alpha_composite(template, dest=(left, top))
                finally:
                    template.close()
        return FrameImage.from_pil_image(image)
    finally:
        image.close()


def _expected_template_center(template_path: Path, *, left: int, top: int) -> NormalizedPoint:
    with Image.open(template_path) as template:
        center_x = left + template.width / 2.0
        center_y = top + template.height / 2.0
    return NormalizedPoint(
        x=center_x / (_FRAME_WIDTH - 1),
        y=center_y / (_FRAME_HEIGHT - 1),
    )


def _assert_normalized_points_close(actual: NormalizedPoint, expected: NormalizedPoint) -> None:
    assert math.isclose(actual.x, expected.x, abs_tol=2 / (_FRAME_WIDTH - 1))
    assert math.isclose(actual.y, expected.y, abs_tol=2 / (_FRAME_HEIGHT - 1))
