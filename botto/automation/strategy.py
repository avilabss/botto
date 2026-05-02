"""Declarative attack strategy models and TOML loader."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from os import PathLike
from pathlib import Path
from typing import Any, Final

DEFAULT_STRATEGY_DIRNAME: Final = "strategies"
_STRATEGY_NAME_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class StrategyConfigError(ValueError):
    """Raised when a declarative attack strategy cannot be loaded or validated."""


class StrategyActionType(StrEnum):
    """Supported declarative strategy action categories."""

    CAST_SPELL_ON_DETECTED_TARGETS = "cast_spell_on_detected_targets"
    DEPLOY_UNIT_AROUND_PERIMETER = "deploy_unit_around_perimeter"
    DEPLOY_GROUP_ON_ONE_SIDE = "deploy_group_on_one_side"
    ACTIVATE_HERO_ABILITIES = "activate_hero_abilities"


class StrategySpell(StrEnum):
    """Spell names currently accepted by strategy files."""

    FREEZE = "freeze"
    LIGHTNING = "lightning"
    RAGE = "rage"


class StrategyTarget(StrEnum):
    """Detected target names currently accepted by strategy files."""

    AIR_DEFENSE = "air_defense"
    INFERNO_TOWER = "inferno_tower"


class StrategyUnit(StrEnum):
    """Deployable unit names currently accepted by strategy files."""

    SUPER_MINION = "super_minion"


class StrategyDeploymentGroup(StrEnum):
    """Deployable group names currently accepted by strategy files."""

    CC_AND_HEROES = "cc_and_heroes"
    HEROES = "heroes"


class StrategySide(StrEnum):
    """Screen-side names currently accepted by strategy files."""

    AUTO = "auto"
    TOP = "top"
    RIGHT = "right"
    BOTTOM = "bottom"
    LEFT = "left"


class StrategyHero(StrEnum):
    """Hero names currently accepted by strategy files."""

    BARBARIAN_KING = "barbarian_king"
    ARCHER_QUEEN = "archer_queen"
    GRAND_WARDEN = "grand_warden"
    ROYAL_CHAMPION = "royal_champion"


@dataclass(frozen=True, slots=True)
class CastSpellOnDetectedTargetsAction:
    spell: StrategySpell
    targets: tuple[StrategyTarget, ...]
    casts_per_target: int


@dataclass(frozen=True, slots=True)
class DeployUnitAroundPerimeterAction:
    unit: StrategyUnit
    points_per_side: int
    waves: int


@dataclass(frozen=True, slots=True)
class DeployGroupOnOneSideAction:
    group: StrategyDeploymentGroup
    side: StrategySide


@dataclass(frozen=True, slots=True)
class ActivateHeroAbilitiesAction:
    heroes: tuple[StrategyHero, ...]


type StrategyAction = (
    CastSpellOnDetectedTargetsAction
    | DeployUnitAroundPerimeterAction
    | DeployGroupOnOneSideAction
    | ActivateHeroAbilitiesAction
)


@dataclass(frozen=True, slots=True)
class AttackStrategy:
    name: str
    actions: tuple[StrategyAction, ...]


@dataclass(frozen=True, slots=True)
class LoadedAttackStrategy:
    path: Path
    strategy: AttackStrategy


def load_attack_strategy(
    name: str,
    *,
    base_dir: str | PathLike[str] | None = None,
) -> LoadedAttackStrategy:
    """Load a named strategy from ``strategies/<name>.toml`` under ``base_dir``."""

    _validate_strategy_name(name, "attack.strategy")
    strategy_base_dir = Path.cwd() if base_dir is None else Path(base_dir)
    strategy_path = (
        (strategy_base_dir / DEFAULT_STRATEGY_DIRNAME / f"{name}.toml")
        .expanduser()
        .resolve(strict=False)
    )

    try:
        with strategy_path.open("rb") as strategy_file:
            raw_strategy = tomllib.load(strategy_file)
    except FileNotFoundError as exc:
        raise StrategyConfigError(f"Attack strategy {name!r} not found at {strategy_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise StrategyConfigError(f"Invalid attack strategy at {strategy_path}: {exc}") from exc

    try:
        strategy = _parse_attack_strategy(raw_strategy, name=name, path=strategy_path)
    except StrategyConfigError as exc:
        message = str(exc)
        if message.startswith("Invalid attack strategy at "):
            raise
        raise StrategyConfigError(f"Invalid attack strategy at {strategy_path}: {message}") from exc

    return LoadedAttackStrategy(path=strategy_path, strategy=strategy)


def _parse_attack_strategy(
    raw_strategy: Mapping[str, Any],
    *,
    name: str,
    path: Path,
) -> AttackStrategy:
    _reject_unknown_keys(raw_strategy, {"actions"}, "strategy")

    raw_actions = raw_strategy.get("actions")
    if not isinstance(raw_actions, list):
        raise StrategyConfigError("actions must be an array of action tables")
    if not raw_actions:
        raise StrategyConfigError("actions must contain at least one action")

    return AttackStrategy(
        name=name,
        actions=tuple(
            _parse_action(raw_action, index=index) for index, raw_action in enumerate(raw_actions)
        ),
    )


def _parse_action(raw_action: object, *, index: int) -> StrategyAction:
    context = f"actions[{index}]"
    if not isinstance(raw_action, dict):
        raise StrategyConfigError(f"{context} must be an action table")

    action_type = _require_enum(raw_action, "type", StrategyActionType, context)
    match action_type:
        case StrategyActionType.CAST_SPELL_ON_DETECTED_TARGETS:
            _reject_unknown_keys(
                raw_action,
                {"type", "spell", "targets", "casts_per_target"},
                context,
            )
            return CastSpellOnDetectedTargetsAction(
                spell=_require_enum(raw_action, "spell", StrategySpell, context),
                targets=_require_enum_tuple(raw_action, "targets", StrategyTarget, context),
                casts_per_target=_require_positive_int(raw_action, "casts_per_target", context),
            )
        case StrategyActionType.DEPLOY_UNIT_AROUND_PERIMETER:
            _reject_unknown_keys(raw_action, {"type", "unit", "points_per_side", "waves"}, context)
            return DeployUnitAroundPerimeterAction(
                unit=_require_enum(raw_action, "unit", StrategyUnit, context),
                points_per_side=_require_positive_int(raw_action, "points_per_side", context),
                waves=_require_positive_int(raw_action, "waves", context),
            )
        case StrategyActionType.DEPLOY_GROUP_ON_ONE_SIDE:
            _reject_unknown_keys(raw_action, {"type", "group", "side"}, context)
            return DeployGroupOnOneSideAction(
                group=_require_enum(raw_action, "group", StrategyDeploymentGroup, context),
                side=_require_enum(raw_action, "side", StrategySide, context),
            )
        case StrategyActionType.ACTIVATE_HERO_ABILITIES:
            _reject_unknown_keys(raw_action, {"type", "heroes"}, context)
            return ActivateHeroAbilitiesAction(
                heroes=_require_enum_tuple(raw_action, "heroes", StrategyHero, context),
            )

    raise AssertionError(f"Unsupported strategy action type {action_type!r}")


def _require_enum[EnumT: StrEnum](
    values: Mapping[str, Any],
    key: str,
    enum_type: type[EnumT],
    context: str,
) -> EnumT:
    value = values.get(key)
    dotted_name = f"{context}.{key}"
    if not isinstance(value, str):
        raise StrategyConfigError(f"{dotted_name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise StrategyConfigError(
            f"{dotted_name} must be one of: {_allowed_values(enum_type)}"
        ) from exc


def _require_enum_tuple[EnumT: StrEnum](
    values: Mapping[str, Any],
    key: str,
    enum_type: type[EnumT],
    context: str,
) -> tuple[EnumT, ...]:
    value = values.get(key)
    dotted_name = f"{context}.{key}"
    if not isinstance(value, list):
        raise StrategyConfigError(f"{dotted_name} must be an array of strings")
    if not value:
        raise StrategyConfigError(f"{dotted_name} must contain at least one value")

    parsed_values: list[EnumT] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise StrategyConfigError(f"{dotted_name}[{index}] must be a string")
        try:
            parsed_values.append(enum_type(item))
        except ValueError as exc:
            raise StrategyConfigError(
                f"{dotted_name}[{index}] must be one of: {_allowed_values(enum_type)}"
            ) from exc
    return tuple(parsed_values)


def _require_positive_int(values: Mapping[str, Any], key: str, context: str) -> int:
    value = values.get(key)
    dotted_name = f"{context}.{key}"
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise StrategyConfigError(f"{dotted_name} must be a positive integer")
    return value


def _reject_unknown_keys(values: Mapping[str, Any], allowed_keys: set[str], context: str) -> None:
    unknown_keys = sorted(set(values) - allowed_keys)
    if unknown_keys:
        raise StrategyConfigError(f"{context} contains unsupported keys: {', '.join(unknown_keys)}")


def _allowed_values(enum_type: type[StrEnum]) -> str:
    return ", ".join(item.value for item in enum_type)


def _validate_strategy_name(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise StrategyConfigError(f"{name} must be a string")
    if _STRATEGY_NAME_RE.fullmatch(value) is None:
        raise StrategyConfigError(
            f"{name} must contain only letters, numbers, '-' or '_', and must not be empty"
        )


__all__ = [
    "DEFAULT_STRATEGY_DIRNAME",
    "ActivateHeroAbilitiesAction",
    "AttackStrategy",
    "CastSpellOnDetectedTargetsAction",
    "DeployGroupOnOneSideAction",
    "DeployUnitAroundPerimeterAction",
    "LoadedAttackStrategy",
    "StrategyAction",
    "StrategyActionType",
    "StrategyConfigError",
    "StrategyDeploymentGroup",
    "StrategyHero",
    "StrategySide",
    "StrategySpell",
    "StrategyTarget",
    "StrategyUnit",
    "load_attack_strategy",
]
