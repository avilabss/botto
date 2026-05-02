"""Tests for dry-run attack strategy planning."""

from __future__ import annotations

from pathlib import Path

from android_game_automator.types import NormalizedPoint, NormalizedRect, Rect
from botto.automation.planner import plan_strategy_execution
from botto.automation.strategy import (
    ActivateHeroAbilitiesAction,
    AttackStrategy,
    CastSpellOnDetectedTargetsAction,
    DeployGroupOnOneSideAction,
    DeployUnitAroundPerimeterAction,
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
    TemplateMatchEvidence,
)


def test_plan_orders_complete_detections_and_casts_each_air_defense() -> None:
    plan = plan_strategy_execution(
        _mass_super_minion_strategy(points_per_side=1, waves=1, casts_per_target=2),
        deployable_slots=_complete_slots(),
        battle_targets=_air_defense_targets(),
    )

    labels = tuple(step.label for step in plan.steps)

    assert plan.skips == ()
    assert labels[:5] == (
        "spell.lightning.select",
        "spell.lightning.air_defense.target_1.cast_1",
        "spell.lightning.air_defense.target_1.cast_2",
        "spell.lightning.air_defense.target_2.cast_1",
        "spell.lightning.air_defense.target_2.cast_2",
    )
    assert labels[5:10] == (
        "unit.super_minion.select",
        "unit.super_minion.perimeter.top.wave_1.point_1",
        "unit.super_minion.perimeter.right.wave_1.point_1",
        "unit.super_minion.perimeter.bottom.wave_1.point_1",
        "unit.super_minion.perimeter.left.wave_1.point_1",
    )
    assert labels[10:20] == (
        "group.cc_and_heroes.red_cc_siege_slot_assumed_cc.select",
        "group.cc_and_heroes.red_cc_siege_slot_assumed_cc.deploy.bottom",
        "group.cc_and_heroes.barbarian_king.select",
        "group.cc_and_heroes.barbarian_king.deploy.bottom",
        "group.cc_and_heroes.archer_queen.select",
        "group.cc_and_heroes.archer_queen.deploy.bottom",
        "group.cc_and_heroes.grand_warden.select",
        "group.cc_and_heroes.grand_warden.deploy.bottom",
        "group.cc_and_heroes.royal_champion.select",
        "group.cc_and_heroes.royal_champion.deploy.bottom",
    )
    assert labels[20:] == (
        "hero.barbarian_king.ability",
        "hero.archer_queen.ability",
        "hero.grand_warden.ability",
        "hero.royal_champion.ability",
    )
    assert all(step.point.y <= 0.74 for step in plan.steps if ".perimeter." in step.label)


def test_plan_missing_air_defenses_skips_spell_targets_but_keeps_remaining_plan() -> None:
    plan = plan_strategy_execution(
        _mass_super_minion_strategy(points_per_side=1, waves=1),
        deployable_slots=_complete_slots(),
        battle_targets=(),
    )

    labels = tuple(step.label for step in plan.steps)

    assert "spell.lightning.select" not in labels
    assert "unit.super_minion.select" in labels
    assert "group.cc_and_heroes.barbarian_king.select" in labels
    assert "hero.barbarian_king.ability" in labels
    assert any(
        skip.label == "spell.lightning.air_defense.targets"
        and "no detected air_defense targets" in skip.reason
        for skip in plan.skips
    )


def test_plan_missing_super_minion_slot_skips_perimeter_but_keeps_cc_and_heroes() -> None:
    slots = tuple(
        slot for slot in _complete_slots() if slot.kind is not DeployableKind.SUPER_MINION
    )

    plan = plan_strategy_execution(
        _mass_super_minion_strategy(points_per_side=1, waves=1),
        deployable_slots=slots,
        battle_targets=_air_defense_targets(count=1),
    )

    labels = tuple(step.label for step in plan.steps)

    assert all(not label.startswith("unit.super_minion") for label in labels)
    assert "group.cc_and_heroes.red_cc_siege_slot_assumed_cc.select" in labels
    assert "hero.royal_champion.ability" in labels
    assert any(
        skip.label == "unit.super_minion.slot" and "skipping perimeter deployment" in skip.reason
        for skip in plan.skips
    )


def test_plan_missing_hero_slot_records_skips_without_blind_ability_taps() -> None:
    slots = tuple(
        slot for slot in _complete_slots() if slot.kind is not DeployableKind.ARCHER_QUEEN
    )

    plan = plan_strategy_execution(
        _mass_super_minion_strategy(points_per_side=1, waves=1),
        deployable_slots=slots,
        battle_targets=_air_defense_targets(count=1),
    )

    labels = tuple(step.label for step in plan.steps)

    assert "group.cc_and_heroes.archer_queen.select" not in labels
    assert "hero.archer_queen.ability" not in labels
    assert any(skip.label == "group.cc_and_heroes.archer_queen.slot" for skip in plan.skips)
    assert any(skip.label == "hero.archer_queen.ability" for skip in plan.skips)


