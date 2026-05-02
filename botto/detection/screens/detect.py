"""Known base-screen detection orchestration."""

from __future__ import annotations

from android_game_automator.image import FrameImage

from ..common import BaseScreenDetection, TemplateMatcher, TextReader
from ..evidence import Evidence
from .attack_menu import detect_attack_menu
from .battle_active import detect_battle_in_progress
from .battle_preparation import detect_battle_preparation
from .battle_result import detect_battle_result
from .battle_surrender import detect_battle_surrender_confirmation
from .home import detect_home_village
from .loading import detect_loading_screen
from .models import BaseScreen
from .my_army import detect_my_army
from .reward_chest import detect_reward_chest
from .star_bonus import detect_star_bonus
from .supercell import detect_supercell_logo


def detect_base_screen(
    image: FrameImage,
    *,
    read_text_fn: TextReader,
    find_template_fn: TemplateMatcher,
) -> BaseScreenDetection:
    """Detect base screens in priority order."""

    supercell_evidence = detect_supercell_logo(image, find_template_fn=find_template_fn)
    if supercell_evidence is not None:
        return BaseScreen.SUPERCELL_LOGO, supercell_evidence.confidence, (supercell_evidence,)

    star_bonus_evidence = detect_star_bonus(
        image,
        read_text_fn=read_text_fn,
        find_template_fn=find_template_fn,
    )
    if star_bonus_evidence:
        return _classification(BaseScreen.STAR_BONUS, star_bonus_evidence)

    my_army_evidence = detect_my_army(image, find_template_fn=find_template_fn)
    if len(my_army_evidence) >= 2:
        return _classification(BaseScreen.MY_ARMY, my_army_evidence)

    attack_menu_evidence = detect_attack_menu(image, find_template_fn=find_template_fn)
    if len(attack_menu_evidence) >= 2:
        return _classification(BaseScreen.ATTACK_MENU, attack_menu_evidence)

    home_evidence = detect_home_village(image, find_template_fn=find_template_fn)
    if len(home_evidence) >= 2:
        return _classification(BaseScreen.HOME_VILLAGE, home_evidence)

    loading_evidence = detect_loading_screen(image, read_text_fn=read_text_fn)
    if loading_evidence is not None:
        return BaseScreen.LOADING, loading_evidence.confidence, (loading_evidence,)

    battle_result_evidence = detect_battle_result(image, find_template_fn=find_template_fn)
    if battle_result_evidence:
        return _classification(BaseScreen.BATTLE_RESULT, battle_result_evidence)

    reward_chest_evidence = detect_reward_chest(image, find_template_fn=find_template_fn)
    if reward_chest_evidence:
        return _classification(BaseScreen.REWARD_CHEST, reward_chest_evidence)

    battle_surrender_evidence = detect_battle_surrender_confirmation(
        image,
        find_template_fn=find_template_fn,
    )
    if battle_surrender_evidence:
        return _classification(
            BaseScreen.BATTLE_SURRENDER_CONFIRMATION,
            battle_surrender_evidence,
        )

    battle_preparation_evidence = detect_battle_preparation(
        image,
        find_template_fn=find_template_fn,
    )
    if battle_preparation_evidence:
        return _classification(BaseScreen.BATTLE_PREPARATION, battle_preparation_evidence)

    battle_active_evidence = detect_battle_in_progress(
        image,
        read_text_fn=read_text_fn,
        find_template_fn=find_template_fn,
    )
    if battle_active_evidence:
        return _classification(BaseScreen.BATTLE_IN_PROGRESS, battle_active_evidence)

    return BaseScreen.UNKNOWN, 0.0, home_evidence


def _classification(screen: BaseScreen, evidence: tuple[Evidence, ...]) -> BaseScreenDetection:
    confidence = sum(item.confidence for item in evidence) / len(evidence)
    return screen, confidence, evidence


__all__ = ["detect_base_screen"]
