"""Tests for required Botto config loading."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from botto.automation.config import BottoConfigError, load_botto_config


def test_load_botto_config_parses_attack_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "botto.toml"
    config_path.write_text(
        """
[attack]
strategy = "mass-super-minion"

[attack.resources]
min_gold = 100
min_elixir = 200
min_dark_elixir = 3

[attack.search]
max_searches = 7

[attack.battle]
resource_stall_seconds = 12.5
""".lstrip(),
        encoding="utf-8",
    )

    loaded = load_botto_config(config_path)

    assert loaded.path == config_path.resolve()
    assert loaded.config.attack.strategy == "mass-super-minion"
    assert loaded.config.attack.resources.min_gold == 100
    assert loaded.config.attack.resources.min_elixir == 200
    assert loaded.config.attack.resources.min_dark_elixir == 3
    assert loaded.config.attack.search.max_searches == 7
    assert loaded.config.attack.battle.resource_stall_seconds == 12.5
    assert loaded.config.effective_values() == {
        "attack.strategy": "mass-super-minion",
        "attack.resources.min_gold": 100,
        "attack.resources.min_elixir": 200,
        "attack.resources.min_dark_elixir": 3,
        "attack.search.max_searches": 7,
        "attack.battle.resource_stall_seconds": 12.5,
    }


@pytest.mark.parametrize(
    ("config_text", "expected_error"),
    [
        (
            """
[attack]
strategy = "../outside"

[attack.resources]
min_gold = 100
min_elixir = 200
min_dark_elixir = 3

[attack.search]
max_searches = 7

[attack.battle]
resource_stall_seconds = 12
""".lstrip(),
            "attack.strategy must contain only letters, numbers, '-' or '_', and must not be empty",
        ),
        (
            """
[attack.resources]
min_gold = 100
min_elixir = 200
min_dark_elixir = 3

[attack.search]
max_searches = 7

[attack.battle]
resource_stall_seconds = 12
""".lstrip(),
            "attack.strategy is required",
        ),
        (
            """
[attack]
strategy = "mass-super-minion"

[attack.resources]
min_gold = -1
min_elixir = 200
min_dark_elixir = 3

[attack.search]
max_searches = 7

[attack.battle]
resource_stall_seconds = 12
""".lstrip(),
            "attack.resources.min_gold must be >= 0",
        ),
        (
            """
[attack]
strategy = "mass-super-minion"

[attack.resources]
min_gold = 100
min_elixir = 200
min_dark_elixir = 3

[attack.search]
max_searches = 0

[attack.battle]
resource_stall_seconds = 12
""".lstrip(),
            "attack.search.max_searches must be > 0",
        ),
        (
            """
[attack]
strategy = "mass-super-minion"

[attack.resources]
min_gold = 100
min_elixir = 200
min_dark_elixir = 3

[attack.search]
max_searches = 7

[attack.battle]
resource_stall_seconds = 0
""".lstrip(),
            "attack.battle.resource_stall_seconds must be > 0",
        ),
        (
            """
[attack]
strategy = "mass-super-minion"

[attack.resources]
min_gold = 100
min_elixir = 200
min_dark_elixir = 3

[attack.battle]
resource_stall_seconds = 12
""".lstrip(),
            "[attack.search] is required",
        ),
    ],
)
def test_load_botto_config_rejects_invalid_values(
    tmp_path: Path,
    config_text: str,
    expected_error: str,
) -> None:
    config_path = tmp_path / "botto.toml"
    config_path.write_text(config_text, encoding="utf-8")

    with pytest.raises(BottoConfigError, match=re.escape(expected_error)):
        load_botto_config(config_path)


def test_load_botto_config_uses_current_directory_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "botto.toml").write_text(
        """
[attack]
strategy = "mass-super-minion"

[attack.resources]
min_gold = 1
min_elixir = 2
min_dark_elixir = 3

[attack.search]
max_searches = 4

[attack.battle]
resource_stall_seconds = 5
""".lstrip(),
        encoding="utf-8",
    )

    loaded = load_botto_config()

    assert loaded.path == (tmp_path / "botto.toml").resolve()
    assert loaded.config.attack.strategy == "mass-super-minion"
    assert loaded.config.attack.search.max_searches == 4


def test_load_botto_config_requires_existing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "botto.toml"

    with pytest.raises(BottoConfigError, match="Botto config not found"):
        load_botto_config(missing_path)
