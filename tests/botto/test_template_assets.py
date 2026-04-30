"""Validity checks for committed Botto template assets."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "botto" / "assets" / "templates"
TEMPLATE_NAMES = ("supercell_logo.png", "attack_button.png", "shop_button.png")


def test_template_assets_are_valid_pngs() -> None:
    for template_name in TEMPLATE_NAMES:
        template_path = TEMPLATE_DIR / template_name

        assert template_path.is_file()
        with Image.open(template_path) as image:
            assert image.format == "PNG"
            assert image.width > 0
            assert image.height > 0
            image.verify()
