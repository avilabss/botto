"""Tests for battle-search metadata parsing and eligibility decisions."""

from __future__ import annotations

import botto.automation as automation
from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedRect, ScreenRect
from botto.automation.config import (
    AttackBattleConfig,
    AttackConfig,
    AttackResourcesConfig,
    AttackSearchConfig,
    BottoConfig,
)
from botto.automation.search import (
    AvailableLoot,
    OpponentBaseMetadata,
    ResourceThresholdFailure,
    evaluate_attack_eligibility,
    is_attack_eligible,
    read_opponent_base_metadata,
)

from tests.botto.fakes import make_frame


def test_read_opponent_base_metadata_uses_top_left_roi_and_parses_grouped_loot() -> None:
    reader = FakeTextReader(
        """
        Chief McChief
        Test Clan
        Available Loot:
        405 473
        1 140 000
        3,158
        """,
    )

    metadata = read_opponent_base_metadata(_frame(), read_text_fn=reader)

    assert metadata == OpponentBaseMetadata(
        name="Chief McChief",
        clan="Test Clan",
        available_loot=AvailableLoot(gold=405473, elixir=1140000, dark_elixir=3158),
    )
    assert len(reader.calls) == 1
    region = reader.calls[0]
    assert isinstance(region, NormalizedRect)
    assert region.left == 0.0
    assert region.top == 0.0
    assert region.width <= 0.40
    assert region.height <= 0.40


def test_read_opponent_base_metadata_parses_labeled_and_plain_numbers() -> None:
    reader = FakeTextReader(
        """
        Available Loot:
        Gold 3158
        Elixir 405 473
        Dark Elixir 3,158
        """,
    )

    metadata = read_opponent_base_metadata(_frame(), read_text_fn=reader)

    assert metadata == OpponentBaseMetadata(
        name=None,
        clan=None,
        available_loot=AvailableLoot(gold=3158, elixir=405473, dark_elixir=3158),
    )


def test_attack_eligibility_requires_each_resource_threshold_to_pass() -> None:
    config = _config(min_gold=500000, min_elixir=400000, min_dark_elixir=3000)

    passing_metadata = OpponentBaseMetadata(
        name=None,
        clan=None,
        available_loot=AvailableLoot(gold=500000, elixir=450000, dark_elixir=3000),
    )
    failing_metadata = OpponentBaseMetadata(
        name=None,
        clan=None,
        available_loot=AvailableLoot(gold=499999, elixir=450000, dark_elixir=2999),
    )

    assert evaluate_attack_eligibility(passing_metadata, config).eligible is True
    assert is_attack_eligible(passing_metadata, config) is True

    result = evaluate_attack_eligibility(failing_metadata, config)

    assert result.eligible is False
    assert result.missing_resources == ()
    assert result.failed_thresholds == (
        ResourceThresholdFailure(resource="gold", actual=499999, minimum=500000),
        ResourceThresholdFailure(resource="dark_elixir", actual=2999, minimum=3000),
    )
    assert is_attack_eligible(failing_metadata, config) is False


def test_malformed_ocr_produces_no_metadata_and_safe_not_eligible_result() -> None:
    config = _config(min_gold=1, min_elixir=1, min_dark_elixir=1)
    reader = FakeTextReader("Available Loot:\nGold lots\nElixir ?")

    metadata = read_opponent_base_metadata(_frame(), read_text_fn=reader)
    result = evaluate_attack_eligibility(metadata, config)

    assert metadata is None
    assert result.eligible is False
    assert result.missing_resources == ("gold", "elixir", "dark_elixir")
    assert result.failed_thresholds == ()
    assert is_attack_eligible(metadata, config) is False


def test_search_models_and_helpers_are_exported_from_automation_package() -> None:
    assert automation.AvailableLoot is AvailableLoot
    assert automation.read_opponent_base_metadata is read_opponent_base_metadata
    assert automation.evaluate_attack_eligibility is evaluate_attack_eligibility


def _frame() -> FrameImage:
    return make_frame(frame_id=None, width=160, height=90, rgba=(0, 0, 0, 255))


def _config(*, min_gold: int, min_elixir: int, min_dark_elixir: int) -> BottoConfig:
    return BottoConfig(
        attack=AttackConfig(
            strategy="mass-super-minion",
            resources=AttackResourcesConfig(
                min_gold=min_gold,
                min_elixir=min_elixir,
                min_dark_elixir=min_dark_elixir,
            ),
            search=AttackSearchConfig(max_searches=10),
            battle=AttackBattleConfig(resource_stall_seconds=20),
        )
    )


class FakeTextReader:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[ScreenRect | None] = []

    def __call__(self, image: FrameImage, *, region: ScreenRect | None = None) -> str:
        _ = image
        self.calls.append(region)
        return self._text