def test_plan_auto_side_tie_breaks_to_bottom_from_perimeter_sides() -> None:
    plan = plan_strategy_execution(
        _mass_super_minion_strategy(points_per_side=2, waves=1),
        deployable_slots=_complete_slots(),
        battle_targets=_air_defense_targets(count=1),
    )

    group_deploy_steps = tuple(
        step
        for step in plan.steps
        if step.label.startswith("group.cc_and_heroes") and ".deploy." in step.label
    )

    assert group_deploy_steps
    assert all(step.label.endswith(".deploy.bottom") for step in group_deploy_steps)
    assert {step.point for step in group_deploy_steps} == {NormalizedPoint(x=0.50, y=0.70)}


def _mass_super_minion_strategy(
    *,
    points_per_side: int,
    waves: int,
    casts_per_target: int = 1,
) -> AttackStrategy:
    return AttackStrategy(
        name="mass-super-minion",
        actions=(
            CastSpellOnDetectedTargetsAction(
                spell=StrategySpell.LIGHTNING,
                targets=(StrategyTarget.AIR_DEFENSE,),
                casts_per_target=casts_per_target,
            ),
            DeployUnitAroundPerimeterAction(
                unit=StrategyUnit.SUPER_MINION,
                points_per_side=points_per_side,
                waves=waves,
            ),
            DeployGroupOnOneSideAction(
                group=StrategyDeploymentGroup.CC_AND_HEROES,
                side=StrategySide.AUTO,
            ),
            ActivateHeroAbilitiesAction(
                heroes=(
                    StrategyHero.BARBARIAN_KING,
                    StrategyHero.ARCHER_QUEEN,
                    StrategyHero.GRAND_WARDEN,
                    StrategyHero.ROYAL_CHAMPION,
                ),
            ),
        ),
    )


def _complete_slots() -> tuple[DeployableSlotDetection, ...]:
    return (
        _slot(DeployableKind.SUPER_MINION, x=0.15, y=0.88, left=150),
        _slot(DeployableKind.RED_CC_SIEGE_SLOT_ASSUMED_CC, x=0.28, y=0.88, left=280),
        _slot(DeployableKind.BARBARIAN_KING, x=0.35, y=0.88, left=350),
        _slot(DeployableKind.ARCHER_QUEEN, x=0.42, y=0.88, left=420),
        _slot(DeployableKind.GRAND_WARDEN, x=0.49, y=0.88, left=490),
        _slot(DeployableKind.ROYAL_CHAMPION, x=0.56, y=0.88, left=560),
        _slot(DeployableKind.LIGHTNING_SPELL, x=0.64, y=0.88, left=640),
    )


def _air_defense_targets(count: int = 2) -> tuple[BattleTargetDetection, ...]:
    targets = (
        _target(BattleTargetKind.AIR_DEFENSE, x=0.62, y=0.36, left=620, top=180),
        _target(BattleTargetKind.AIR_DEFENSE, x=0.38, y=0.24, left=380, top=120),
    )
    return targets[:count]


def _slot(kind: DeployableKind, *, x: float, y: float, left: int) -> DeployableSlotDetection:
    bounds = Rect(left=left, top=440, width=20, height=20)
    return DeployableSlotDetection(
        kind=kind,
        center=NormalizedPoint(x=x, y=y),
        bounds=bounds,
        confidence=0.99,
        evidence=_evidence(source=f"fake:{kind.value}", bounds=bounds),
    )


def _target(
    kind: BattleTargetKind,
    *,
    x: float,
    y: float,
    left: int,
    top: int,
) -> BattleTargetDetection:
    bounds = Rect(left=left, top=top, width=24, height=24)
    return BattleTargetDetection(
        kind=kind,
        center=NormalizedPoint(x=x, y=y),
        bounds=bounds,
        confidence=0.98,
        evidence=_evidence(source=f"fake:{kind.value}", bounds=bounds),
    )


def _evidence(*, source: str, bounds: Rect) -> TemplateMatchEvidence:
    return TemplateMatchEvidence(
        template_path=Path(f"{source}.png"),
        source=source,
        search_region=NormalizedRect(left=0.0, top=0.0, width=1.0, height=1.0),
        bounds=bounds,
        confidence=0.99,
        scale=1.0,
    )
