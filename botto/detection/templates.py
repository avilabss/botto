"""Template metadata and scale helpers for Botto detection."""

from __future__ import annotations

import math
from pathlib import Path

from android_game_automator.types import Size

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "assets" / "templates"
SUPERCELL_LOGO_TEMPLATE = TEMPLATE_DIR / "screens" / "supercell" / "logo.png"
ATTACK_BUTTON_TEMPLATE = TEMPLATE_DIR / "screens" / "home" / "attack_button.png"
SHOP_BUTTON_TEMPLATE = TEMPLATE_DIR / "screens" / "home" / "shop_button.png"

HOME_TEMPLATE_REFERENCE_SIZE = Size(width=1080, height=504)
HOME_TEMPLATE_SCALE_MULTIPLIERS = (0.95, 1.0, 1.05)


def home_template_scales(frame_size: Size) -> tuple[float, ...]:
    """Return scale candidates for home-village templates at ``frame_size``."""

    width_scale = frame_size.width / HOME_TEMPLATE_REFERENCE_SIZE.width
    height_scale = frame_size.height / HOME_TEMPLATE_REFERENCE_SIZE.height
    expected_scale = (width_scale + height_scale) / 2.0

    scales: list[float] = []
    seen: set[float] = set()
    for multiplier in HOME_TEMPLATE_SCALE_MULTIPLIERS:
        scale = expected_scale * multiplier
        if not math.isfinite(scale) or scale <= 0.0 or scale in seen:
            continue
        seen.add(scale)
        scales.append(scale)

    return tuple(scales)


__all__ = [
    "ATTACK_BUTTON_TEMPLATE",
    "HOME_TEMPLATE_REFERENCE_SIZE",
    "HOME_TEMPLATE_SCALE_MULTIPLIERS",
    "SHOP_BUTTON_TEMPLATE",
    "SUPERCELL_LOGO_TEMPLATE",
    "TEMPLATE_DIR",
    "home_template_scales",
]
