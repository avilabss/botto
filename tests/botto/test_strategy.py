"""Tests for declarative attack strategy loading."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from botto.automation.strategy import (
    ActivateHeroAbilitiesAction,
    CastSpellOnDetectedTargetsAction,
    DeployGroupOnOneSideAction,
    DeployUnitAroundPerimeterAction,
    StrategyConfigError,
    StrategyDeploymentGroup,
    StrategyHero,
    StrategySide,
    StrategySpell,
    StrategyTarget,
    StrategyUnit,
    load_attack_strategy,
)


def test_load_attack_strategy_parses_supported_action_categories(tmp_path: Path) -> None:
    strategy_path = _write_strategy(
        tmp_path,
        "mass-super-minion",
        """
[[actions]]
type = "cast_spell_on_detected_targets"
spell = "lightning"
targets = ["air_defense"]
casts_per_target = 3

[[actions]]
type = "deploy_unit_around_perimeter"
unit = "super_minion"
points_per_side = 4
waves = 1

[[actions]]
type = "deploy_group_on_one_side"
group = "cc_and_heroes"
side = "auto"

[[actions]]
type = "activate_hero_abilities"
heroes = [
  "barbarian_king",
  "archer_queen",
  "grand_warden",
  "royal_champion",
]
""".lstrip(),
    )

    loaded = load_attack_strategy("mass-super-minion", base_dir=tmp_path)

    assert loaded.path == strategy_path.resolve()
    assert loaded.strategy.name == "mass-super-minion"
    assert loaded.strategy.actions == _approved_mass_super_minion_actions()


def test_committed_mass_super_minion_strategy_matches_approved_plan() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    loaded = load_attack_strategy("mass-super-minion", base_dir=repo_root)

    assert loaded.strategy.actions == _approved_mass_super_minion_actions()


def test_load_attack_strategy_requires_existing_file(tmp_path: Path) -> None:
    with pytest.raises(StrategyConfigError, match="Attack strategy 'missing' not found at "):
        load_attack_strategy("missing", base_dir=tmp_path)


def test_load_attack_strategy_rejects_invalid_action_values(tmp_path: Path) -> None:
    strategy_path = _write_strategy(
        tmp_path,
        "invalid-target",
        """
[[actions]]
type = "cast_spell_on_detected_targets"
spell = "freeze"
targets = ["gold_storage"]
casts_per_target = 3
""".lstrip(),
    )

    with pytest.raises(
        StrategyConfigError,
        match=re.escape(
            f"Invalid attack strategy at {strategy_path.resolve()}: "
            "actions[0].targets[0] must be one of: air_defense, inferno_tower"
        ),
    ):
        load_attack_strategy("invalid-target", base_dir=tmp_path)


@pytest.mark.parametrize(
    "casts_per_target_line",
    ["casts_per_target = 0", "casts_per_target = -1", "casts_per_target = true", ""],
)
def test_load_attack_strategy_rejects_invalid_casts_per_target(
    tmp_path: Path,
    casts_per_target_line: str,
) -> None:
    strategy_path = _write_strategy(
        tmp_path,
        "invalid-casts-per-target",
        f"""
[[actions]]
type = "cast_spell_on_detected_targets"
spell = "lightning"
targets = ["air_defense"]
{casts_per_target_line}
""".lstrip(),
    )

    with pytest.raises(
        StrategyConfigError,
        match=re.escape(
            f"Invalid attack strategy at {strategy_path.resolve()}: "
            "actions[0].casts_per_target must be a positive integer"
        ),
    ):
        load_attack_strategy("invalid-casts-per-target", base_dir=tmp_path)


@pytest.mark.parametrize(
    ("parameter_name", "parameter_line", "expected_name"),
    [
        ("points_per_side", "points_per_side = 0", "points_per_side"),
        ("points_per_side", "points_per_side = -1", "points_per_side"),
        ("points_per_side", "points_per_side = true", "points_per_side"),
        ("points_per_side", "", "points_per_side"),
        ("waves", "waves = 0", "waves"),
        ("waves", "waves = -1", "waves"),
        ("waves", "waves = true", "waves"),
        ("waves", "", "waves"),
    ],
)
def test_load_attack_strategy_rejects_invalid_perimeter_parameters(
    tmp_path: Path,
    parameter_name: str,
    parameter_line: str,
    expected_name: str,
) -> None:
    other_parameter_line = (
        "waves = 1" if parameter_name == "points_per_side" else "points_per_side = 4"
    )
    strategy_path = _write_strategy(
        tmp_path,
        "invalid-perimeter-parameter",
        f"""
[[actions]]
type = "deploy_unit_around_perimeter"
unit = "super_minion"
{parameter_line}
{other_parameter_line}
""".lstrip(),
    )

    with pytest.raises(
        StrategyConfigError,
        match=re.escape(
            f"Invalid attack strategy at {strategy_path.resolve()}: "
            f"actions[0].{expected_name} must be a positive integer"
        ),
    ):
        load_attack_strategy("invalid-perimeter-parameter", base_dir=tmp_path)


def test_load_attack_strategy_rejects_unsupported_action_category(tmp_path: Path) -> None:
    strategy_path = _write_strategy(
        tmp_path,
        "invalid-action",
        """
[[actions]]
type = "surrender"
""".lstrip(),
    )

    with pytest.raises(
        StrategyConfigError,
        match=re.escape(
            f"Invalid attack strategy at {strategy_path.resolve()}: "
            "actions[0].type must be one of: cast_spell_on_detected_targets, "
            "deploy_unit_around_perimeter, deploy_group_on_one_side, activate_hero_abilities"
        ),
    ):
        load_attack_strategy("invalid-action", base_dir=tmp_path)


def _write_strategy(base_dir: Path, name: str, text: str) -> Path:
    strategy_dir = base_dir / "strategies"
    strategy_dir.mkdir(exist_ok=True)
    strategy_path = strategy_dir / f"{name}.toml"
    strategy_path.write_text(text, encoding="utf-8")
    return strategy_path


def _approved_mass_super_minion_actions() -> tuple[
    CastSpellOnDetectedTargetsAction
    | DeployUnitAroundPerimeterAction
    | DeployGroupOnOneSideAction
    | ActivateHeroAbilitiesAction,
    ...,
]:
    return (
        CastSpellOnDetectedTargetsAction(
            spell=StrategySpell.LIGHTNING,
            targets=(StrategyTarget.AIR_DEFENSE,),
            casts_per_target=3,
        ),
        DeployUnitAroundPerimeterAction(
            unit=StrategyUnit.SUPER_MINION,
            points_per_side=4,
            waves=1,
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
    )
