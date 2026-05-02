"""Dry-run attack strategy execution planner."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from android_game_automator.types import NormalizedPoint

from botto.automation.strategy import (
    ActivateHeroAbilitiesAction,
    AttackStrategy,
    CastSpellOnDetectedTargetsAction,
    DeployGroupOnOneSideAction,
    DeployUnitAroundPerimeterAction,
    StrategyAction,
    StrategyActionType,
    StrategyDeploymentGroup,
    StrategyHero,
    StrategySide,
    StrategySpell,
    StrategyTarget,
    StrategyUnit,
)
from botto.detection.deployment import (
    BattleTargetDetection,
    BattleTargetKind,
    DeployableKind,
    DeployableSlotDetection,
)


@dataclass(frozen=True, slots=True)
class PlannedTapStep:
    """One dry-run tap in a deterministic strategy plan."""

    point: NormalizedPoint
    label: str
    reason: str
    action_type: StrategyActionType | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedSkip:
    """A skipped optional strategy item or action segment."""

    label: str
    reason: str
    action_type: StrategyActionType | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyExecutionPlan:
    """Dry-run strategy plan containing taps and explicit skip reasons."""

    strategy_name: str
    steps: tuple[PlannedTapStep, ...]
    skips: tuple[PlannedSkip, ...]


_SPELL_SLOT_KINDS: Final = {
    StrategySpell.LIGHTNING: DeployableKind.LIGHTNING_SPELL,
}
_TARGET_KINDS: Final = {
    StrategyTarget.AIR_DEFENSE: BattleTargetKind.AIR_DEFENSE,
}
_UNIT_SLOT_KINDS: Final = {
    StrategyUnit.SUPER_MINION: DeployableKind.SUPER_MINION,
}
_HERO_SLOT_KINDS: Final = {
    StrategyHero.BARBARIAN_KING: DeployableKind.BARBARIAN_KING,
    StrategyHero.ARCHER_QUEEN: DeployableKind.ARCHER_QUEEN,
    StrategyHero.GRAND_WARDEN: DeployableKind.GRAND_WARDEN,
    StrategyHero.ROYAL_CHAMPION: DeployableKind.ROYAL_CHAMPION,
}
_HERO_BY_SLOT_KIND: Final = {slot_kind: hero for hero, slot_kind in _HERO_SLOT_KINDS.items()}
_CC_AND_HERO_SLOT_ORDER: Final = (
    DeployableKind.RED_CC_SIEGE_SLOT_ASSUMED_CC,
    DeployableKind.BARBARIAN_KING,
    DeployableKind.ARCHER_QUEEN,
    DeployableKind.GRAND_WARDEN,
    DeployableKind.ROYAL_CHAMPION,
)
_PERIMETER_SIDES: Final = (
    StrategySide.TOP,
    StrategySide.RIGHT,
    StrategySide.BOTTOM,
    StrategySide.LEFT,
)
_AUTO_SIDE_TIE_BREAK_ORDER: Final = (
    StrategySide.BOTTOM,
    StrategySide.RIGHT,
    StrategySide.LEFT,
    StrategySide.TOP,
)
_PERIMETER_X_MIN: Final = 0.20
_PERIMETER_X_MAX: Final = 0.80
_PERIMETER_Y_MIN: Final = 0.20
_PERIMETER_Y_MAX: Final = 0.68
_PERIMETER_TOP_Y: Final = 0.12
_PERIMETER_RIGHT_X: Final = 0.88
_PERIMETER_BOTTOM_Y: Final = 0.74
_PERIMETER_LEFT_X: Final = 0.12
_GROUP_DEPLOY_POINTS: Final = {
    StrategySide.TOP: NormalizedPoint(x=0.50, y=0.16),
    StrategySide.RIGHT: NormalizedPoint(x=0.84, y=0.45),
    StrategySide.BOTTOM: NormalizedPoint(x=0.50, y=0.70),
    StrategySide.LEFT: NormalizedPoint(x=0.16, y=0.45),
}


def plan_strategy_execution(
    strategy: AttackStrategy,
    *,
    deployable_slots: Iterable[DeployableSlotDetection],
    battle_targets: Iterable[BattleTargetDetection],
) -> StrategyExecutionPlan:
    """Convert a strategy and read-only detections into a dry-run tap plan."""

    builder = _StrategyPlanBuilder(
        strategy=strategy,
        deployable_slots=deployable_slots,
        battle_targets=battle_targets,
    )
    return builder.build()


class _StrategyPlanBuilder:
    def __init__(
        self,
        *,
        strategy: AttackStrategy,
        deployable_slots: Iterable[DeployableSlotDetection],
        battle_targets: Iterable[BattleTargetDetection],
    ) -> None:
        self._strategy = strategy
        self._slots_by_kind = _best_slots_by_kind(deployable_slots)
        self._targets_by_kind = _targets_by_kind(battle_targets)
        self._steps: list[PlannedTapStep] = []
        self._skips: list[PlannedSkip] = []
        self._planned_perimeter_sides: list[StrategySide] = []
        self._deployed_hero_slots: dict[StrategyHero, DeployableSlotDetection] = {}

    def build(self) -> StrategyExecutionPlan:
        for action in self._strategy.actions:
            self._plan_action(action)
        return StrategyExecutionPlan(
            strategy_name=self._strategy.name,
            steps=tuple(self._steps),
            skips=tuple(self._skips),
        )

    def _plan_action(self, action: StrategyAction) -> None:
        match action:
            case CastSpellOnDetectedTargetsAction():
                self._plan_cast_spell_on_detected_targets(action)
            case DeployUnitAroundPerimeterAction():
                self._plan_deploy_unit_around_perimeter(action)
            case DeployGroupOnOneSideAction():
                self._plan_deploy_group_on_one_side(action)
            case ActivateHeroAbilitiesAction():
                self._plan_activate_hero_abilities(action)

    def _plan_cast_spell_on_detected_targets(
        self,
        action: CastSpellOnDetectedTargetsAction,
    ) -> None:
        action_type = StrategyActionType.CAST_SPELL_ON_DETECTED_TARGETS
        slot_kind = _SPELL_SLOT_KINDS.get(action.spell)
        if slot_kind is None:
            self._skip(
                label=f"spell.{action.spell.value}",
                reason=f"unsupported spell {action.spell.value}; no deployment slot mapping",
                action_type=action_type,
                source="strategy",
            )
            return

        targets = self._spell_targets(action, action_type=action_type)
        if not targets:
            return

        slot = self._slots_by_kind.get(slot_kind)
        if slot is None:
            self._skip(
                label=f"spell.{action.spell.value}.slot",
                reason=f"missing detected {slot_kind.value} slot; skipping spell casts",
                action_type=action_type,
                source="deployment_detection",
            )
            return

        self._add_step(
            point=slot.center,
            label=f"spell.{action.spell.value}.select",
            reason=f"select {slot_kind.value} slot for detected target casts",
            action_type=action_type,
            source=slot.evidence.source,
        )
        for target_index, target in enumerate(targets, start=1):
            for cast_index in range(1, action.casts_per_target + 1):
                self._add_step(
                    point=target.center,
                    label=(
                        f"spell.{action.spell.value}.{target.kind.value}."
                        f"target_{target_index}.cast_{cast_index}"
                    ),
                    reason=(
                        f"cast {action.spell.value} on {target.kind.value} target "
                        f"{target_index} ({cast_index}/{action.casts_per_target})"
                    ),
                    action_type=action_type,
                    source=target.evidence.source,
                )

    def _spell_targets(
        self,
        action: CastSpellOnDetectedTargetsAction,
        *,
        action_type: StrategyActionType,
    ) -> tuple[BattleTargetDetection, ...]:
        targets: list[BattleTargetDetection] = []
        for strategy_target in action.targets:
            target_kind = _TARGET_KINDS.get(strategy_target)
            if target_kind is None:
                self._skip(
                    label=f"spell.{action.spell.value}.{strategy_target.value}.targets",
                    reason=f"unsupported target {strategy_target.value}; no detection mapping",
                    action_type=action_type,
                    source="strategy",
                )
                continue
            detected_targets = self._targets_by_kind.get(target_kind, ())
            if not detected_targets:
                self._skip(
                    label=f"spell.{action.spell.value}.{strategy_target.value}.targets",
                    reason=(
                        f"no detected {strategy_target.value} targets; "
                        f"skipping {action.spell.value} target casts"
                    ),
                    action_type=action_type,
                    source="target_detection",
                )
                continue
            targets.extend(detected_targets)
        return tuple(sorted(targets, key=_target_sort_key))

    def _plan_deploy_unit_around_perimeter(
        self,
        action: DeployUnitAroundPerimeterAction,
    ) -> None:
        action_type = StrategyActionType.DEPLOY_UNIT_AROUND_PERIMETER
        slot_kind = _UNIT_SLOT_KINDS.get(action.unit)
        if slot_kind is None:
            self._skip(
                label=f"unit.{action.unit.value}.perimeter",
                reason=f"unsupported unit {action.unit.value}; no deployment slot mapping",
                action_type=action_type,
                source="strategy",
            )
            return

        slot = self._slots_by_kind.get(slot_kind)
        if slot is None:
            self._skip(
                label=f"unit.{action.unit.value}.slot",
                reason=f"missing detected {slot_kind.value} slot; skipping perimeter deployment",
                action_type=action_type,
                source="deployment_detection",
            )
            return

        self._add_step(
            point=slot.center,
            label=f"unit.{action.unit.value}.select",
            reason=f"select {slot_kind.value} slot for perimeter deployment",
            action_type=action_type,
            source=slot.evidence.source,
        )
        for wave_index, side, point_index, point in _perimeter_drop_points(action):
            self._planned_perimeter_sides.append(side)
            self._add_step(
                point=point,
                label=(
                    f"unit.{action.unit.value}.perimeter.{side.value}."
                    f"wave_{wave_index}.point_{point_index}"
                ),
                reason=(
                    f"deploy {action.unit.value} on {side.value} perimeter "
                    f"wave {wave_index}, point {point_index}"
                ),
                action_type=action_type,
                source="strategy:perimeter",
            )

    def _plan_deploy_group_on_one_side(self, action: DeployGroupOnOneSideAction) -> None:
        action_type = StrategyActionType.DEPLOY_GROUP_ON_ONE_SIDE
        if action.group is not StrategyDeploymentGroup.CC_AND_HEROES:
            self._skip(
                label=f"group.{action.group.value}",
                reason=f"unsupported deployment group {action.group.value}; no slot mapping",
                action_type=action_type,
                source="strategy",
            )
            return

        side = self._resolve_group_side(action.side)
        deploy_point = _group_deploy_point(side)
        for slot_kind in _CC_AND_HERO_SLOT_ORDER:
            slot = self._slots_by_kind.get(slot_kind)
            if slot is None:
                self._skip(
                    label=f"group.{action.group.value}.{slot_kind.value}.slot",
                    reason=(
                        f"missing detected {slot_kind.value} slot; skipping group item deployment"
                    ),
                    action_type=action_type,
                    source="deployment_detection",
                )
                continue

            self._add_step(
                point=slot.center,
                label=f"group.{action.group.value}.{slot_kind.value}.select",
                reason=f"select {slot_kind.value} slot for {side.value} side deployment",
                action_type=action_type,
                source=slot.evidence.source,
            )
            self._add_step(
                point=deploy_point,
                label=f"group.{action.group.value}.{slot_kind.value}.deploy.{side.value}",
                reason=f"deploy {slot_kind.value} on {side.value} side",
                action_type=action_type,
                source=f"strategy:side:{side.value}",
            )

            hero = _HERO_BY_SLOT_KIND.get(slot_kind)
            if hero is not None:
                self._deployed_hero_slots[hero] = slot

    def _resolve_group_side(self, strategy_side: StrategySide) -> StrategySide:
        if strategy_side is StrategySide.AUTO:
            return _choose_auto_side(self._planned_perimeter_sides)
        return strategy_side

    def _plan_activate_hero_abilities(self, action: ActivateHeroAbilitiesAction) -> None:
        action_type = StrategyActionType.ACTIVATE_HERO_ABILITIES
        for hero in action.heroes:
            slot_kind = _HERO_SLOT_KINDS.get(hero)
            if slot_kind is None:
                self._skip(
                    label=f"hero.{hero.value}.ability",
                    reason=f"unsupported hero {hero.value}; no slot mapping",
                    action_type=action_type,
                    source="strategy",
                )
                continue

            slot = self._deployed_hero_slots.get(hero)
            if slot is None:
                self._skip(
                    label=f"hero.{hero.value}.ability",
                    reason=_missing_hero_ability_reason(hero, self._slots_by_kind.get(slot_kind)),
                    action_type=action_type,
                    source="deployment_detection",
                )
                continue

            self._add_step(
                point=slot.center,
                label=f"hero.{hero.value}.ability",
                reason=f"activate {hero.value} ability after deployment",
                action_type=action_type,
                source=slot.evidence.source,
            )

    def _add_step(
        self,
        *,
        point: NormalizedPoint,
        label: str,
        reason: str,
        action_type: StrategyActionType,
        source: str,
    ) -> None:
        self._steps.append(
            PlannedTapStep(
                point=point,
                label=label,
                reason=reason,
                action_type=action_type,
                source=source,
            )
        )

    def _skip(
        self,
        *,
        label: str,
        reason: str,
        action_type: StrategyActionType,
        source: str,
    ) -> None:
        self._skips.append(
            PlannedSkip(
                label=label,
                reason=reason,
                action_type=action_type,
                source=source,
            )
        )


def _best_slots_by_kind(
    slots: Iterable[DeployableSlotDetection],
) -> dict[DeployableKind, DeployableSlotDetection]:
    slots_by_kind: dict[DeployableKind, DeployableSlotDetection] = {}
    for slot in slots:
        existing = slots_by_kind.get(slot.kind)
        if existing is None or _slot_rank(slot) < _slot_rank(existing):
            slots_by_kind[slot.kind] = slot
    return slots_by_kind


def _targets_by_kind(
    targets: Iterable[BattleTargetDetection],
) -> dict[BattleTargetKind, tuple[BattleTargetDetection, ...]]:
    targets_by_kind: dict[BattleTargetKind, list[BattleTargetDetection]] = {}
    for target in targets:
        targets_by_kind.setdefault(target.kind, []).append(target)
    return {
        kind: tuple(sorted(kind_targets, key=_target_sort_key))
        for kind, kind_targets in targets_by_kind.items()
    }


def _slot_rank(slot: DeployableSlotDetection) -> tuple[float, int, int, float, float]:
    return (-slot.confidence, slot.bounds.top, slot.bounds.left, slot.center.y, slot.center.x)


def _target_sort_key(target: BattleTargetDetection) -> tuple[float, float, float]:
    return (target.center.y, target.center.x, -target.confidence)


def _perimeter_drop_points(
    action: DeployUnitAroundPerimeterAction,
) -> Iterable[tuple[int, StrategySide, int, NormalizedPoint]]:
    x_positions = _spread(action.points_per_side, start=_PERIMETER_X_MIN, end=_PERIMETER_X_MAX)
    y_positions = _spread(action.points_per_side, start=_PERIMETER_Y_MIN, end=_PERIMETER_Y_MAX)
    for wave_index in range(1, action.waves + 1):
        for side in _PERIMETER_SIDES:
            for point_index in range(1, action.points_per_side + 1):
                yield (
                    wave_index,
                    side,
                    point_index,
                    _perimeter_point(
                        side,
                        point_index=point_index,
                        x_positions=x_positions,
                        y_positions=y_positions,
                    ),
                )


def _spread(count: int, *, start: float, end: float) -> tuple[float, ...]:
    if count <= 0:
        raise ValueError("perimeter point count must be positive")
    if count == 1:
        return ((start + end) / 2.0,)
    step = (end - start) / (count - 1)
    return tuple(start + step * index for index in range(count))


def _perimeter_point(
    side: StrategySide,
    *,
    point_index: int,
    x_positions: tuple[float, ...],
    y_positions: tuple[float, ...],
) -> NormalizedPoint:
    offset = point_index - 1
    reverse_offset = len(x_positions) - point_index
    match side:
        case StrategySide.TOP:
            return NormalizedPoint(x=x_positions[offset], y=_PERIMETER_TOP_Y)
        case StrategySide.RIGHT:
            return NormalizedPoint(x=_PERIMETER_RIGHT_X, y=y_positions[offset])
        case StrategySide.BOTTOM:
            return NormalizedPoint(x=x_positions[reverse_offset], y=_PERIMETER_BOTTOM_Y)
        case StrategySide.LEFT:
            return NormalizedPoint(x=_PERIMETER_LEFT_X, y=y_positions[reverse_offset])
        case StrategySide.AUTO:
            raise ValueError("auto is not a concrete perimeter side")


def _choose_auto_side(planned_perimeter_sides: Iterable[StrategySide]) -> StrategySide:
    side_counts = Counter(planned_perimeter_sides)
    if not side_counts:
        return StrategySide.BOTTOM
    highest_count = max(side_counts.values())
    for side in _AUTO_SIDE_TIE_BREAK_ORDER:
        if side_counts.get(side, 0) == highest_count:
            return side
    return StrategySide.BOTTOM


def _group_deploy_point(side: StrategySide) -> NormalizedPoint:
    return _GROUP_DEPLOY_POINTS[side]


def _missing_hero_ability_reason(
    hero: StrategyHero,
    slot: DeployableSlotDetection | None,
) -> str:
    if slot is None:
        return f"missing detected {hero.value} slot; skipping hero ability activation"
    return (
        f"{hero.value} was not deployed by an earlier group action; "
        "skipping hero ability activation"
    )


__all__ = [
    "PlannedSkip",
    "PlannedTapStep",
    "StrategyExecutionPlan",
    "plan_strategy_execution",
]
