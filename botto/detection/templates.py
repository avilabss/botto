"""Template metadata and scale helpers for Botto detection."""

from __future__ import annotations

import math
from pathlib import Path

from android_game_automator.types import Size

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "assets" / "templates"
_SCREEN_TEMPLATE_DIR = TEMPLATE_DIR / "screens"

SUPERCELL_LOGO_TEMPLATE = _SCREEN_TEMPLATE_DIR / "supercell" / "logo.png"
ATTACK_BUTTON_TEMPLATE = _SCREEN_TEMPLATE_DIR / "home" / "attack_button.png"
SHOP_BUTTON_TEMPLATE = _SCREEN_TEMPLATE_DIR / "home" / "shop_button.png"

ATTACK_MENU_MULTIPLAYER_TITLE_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "attack_menu" / "multiplayer_title.png"
)
ATTACK_MENU_FIND_A_MATCH_BUTTON_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "attack_menu" / "find_a_match_button.png"
)
MY_ARMY_TITLE_TEMPLATE = _SCREEN_TEMPLATE_DIR / "my_army" / "title.png"
MY_ARMY_ATTACK_BUTTON_TEMPLATE = _SCREEN_TEMPLATE_DIR / "my_army" / "attack_button.png"
BATTLE_PREPARATION_BATTLE_STARTS_IN_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "preparation" / "battle_starts_in.png"
)
BATTLE_PREPARATION_NEXT_BUTTON_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "preparation" / "next_button.png"
)
BATTLE_ACTIVE_END_BATTLE_BUTTON_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "active" / "end_battle_button.png"
)
BATTLE_ACTIVE_SURRENDER_BUTTON_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "active" / "surrender_button.png"
)
BATTLE_ACTIVE_OVERALL_DAMAGE_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "active" / "overall_damage.png"
)
BATTLE_DEPLOYMENT_SUPER_MINION_SLOT_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "deployment" / "super_minion_slot.png"
)
BATTLE_DEPLOYMENT_LIGHTNING_SPELL_SLOT_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "deployment" / "lightning_spell_slot.png"
)
BATTLE_DEPLOYMENT_BARBARIAN_KING_SLOT_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "deployment" / "barbarian_king_slot.png"
)
BATTLE_DEPLOYMENT_ARCHER_QUEEN_SLOT_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "deployment" / "archer_queen_slot.png"
)
BATTLE_DEPLOYMENT_GRAND_WARDEN_SLOT_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "deployment" / "grand_warden_slot.png"
)
BATTLE_DEPLOYMENT_ROYAL_CHAMPION_SLOT_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "deployment" / "royal_champion_slot.png"
)
BATTLE_DEPLOYMENT_RED_CC_SIEGE_SLOT_ASSUMED_CC_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "deployment" / "red_cc_siege_slot_assumed_cc.png"
)
BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "targets" / "air_defense_zoomed_back.png"
)
BATTLE_TARGET_AIR_DEFENSE_ZOOMED_IN_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "targets" / "air_defense_zoomed_in.png"
)
BATTLE_END_RETURN_HOME_BUTTON_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "end" / "return_home_button.png"
)
BATTLE_END_CLAIM_REWARD_BUTTON_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "end" / "claim_reward_button.png"
)
BATTLE_SURRENDER_OKAY_BUTTON_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "battle" / "surrender" / "okay_button.png"
)
REWARD_CHEST_CONTINUE_BUTTON_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "rewards" / "chest" / "continue_button.png"
)
REWARD_CHEST_CLOSED_CHEST_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "rewards" / "chest" / "closed_chest.png"
)
STAR_BONUS_OKAY_BUTTON_TEMPLATE = (
    _SCREEN_TEMPLATE_DIR / "rewards" / "star_bonus" / "okay_button.png"
)

HOME_TEMPLATE_REFERENCE_SIZE = Size(width=1080, height=504)
HOME_TEMPLATE_SCALE_MULTIPLIERS = (0.95, 1.0, 1.05)
ATTACK_FLOW_TEMPLATE_REFERENCE_SIZE = Size(width=1080, height=504)
ATTACK_FLOW_TEMPLATE_SCALE_MULTIPLIERS = (0.95, 1.0, 1.05)


