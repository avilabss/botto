"""Required Botto startup config models and loader."""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any, Final

DEFAULT_CONFIG_FILENAME: Final = "botto.toml"
_STRATEGY_NAME_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class BottoConfigError(ValueError):
    """Raised when Botto config cannot be loaded or validated."""


@dataclass(frozen=True, slots=True)
class AttackResourcesConfig:
    min_gold: int
    min_elixir: int
    min_dark_elixir: int

    def __post_init__(self) -> None:
        _validate_non_negative_int(self.min_gold, "attack.resources.min_gold")
        _validate_non_negative_int(self.min_elixir, "attack.resources.min_elixir")
        _validate_non_negative_int(self.min_dark_elixir, "attack.resources.min_dark_elixir")


@dataclass(frozen=True, slots=True)
class AttackSearchConfig:
    max_searches: int

    def __post_init__(self) -> None:
        _validate_positive_int(self.max_searches, "attack.search.max_searches")


@dataclass(frozen=True, slots=True)
class AttackBattleConfig:
    resource_stall_seconds: float

    def __post_init__(self) -> None:
        _validate_positive_number(
            self.resource_stall_seconds,
            "attack.battle.resource_stall_seconds",
        )


@dataclass(frozen=True, slots=True)
class AttackConfig:
    strategy: str
    resources: AttackResourcesConfig
    search: AttackSearchConfig
    battle: AttackBattleConfig

    def __post_init__(self) -> None:
        _validate_strategy_name(self.strategy, "attack.strategy")


@dataclass(frozen=True, slots=True)
class BottoConfig:
    attack: AttackConfig

    def effective_values(self) -> Mapping[str, str | int | float]:
        """Return a stable flattened view used for startup logging."""

        return {
            "attack.strategy": self.attack.strategy,
            "attack.resources.min_gold": self.attack.resources.min_gold,
            "attack.resources.min_elixir": self.attack.resources.min_elixir,
            "attack.resources.min_dark_elixir": self.attack.resources.min_dark_elixir,
            "attack.search.max_searches": self.attack.search.max_searches,
            "attack.battle.resource_stall_seconds": self.attack.battle.resource_stall_seconds,
        }


@dataclass(frozen=True, slots=True)
class LoadedBottoConfig:
    path: Path
    config: BottoConfig


def load_botto_config(path: str | PathLike[str] | None = None) -> LoadedBottoConfig:
    """Load required Botto config from ``path`` or ``./botto.toml``."""

    config_path = _default_config_path() if path is None else Path(path)
    config_path = config_path.expanduser().resolve(strict=False)
    try:
        with config_path.open("rb") as config_file:
            raw_config = tomllib.load(config_file)
    except FileNotFoundError as exc:
        raise BottoConfigError(f"Botto config not found at {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise BottoConfigError(f"Invalid Botto config at {config_path}: {exc}") from exc

    try:
        config = _parse_botto_config(raw_config, config_path)
    except BottoConfigError as exc:
        message = str(exc)
        if message.startswith("Invalid Botto config at "):
            raise
        raise BottoConfigError(f"Invalid Botto config at {config_path}: {message}") from exc

    return LoadedBottoConfig(path=config_path, config=config)


def load_config(path: str | PathLike[str] | None = None) -> LoadedBottoConfig:
    """Compatibility alias for the Botto config loader."""

    return load_botto_config(path)


def _default_config_path() -> Path:
    return Path.cwd() / DEFAULT_CONFIG_FILENAME


def _parse_botto_config(raw_config: Mapping[str, Any], path: Path) -> BottoConfig:
    attack = _require_table(raw_config, "attack", path)
    resources = _require_table(attack, "resources", path, parent="attack")
    search = _require_table(attack, "search", path, parent="attack")
    battle = _require_table(attack, "battle", path, parent="attack")

    return BottoConfig(
        attack=AttackConfig(
            strategy=_require_str(attack, "strategy", path, parent="attack"),
            resources=AttackResourcesConfig(
                min_gold=_require_int(resources, "min_gold", path, parent="attack.resources"),
                min_elixir=_require_int(resources, "min_elixir", path, parent="attack.resources"),
                min_dark_elixir=_require_int(
                    resources,
                    "min_dark_elixir",
                    path,
                    parent="attack.resources",
                ),
            ),
            search=AttackSearchConfig(
                max_searches=_require_int(search, "max_searches", path, parent="attack.search"),
            ),
            battle=AttackBattleConfig(
                resource_stall_seconds=_require_number(
                    battle,
                    "resource_stall_seconds",
                    path,
                    parent="attack.battle",
                ),
            ),
        )
    )


def _require_table(
    values: Mapping[str, Any],
    key: str,
    path: Path,
    *,
    parent: str | None = None,
) -> Mapping[str, Any]:
    value = values.get(key)
    dotted_name = key if parent is None else f"{parent}.{key}"
    if not isinstance(value, dict):
        raise BottoConfigError(f"Invalid Botto config at {path}: [{dotted_name}] is required")
    return value


def _require_int(
    values: Mapping[str, Any],
    key: str,
    path: Path,
    *,
    parent: str,
) -> int:
    value = values.get(key)
    dotted_name = f"{parent}.{key}"
    if isinstance(value, bool) or not isinstance(value, int):
        raise BottoConfigError(f"Invalid Botto config at {path}: {dotted_name} must be an integer")
    return value


def _require_str(
    values: Mapping[str, Any],
    key: str,
    path: Path,
    *,
    parent: str,
) -> str:
    dotted_name = f"{parent}.{key}"
    if key not in values:
        raise BottoConfigError(f"Invalid Botto config at {path}: {dotted_name} is required")
    value = values[key]
    if not isinstance(value, str):
        raise BottoConfigError(f"Invalid Botto config at {path}: {dotted_name} must be a string")
    return value


def _require_number(
    values: Mapping[str, Any],
    key: str,
    path: Path,
    *,
    parent: str,
) -> float:
    value = values.get(key)
    dotted_name = f"{parent}.{key}"
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BottoConfigError(f"Invalid Botto config at {path}: {dotted_name} must be numeric")
    return float(value)


def _validate_non_negative_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BottoConfigError(f"{name} must be an integer")
    if value < 0:
        raise BottoConfigError(f"{name} must be >= 0")


def _validate_positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BottoConfigError(f"{name} must be an integer")
    if value <= 0:
        raise BottoConfigError(f"{name} must be > 0")


def _validate_positive_number(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BottoConfigError(f"{name} must be numeric")
    if not math.isfinite(float(value)) or value <= 0:
        raise BottoConfigError(f"{name} must be > 0")


def _validate_strategy_name(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise BottoConfigError(f"{name} must be a string")
    if _STRATEGY_NAME_RE.fullmatch(value) is None:
        raise BottoConfigError(
            f"{name} must contain only letters, numbers, '-' or '_', and must not be empty"
        )


__all__ = [
    "DEFAULT_CONFIG_FILENAME",
    "AttackBattleConfig",
    "AttackConfig",
    "AttackResourcesConfig",
    "AttackSearchConfig",
    "BottoConfig",
    "BottoConfigError",
    "LoadedBottoConfig",
    "load_botto_config",
    "load_config",
]
