"""Base screen and screen-element detection models."""

from __future__ import annotations

from enum import StrEnum


class BaseScreen(StrEnum):
    """High-level Clash screen states Botto can currently identify."""

    SUPERCELL_LOGO = "supercell_logo"
    LOADING = "loading"
    HOME_VILLAGE = "home_village"
    UNKNOWN = "unknown"


class HomeElement(StrEnum):
    """Home-village UI anchors Botto can currently identify."""

    ATTACK_BUTTON = "attack_button"
    SHOP_BUTTON = "shop_button"


class ScreenElement(StrEnum):
    """Base-screen anchors outside the home village."""

    LOADING_TEXT = "loading_text"
    SUPERCELL_LOGO = "supercell_logo"


__all__ = ["BaseScreen", "HomeElement", "ScreenElement"]