def home_template_scales(frame_size: Size) -> tuple[float, ...]:
    """Return scale candidates for home-village templates at ``frame_size``."""

    return _template_scales(
        frame_size,
        reference_size=HOME_TEMPLATE_REFERENCE_SIZE,
        multipliers=HOME_TEMPLATE_SCALE_MULTIPLIERS,
    )


def attack_flow_template_scales(frame_size: Size) -> tuple[float, ...]:
    """Return scale candidates for attack-flow templates at ``frame_size``."""

    return _template_scales(
        frame_size,
        reference_size=ATTACK_FLOW_TEMPLATE_REFERENCE_SIZE,
        multipliers=ATTACK_FLOW_TEMPLATE_SCALE_MULTIPLIERS,
    )


def _template_scales(
    frame_size: Size,
    *,
    reference_size: Size,
    multipliers: tuple[float, ...],
) -> tuple[float, ...]:
    width_scale = frame_size.width / reference_size.width
    height_scale = frame_size.height / reference_size.height
    expected_scale = (width_scale + height_scale) / 2.0

    scales: list[float] = []
    seen: set[float] = set()
    for multiplier in multipliers:
        scale = expected_scale * multiplier
        if not math.isfinite(scale) or scale <= 0.0 or scale in seen:
            continue
        seen.add(scale)
        scales.append(scale)

    return tuple(scales)


__all__ = [
    "ATTACK_BUTTON_TEMPLATE",
    "ATTACK_FLOW_TEMPLATE_REFERENCE_SIZE",
    "ATTACK_FLOW_TEMPLATE_SCALE_MULTIPLIERS",
    "ATTACK_MENU_FIND_A_MATCH_BUTTON_TEMPLATE",
    "ATTACK_MENU_MULTIPLAYER_TITLE_TEMPLATE",
    "BATTLE_ACTIVE_END_BATTLE_BUTTON_TEMPLATE",
    "BATTLE_ACTIVE_OVERALL_DAMAGE_TEMPLATE",
    "BATTLE_ACTIVE_SURRENDER_BUTTON_TEMPLATE",
    "BATTLE_DEPLOYMENT_ARCHER_QUEEN_SLOT_TEMPLATE",
    "BATTLE_DEPLOYMENT_BARBARIAN_KING_SLOT_TEMPLATE",
    "BATTLE_DEPLOYMENT_GRAND_WARDEN_SLOT_TEMPLATE",
    "BATTLE_DEPLOYMENT_LIGHTNING_SPELL_SLOT_TEMPLATE",
    "BATTLE_DEPLOYMENT_RED_CC_SIEGE_SLOT_ASSUMED_CC_TEMPLATE",
    "BATTLE_DEPLOYMENT_ROYAL_CHAMPION_SLOT_TEMPLATE",
    "BATTLE_DEPLOYMENT_SUPER_MINION_SLOT_TEMPLATE",
    "BATTLE_END_CLAIM_REWARD_BUTTON_TEMPLATE",
    "BATTLE_END_RETURN_HOME_BUTTON_TEMPLATE",
    "BATTLE_PREPARATION_BATTLE_STARTS_IN_TEMPLATE",
    "BATTLE_PREPARATION_NEXT_BUTTON_TEMPLATE",
    "BATTLE_SURRENDER_OKAY_BUTTON_TEMPLATE",
    "BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE",
    "BATTLE_TARGET_AIR_DEFENSE_ZOOMED_IN_TEMPLATE",
    "HOME_TEMPLATE_REFERENCE_SIZE",
    "HOME_TEMPLATE_SCALE_MULTIPLIERS",
    "MY_ARMY_ATTACK_BUTTON_TEMPLATE",
    "MY_ARMY_TITLE_TEMPLATE",
    "REWARD_CHEST_CLOSED_CHEST_TEMPLATE",
    "REWARD_CHEST_CONTINUE_BUTTON_TEMPLATE",
    "SHOP_BUTTON_TEMPLATE",
    "STAR_BONUS_OKAY_BUTTON_TEMPLATE",
    "SUPERCELL_LOGO_TEMPLATE",
    "TEMPLATE_DIR",
    "attack_flow_template_scales",
    "home_template_scales",
]
