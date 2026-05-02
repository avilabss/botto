"""Validity checks for committed Botto template assets."""

from __future__ import annotations

from botto.detection.templates import (
    ATTACK_BUTTON_TEMPLATE,
    ATTACK_MENU_FIND_A_MATCH_BUTTON_TEMPLATE,
    ATTACK_MENU_MULTIPLAYER_TITLE_TEMPLATE,
    BATTLE_ACTIVE_END_BATTLE_BUTTON_TEMPLATE,
    BATTLE_ACTIVE_OVERALL_DAMAGE_TEMPLATE,
    BATTLE_ACTIVE_SURRENDER_BUTTON_TEMPLATE,
    BATTLE_DEPLOYMENT_ARCHER_QUEEN_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_BARBARIAN_KING_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_GRAND_WARDEN_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_LIGHTNING_SPELL_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_RED_CC_SIEGE_SLOT_ASSUMED_CC_TEMPLATE,
    BATTLE_DEPLOYMENT_ROYAL_CHAMPION_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_SUPER_MINION_SLOT_TEMPLATE,
    BATTLE_END_CLAIM_REWARD_BUTTON_TEMPLATE,
    BATTLE_END_RETURN_HOME_BUTTON_TEMPLATE,
    BATTLE_PREPARATION_BATTLE_STARTS_IN_TEMPLATE,
    BATTLE_PREPARATION_NEXT_BUTTON_TEMPLATE,
    BATTLE_SURRENDER_OKAY_BUTTON_TEMPLATE,
    BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE,
    BATTLE_TARGET_AIR_DEFENSE_ZOOMED_IN_TEMPLATE,
    MY_ARMY_ATTACK_BUTTON_TEMPLATE,
    MY_ARMY_TITLE_TEMPLATE,
    REWARD_CHEST_CLOSED_CHEST_TEMPLATE,
    REWARD_CHEST_CONTINUE_BUTTON_TEMPLATE,
    SHOP_BUTTON_TEMPLATE,
    STAR_BONUS_OKAY_BUTTON_TEMPLATE,
    SUPERCELL_LOGO_TEMPLATE,
    TEMPLATE_DIR,
)
from PIL import Image

TEMPLATE_PATHS = (
    SUPERCELL_LOGO_TEMPLATE,
    ATTACK_BUTTON_TEMPLATE,
    SHOP_BUTTON_TEMPLATE,
    ATTACK_MENU_MULTIPLAYER_TITLE_TEMPLATE,
    ATTACK_MENU_FIND_A_MATCH_BUTTON_TEMPLATE,
    MY_ARMY_TITLE_TEMPLATE,
    MY_ARMY_ATTACK_BUTTON_TEMPLATE,
    BATTLE_PREPARATION_BATTLE_STARTS_IN_TEMPLATE,
    BATTLE_PREPARATION_NEXT_BUTTON_TEMPLATE,
    BATTLE_ACTIVE_END_BATTLE_BUTTON_TEMPLATE,
    BATTLE_ACTIVE_SURRENDER_BUTTON_TEMPLATE,
    BATTLE_ACTIVE_OVERALL_DAMAGE_TEMPLATE,
    BATTLE_DEPLOYMENT_SUPER_MINION_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_LIGHTNING_SPELL_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_BARBARIAN_KING_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_ARCHER_QUEEN_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_GRAND_WARDEN_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_ROYAL_CHAMPION_SLOT_TEMPLATE,
    BATTLE_DEPLOYMENT_RED_CC_SIEGE_SLOT_ASSUMED_CC_TEMPLATE,
    BATTLE_TARGET_AIR_DEFENSE_ZOOMED_BACK_TEMPLATE,
    BATTLE_TARGET_AIR_DEFENSE_ZOOMED_IN_TEMPLATE,
    BATTLE_END_RETURN_HOME_BUTTON_TEMPLATE,
    BATTLE_END_CLAIM_REWARD_BUTTON_TEMPLATE,
    BATTLE_SURRENDER_OKAY_BUTTON_TEMPLATE,
    REWARD_CHEST_CLOSED_CHEST_TEMPLATE,
    REWARD_CHEST_CONTINUE_BUTTON_TEMPLATE,
    STAR_BONUS_OKAY_BUTTON_TEMPLATE,
)
TEMPLATE_RELATIVE_PATHS = (
    "screens/supercell/logo.png",
    "screens/home/attack_button.png",
    "screens/home/shop_button.png",
    "screens/attack_menu/multiplayer_title.png",
    "screens/attack_menu/find_a_match_button.png",
    "screens/my_army/title.png",
    "screens/my_army/attack_button.png",
    "screens/battle/preparation/battle_starts_in.png",
    "screens/battle/preparation/next_button.png",
    "screens/battle/active/end_battle_button.png",
    "screens/battle/active/surrender_button.png",
    "screens/battle/active/overall_damage.png",
    "screens/battle/deployment/super_minion_slot.png",
    "screens/battle/deployment/lightning_spell_slot.png",
    "screens/battle/deployment/barbarian_king_slot.png",
    "screens/battle/deployment/archer_queen_slot.png",
    "screens/battle/deployment/grand_warden_slot.png",
    "screens/battle/deployment/royal_champion_slot.png",
    "screens/battle/deployment/red_cc_siege_slot_assumed_cc.png",
    "screens/battle/targets/air_defense_zoomed_back.png",
    "screens/battle/targets/air_defense_zoomed_in.png",
    "screens/battle/end/return_home_button.png",
    "screens/battle/end/claim_reward_button.png",
    "screens/battle/surrender/okay_button.png",
    "screens/rewards/chest/closed_chest.png",
    "screens/rewards/chest/continue_button.png",
    "screens/rewards/star_bonus/okay_button.png",
)


def test_template_paths_are_categorized() -> None:
    categorized_paths = tuple(path.relative_to(TEMPLATE_DIR).as_posix() for path in TEMPLATE_PATHS)

    assert categorized_paths == TEMPLATE_RELATIVE_PATHS


def test_template_assets_are_valid_pngs() -> None:
    for template_path in TEMPLATE_PATHS:
        assert template_path.is_file()
        with Image.open(template_path) as image:
            assert image.format == "PNG"
            assert image.width > 0
            assert image.height > 0
            image.verify()
