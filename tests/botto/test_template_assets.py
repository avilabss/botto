"""Validity checks for committed Botto template assets."""

from __future__ import annotations

from botto.detection.templates import (
    ATTACK_BUTTON_TEMPLATE,
    SHOP_BUTTON_TEMPLATE,
    SUPERCELL_LOGO_TEMPLATE,
    TEMPLATE_DIR,
)
from PIL import Image

TEMPLATE_PATHS = (SUPERCELL_LOGO_TEMPLATE, ATTACK_BUTTON_TEMPLATE, SHOP_BUTTON_TEMPLATE)
TEMPLATE_RELATIVE_PATHS = (
    "screens/supercell/logo.png",
    "screens/home/attack_button.png",
    "screens/home/shop_button.png",
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
