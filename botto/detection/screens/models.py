"""Base screen and screen-element detection models."""

from __future__ import annotations

from enum import StrEnum


class BaseScreen(StrEnum):
    """High-level Clash screen states Botto can currently identify."""

    SUPERCELL_LOGO = "supercell_logo"
    LOADING = "loading"
    HOME_VILLAGE = "home_village"
    ATTACK_MENU = "attack_menu"
    MY_ARMY = "my_army"
    BATTLE_PREPARATION = "battle_preparation"
    BATTLE_IN_PROGRESS = "battle_in_progress"
    BATTLE_SURRENDER_CONFIRMATION = "battle_surrender_confirmation"
    BATTLE_RESULT = "battle_result"
    REWARD_CHEST = "reward_chest"
    STAR_BONUS = "star_bonus"
    UNKNOWN = "unknown"


class HomeElement(StrEnum):
    """Home-village UI anchors Botto can currently identify."""

    ATTACK_BUTTON = "attack_button"
    SHOP_BUTTON = "shop_button"


class ScreenElement(StrEnum):
    """Base-screen anchors outside the home village."""

    LOADING_TEXT = "loading_text"
    SUPERCELL_LOGO = "supercell_logo"
    ATTACK_MENU_MULTIPLAYER_TITLE = "attack_menu_multiplayer_title"
    ATTACK_MENU_FIND_A_MATCH_BUTTON = "attack_menu_find_a_match_button"
    MY_ARMY_TITLE = "my_army_title"
    MY_ARMY_ATTACK_BUTTON = "my_army_attack_button"
    BATTLE_STARTS_IN_TEXT = "battle_starts_in_text"
    BATTLE_NEXT_BUTTON = "battle_next_button"
    BATTLE_ENDS_IN_TEXT = "battle_ends_in_text"
    BATTLE_END_BATTLE_BUTTON = "battle_end_battle_button"
    BATTLE_SURRENDER_BUTTON = "battle_surrender_button"
    BATTLE_OVERALL_DAMAGE = "battle_overall_damage"
    BATTLE_RETURN_HOME_BUTTON = "battle_return_home_button"
    BATTLE_CLAIM_REWARD_BUTTON = "battle_claim_reward_button"
    BATTLE_SURRENDER_OKAY_BUTTON = "battle_surrender_okay_button"
    REWARD_CHEST_OPEN_CHEST = "reward_chest_open_chest"
    REWARD_CHEST_CONTINUE_BUTTON = "reward_chest_continue_button"
    STAR_BONUS_TITLE = "star_bonus_title"
    STAR_BONUS_OKAY_BUTTON = "star_bonus_okay_button"


__all__ = ["BaseScreen", "HomeElement", "ScreenElement"]
