"""Read-only battle-search metadata parsing and attack eligibility helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from android_game_automator.image import FrameImage
from android_game_automator.ocr import read_text
from android_game_automator.types import NormalizedRect, ScreenRect

from .config import BottoConfig

ResourceName = Literal["gold", "elixir", "dark_elixir"]

_BATTLE_SEARCH_METADATA_REGION = NormalizedRect(left=0.0, top=0.0, width=0.36, height=0.34)
_AVAILABLE_LOOT_PATTERN = re.compile(r"\bavailable\W*loot\b", re.IGNORECASE)
_NUMBER_TOKEN_PATTERN = re.compile(r"(?<!\d)(?:\d{1,3}(?:[ ,\u00a0\u202f]\d{3})+|\d+)(?!\d)")
_RESOURCE_LABEL_PATTERN = re.compile(
    r"\b(?P<gold>gold)\b|\b(?P<dark_elixir>dark(?:\W+elixir)?)\b|\b(?P<elixir>elixir)\b",
    re.IGNORECASE,
)


class BattleSearchTextReader(Protocol):
    """Callable shape used for battle-search OCR so tests can inject fakes."""

    def __call__(self, image: FrameImage, *, region: ScreenRect | None = None) -> str: ...


@dataclass(frozen=True, slots=True)
class AvailableLoot:
    """Available loot values shown for a searched opponent base."""

    gold: int
    elixir: int
    dark_elixir: int

    def __post_init__(self) -> None:
        _validate_non_negative_resource(self.gold, "gold")
        _validate_non_negative_resource(self.elixir, "elixir")
        _validate_non_negative_resource(self.dark_elixir, "dark_elixir")


BattleAvailableLoot = AvailableLoot


@dataclass(frozen=True, slots=True)
class OpponentBaseMetadata:
    """Read-only metadata parsed from a battle preparation/search screen."""

    name: str | None
    clan: str | None
    available_loot: AvailableLoot


@dataclass(frozen=True, slots=True)
class ResourceThresholdFailure:
    """Details for a resource value that is below its configured threshold."""

    resource: ResourceName
    actual: int
    minimum: int


@dataclass(frozen=True, slots=True)
class AttackEligibilityResult:
    """Read-only attack eligibility decision with logging-friendly details."""

    eligible: bool
    missing_resources: tuple[ResourceName, ...] = ()
    failed_thresholds: tuple[ResourceThresholdFailure, ...] = ()


def read_opponent_base_metadata(
    image: FrameImage,
    *,
    read_text_fn: BattleSearchTextReader = read_text,
) -> OpponentBaseMetadata | None:
    """OCR and parse opponent/base loot metadata from the battle-search top-left ROI."""

    text = read_text_fn(image, region=_BATTLE_SEARCH_METADATA_REGION)
    return _parse_opponent_base_metadata_text(text)


def parse_available_loot_text(text: str) -> AvailableLoot | None:
    """Parse Available Loot values from OCR text without inventing missing data."""

    lines = _non_empty_lines(text)
    if not lines:
        return None
    return _parse_available_loot(lines)


def evaluate_attack_eligibility(
    metadata: OpponentBaseMetadata | None,
    config: BottoConfig,
) -> AttackEligibilityResult:
    """Return whether parsed metadata satisfies configured resource thresholds."""

    minimums = _resource_thresholds(config)
    if metadata is None:
        return AttackEligibilityResult(
            eligible=False,
            missing_resources=("gold", "elixir", "dark_elixir"),
        )

    failed_thresholds = tuple(
        ResourceThresholdFailure(resource=resource, actual=actual, minimum=minimums[resource])
        for resource, actual in _loot_values(metadata.available_loot)
        if actual < minimums[resource]
    )
    return AttackEligibilityResult(
        eligible=not failed_thresholds,
        failed_thresholds=failed_thresholds,
    )


def is_attack_eligible(metadata: OpponentBaseMetadata | None, config: BottoConfig) -> bool:
    """Return ``True`` only when all parsed resource values meet configured thresholds."""

    return evaluate_attack_eligibility(metadata, config).eligible


def _parse_opponent_base_metadata_text(text: str) -> OpponentBaseMetadata | None:
    lines = _non_empty_lines(text)
    if not lines:
        return None

    loot = _parse_available_loot(lines)
    if loot is None:
        return None

    name, clan = _parse_opponent_identity(lines)
    return OpponentBaseMetadata(name=name, clan=clan, available_loot=loot)


def _non_empty_lines(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def _parse_available_loot(lines: tuple[str, ...]) -> AvailableLoot | None:
    labeled_values = _parse_labeled_resource_values(lines)
    if all(resource in labeled_values for resource in ("gold", "elixir", "dark_elixir")):
        return AvailableLoot(
            gold=labeled_values["gold"],
            elixir=labeled_values["elixir"],
            dark_elixir=labeled_values["dark_elixir"],
        )

    ordered_values = _parse_ordered_loot_values(lines)
    if len(ordered_values) < 3:
        return None
    return AvailableLoot(
        gold=ordered_values[0],
        elixir=ordered_values[1],
        dark_elixir=ordered_values[2],
    )


def _parse_labeled_resource_values(lines: tuple[str, ...]) -> dict[ResourceName, int]:
    values: dict[ResourceName, int] = {}
    for line in lines:
        labels = _resource_label_matches(line)
        for index, (resource, _start, end) in enumerate(labels):
            if resource in values:
                continue
            segment_end = labels[index + 1][1] if index + 1 < len(labels) else len(line)
            numbers = _number_values_from_text(line[end:segment_end])
            if numbers:
                values[resource] = numbers[0]
    return values


def _resource_label_matches(line: str) -> tuple[tuple[ResourceName, int, int], ...]:
    labels: list[tuple[ResourceName, int, int]] = []
    dark_spans: list[tuple[int, int]] = []
    for match in _RESOURCE_LABEL_PATTERN.finditer(line):
        resource = _resource_from_match(match)
        if resource is None:
            continue
        if resource == "dark_elixir":
            dark_spans.append(match.span())
        elif resource == "elixir" and any(
            _contains_span(span, match.span()) for span in dark_spans
        ):
            continue
        labels.append((resource, match.start(), match.end()))
    return tuple(sorted(labels, key=lambda item: item[1]))


def _resource_from_match(match: re.Match[str]) -> ResourceName | None:
    for resource in ("gold", "dark_elixir", "elixir"):
        if match.group(resource) is not None:
            return resource
    return None


def _contains_span(outer: tuple[int, int], inner: tuple[int, int]) -> bool:
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def _parse_ordered_loot_values(lines: tuple[str, ...]) -> tuple[int, ...]:
    loot_start = _available_loot_line_index(lines)
    search_lines = lines if loot_start is None else lines[loot_start:]
    values: list[int] = []
    for index, line in enumerate(search_lines):
        candidate = (
            _line_after_available_loot_marker(line)
            if index == 0 and loot_start is not None
            else line
        )
        values.extend(_number_values_from_text(candidate))
    return tuple(values)


def _available_loot_line_index(lines: tuple[str, ...]) -> int | None:
    for index, line in enumerate(lines):
        if _AVAILABLE_LOOT_PATTERN.search(line):
            return index
    return None


def _line_after_available_loot_marker(line: str) -> str:
    match = _AVAILABLE_LOOT_PATTERN.search(line)
    if match is None:
        return line
    return line[match.end() :]


def _number_values_from_text(text: str) -> tuple[int, ...]:
    return tuple(
        _parse_number_token(match.group(0)) for match in _NUMBER_TOKEN_PATTERN.finditer(text)
    )


def _parse_number_token(token: str) -> int:
    return int(re.sub(r"[ ,\u00a0\u202f]", "", token))


def _parse_opponent_identity(lines: tuple[str, ...]) -> tuple[str | None, str | None]:
    identity_lines = tuple(_identity_candidate_lines(lines))
    name = identity_lines[0] if identity_lines else None
    clan = identity_lines[1] if len(identity_lines) > 1 else None
    return name, clan


def _identity_candidate_lines(lines: tuple[str, ...]) -> tuple[str, ...]:
    loot_start = _available_loot_line_index(lines)
    if loot_start is not None:
        search_lines = lines[:loot_start]
    else:
        first_number_line = next(
            (index for index, line in enumerate(lines) if _number_values_from_text(line)),
            len(lines),
        )
        search_lines = lines[:first_number_line]

    return tuple(
        line
        for line in search_lines
        if not _AVAILABLE_LOOT_PATTERN.search(line)
        and not _resource_label_matches(line)
        and not _number_values_from_text(line)
    )


def _resource_thresholds(config: BottoConfig) -> dict[ResourceName, int]:
    return {
        "gold": config.attack.resources.min_gold,
        "elixir": config.attack.resources.min_elixir,
        "dark_elixir": config.attack.resources.min_dark_elixir,
    }


def _loot_values(loot: AvailableLoot) -> tuple[tuple[ResourceName, int], ...]:
    return (
        ("gold", loot.gold),
        ("elixir", loot.elixir),
        ("dark_elixir", loot.dark_elixir),
    )


def _validate_non_negative_resource(value: int, resource: ResourceName) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{resource} must be an integer")
    if value < 0:
        raise ValueError(f"{resource} must be >= 0")


__all__ = [
    "AttackEligibilityResult",
    "AvailableLoot",
    "BattleAvailableLoot",
    "BattleSearchTextReader",
    "OpponentBaseMetadata",
    "ResourceThresholdFailure",
    "evaluate_attack_eligibility",
    "is_attack_eligible",
    "parse_available_loot_text",
    "read_opponent_base_metadata",
]
