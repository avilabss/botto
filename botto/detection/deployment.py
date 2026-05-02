"""Read-only battle deployment inventory and target detection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from android_game_automator.image import FrameImage
from android_game_automator.types import (
    Match,
    NormalizedPoint,
    NormalizedRect,
    Rect,
    ScreenRect,
    Size,
)
from android_game_automator.vision import find_template, find_template_matches

from .common import TemplateMatcher, TemplateMatchesFinder
from .templates import (
    BATTLE_DEPLOYMENT_ARCHER_QUEEN_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_BARBARIAN_KING_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_GRAND_WARDEN_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_LIGHTNING_SPELL_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_RED_CC_SIEGE_SLOT_ASSUMED_CC_TEMPLATE,
    BATTLE_DEPLOYMENT_ROYAL_CHAMPION_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_SUPER_MINION_SLOT_TEMPLATE,
    BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE,
    BATTLE_TARGET_AIR_DEFENSE_ZOOMED_IN_TEMPLATE,
    attack_flow_template_scales,
)


class DeployableKind(StrEnum):
    """Deployment-bar items needed by the Mass Super Minion strategy."""

    SUPER_MINION = "super_minion"
    LIGHTNING_SPELL = "lightning_spell"
    BARBARIAN_KING = "barbarian_king"
    ARCHER_QUEEN = "archer_queen"
    GRAND_WARDEN = "grand_warden"
    ROYAL_CHAMPION = "royal_champion"
    RED_CC_SIEGE_SLOT_ASSUMED_CC = "red_cc_siege_slot_assumed_cc"


class BattleTargetKind(StrEnum):
    """Battlefield building targets detected without taking action."""

    AIR_DEFENSE = "air_defense"


@dataclass(frozen=True, slots=True)
class TemplateMatchEvidence:
    """Debug-friendly details for one template-backed read-only detection."""

    template_path: Path
    source: str
    search_region: ScreenRect
    bounds: Rect
    confidence: float
    scale: float


@dataclass(frozen=True, slots=True)
class DeployableSlotDetection:
    """Detected deployment-bar slot with a tap-safe center for later tasks."""

    kind: DeployableKind
    center: NormalizedPoint
    bounds: Rect
    confidence: float
    evidence: TemplateMatchEvidence


@dataclass(frozen=True, slots=True)
class BattleTargetDetection:
    """Detected battlefield target with a center point for later spell targeting."""

    kind: BattleTargetKind
    center: NormalizedPoint
    bounds: Rect
    confidence: float
    evidence: TemplateMatchEvidence


@dataclass(frozen=True, slots=True)
class _DeployableSlotSpec:
    kind: DeployableKind
    template_path: Path
    region: NormalizedRect


@dataclass(frozen=True, slots=True)
class _BattleTargetSpec:
    kind: BattleTargetKind
    template_path: Path
    region: NormalizedRect
    source: str


_DEPLOYABLE_SLOT_CONFIDENCE = 0.90
_AIR_DEFENSE_TARGET_CONFIDENCE = 0.90
_MAX_AIR_DEFENSE_TARGETS = 4
_BATTLEFIELD_TARGET_REGION = NormalizedRect(left=0.08, top=0.04, width=0.84, height=0.74)

_DEPLOYABLE_SLOT_SPECS = (
    _DeployableSlotSpec(
        kind=DeployableKind.SUPER_MINION,
        template_path=BATTLE_DEPLOYMENT_SUPER_MINION_SLOT_TEMPLATE,
        region=NormalizedRect(left=0.13, top=0.79, width=0.09, height=0.20),
    ),
    _DeployableSlotSpec(
        kind=DeployableKind.RED_CC_SIEGE_SLOT_ASSUMED_CC,
        template_path=BATTLE_DEPLOYMENT_RED_CC_SIEGE_SLOT_ASSUMED_CC_TEMPLATE,
        region=NormalizedRect(left=0.27, top=0.79, width=0.09, height=0.20),
    ),
    _DeployableSlotSpec(
        kind=DeployableKind.BARBARIAN_KING,
        template_path=BATTLE_DEPLOYMENT_BARBARIAN_KING_SLOT_TEMPLATE,
        region=NormalizedRect(left=0.33, top=0.79, width=0.09, height=0.20),
    ),
    _DeployableSlotSpec(
        kind=DeployableKind.ARCHER_QUEEN,
        template_path=BATTLE_DEPLOYMENT_ARCHER_QUEEN_SLOT_TEMPLATE,
        region=NormalizedRect(left=0.39, top=0.79, width=0.09, height=0.20),
    ),
    _DeployableSlotSpec(
        kind=DeployableKind.GRAND_WARDEN,
        template_path=BATTLE_DEPLOYMENT_GRAND_WARDEN_SLOT_TEMPLATE,
        region=NormalizedRect(left=0.46, top=0.79, width=0.09, height=0.20),
    ),
    _DeployableSlotSpec(
        kind=DeployableKind.ROYAL_CHAMPION,
        template_path=BATTLE_DEPLOYMENT_ROYAL_CHAMPION_SLOT_TEMPLATE,
        region=NormalizedRect(left=0.53, top=0.79, width=0.09, height=0.20),
    ),
    _DeployableSlotSpec(
        kind=DeployableKind.LIGHTNING_SPELL,
        template_path=BATTLE_DEPLOYMENT_LIGHTNING_SPELL_SLOT_TEMPLATE,
        region=NormalizedRect(left=0.60, top=0.79, width=0.09, height=0.20),
    ),
)

_AIR_DEFENSE_TARGET_SPECS = (
    _BattleTargetSpec(
        kind=BattleTargetKind.AIR_DEFENSE,
        template_path=BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE,
        region=_BATTLEFIELD_TARGET_REGION,
        source="template:air_defense_zoomed_back",
    ),
    _BattleTargetSpec(
        kind=BattleTargetKind.AIR_DEFENSE,
        template_path=BATTLE_TARGET_AIR_DEFENSE_ZOOMED_IN_TEMPLATE,
        region=_BATTLEFIELD_TARGET_REGION,
        source="template:air_defense_zoomed_in",
    ),
)


def detect_deployable_slots(
    image: FrameImage,
    *,
    find_template_fn: TemplateMatcher = find_template,
) -> tuple[DeployableSlotDetection, ...]:
    """Detect Mass Super Minion deployment-bar slots without issuing input actions."""

    scales = attack_flow_template_scales(image.size)
    detections: list[DeployableSlotDetection] = []
    for spec in _DEPLOYABLE_SLOT_SPECS:
        match = find_template_fn(
            image,
            spec.template_path,
            region=spec.region,
            min_confidence=_DEPLOYABLE_SLOT_CONFIDENCE,
            scales=scales,
        )
        if match is None:
            continue
        detections.append(_deployable_slot_detection(spec, match, image.size))
    return tuple(detections)


def detect_air_defense_targets(
    image: FrameImage,
    *,
    find_template_fn: TemplateMatcher | None = None,
    find_template_matches_fn: TemplateMatchesFinder | None = None,
) -> tuple[BattleTargetDetection, ...]:
    """Detect Air Defense battlefield targets without issuing input actions."""

    scales = attack_flow_template_scales(image.size)
    detections: list[BattleTargetDetection] = []
    for spec in _AIR_DEFENSE_TARGET_SPECS:
        for match in _air_defense_template_matches(
            image,
            spec,
            scales=scales,
            find_template_fn=find_template_fn,
            find_template_matches_fn=find_template_matches_fn,
        ):
            detections.append(_battle_target_detection(spec, match, image.size))
    return _dedupe_battle_target_detections(detections, max_count=_MAX_AIR_DEFENSE_TARGETS)


def _air_defense_template_matches(
    image: FrameImage,
    spec: _BattleTargetSpec,
    *,
    scales: tuple[float, ...],
    find_template_fn: TemplateMatcher | None,
    find_template_matches_fn: TemplateMatchesFinder | None,
) -> tuple[Match, ...]:
    if find_template_matches_fn is not None:
        return find_template_matches_fn(
            image,
            spec.template_path,
            region=spec.region,
            min_confidence=_AIR_DEFENSE_TARGET_CONFIDENCE,
            scales=scales,
            max_matches=_MAX_AIR_DEFENSE_TARGETS,
        )
    if find_template_fn is not None:
        match = find_template_fn(
            image,
            spec.template_path,
            region=spec.region,
            min_confidence=_AIR_DEFENSE_TARGET_CONFIDENCE,
            scales=scales,
        )
        return () if match is None else (match,)
    return find_template_matches(
        image,
        spec.template_path,
        region=spec.region,
        min_confidence=_AIR_DEFENSE_TARGET_CONFIDENCE,
        scales=scales,
        max_matches=_MAX_AIR_DEFENSE_TARGETS,
    )


def _deployable_slot_detection(
    spec: _DeployableSlotSpec,
    match: Match,
    frame_size: Size,
) -> DeployableSlotDetection:
    return DeployableSlotDetection(
        kind=spec.kind,
        center=_normalized_center(match.bounds, frame_size),
        bounds=match.bounds,
        confidence=match.confidence,
        evidence=TemplateMatchEvidence(
            template_path=spec.template_path,
            source=f"template:{spec.kind.value}",
            search_region=spec.region,
            bounds=match.bounds,
            confidence=match.confidence,
            scale=match.scale,
        ),
    )


def _battle_target_detection(
    spec: _BattleTargetSpec,
    match: Match,
    frame_size: Size,
) -> BattleTargetDetection:
    return BattleTargetDetection(
        kind=spec.kind,
        center=_normalized_center(match.bounds, frame_size),
        bounds=match.bounds,
        confidence=match.confidence,
        evidence=TemplateMatchEvidence(
            template_path=spec.template_path,
            source=spec.source,
            search_region=spec.region,
            bounds=match.bounds,
            confidence=match.confidence,
            scale=match.scale,
        ),
    )


def _dedupe_battle_target_detections(
    detections: list[BattleTargetDetection],
    *,
    max_count: int,
) -> tuple[BattleTargetDetection, ...]:
    selected: list[BattleTargetDetection] = []
    for detection in sorted(detections, key=_battle_target_confidence_sort_key):
        if any(_rects_intersect(detection.bounds, existing.bounds) for existing in selected):
            continue
        selected.append(detection)
        if len(selected) >= max_count:
            break
    return tuple(sorted(selected, key=_battle_target_position_sort_key))


def _battle_target_confidence_sort_key(
    detection: BattleTargetDetection,
) -> tuple[float, int, int, int, str]:
    return (
        -detection.confidence,
        -(detection.bounds.width * detection.bounds.height),
        detection.bounds.top,
        detection.bounds.left,
        detection.evidence.source,
    )


def _battle_target_position_sort_key(
    detection: BattleTargetDetection,
) -> tuple[float, float, float, str]:
    return (
        detection.center.y,
        detection.center.x,
        -detection.confidence,
        detection.evidence.source,
    )


def _rects_intersect(first: Rect, second: Rect) -> bool:
    return (
        first.left < second.right
        and second.left < first.right
        and first.top < second.bottom
        and second.top < first.bottom
    )


def _normalized_center(bounds: Rect, frame_size: Size) -> NormalizedPoint:
    center_x = bounds.left + bounds.width / 2.0
    center_y = bounds.top + bounds.height / 2.0
    return NormalizedPoint(
        x=_normalize_pixel_coordinate(center_x, frame_size.width),
        y=_normalize_pixel_coordinate(center_y, frame_size.height),
    )


def _normalize_pixel_coordinate(value: float, axis_size: int) -> float:
    if axis_size <= 1:
        return 0.0
    return min(max(value / (axis_size - 1), 0.0), 1.0)


__all__ = [
    "BattleTargetDetection",
    "BattleTargetKind",
    "DeployableKind",
    "DeployableSlotDetection",
    "TemplateMatchEvidence",
    "detect_air_defense_targets",
    "detect_deployable_slots",
]
