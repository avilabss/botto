"""Tests for OpenCV-backed vision matching helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from android_game_automator.image import FrameImage
from android_game_automator.types import Match, PixelFormat, Point, Rect, Size
from android_game_automator.vision import FeatureMatch, find_feature_match, find_template
from PIL import Image, ImageDraw


def test_find_template_uses_full_frame_by_default_and_respects_roi() -> None:
    image = _template_scene_image(scale=2)

    match = find_template(
        image,
        _template_image(),
        min_confidence=0.99,
        scales=(1.0, 2.0),
    )

    assert isinstance(match, Match)
    assert match.bounds == Rect(left=1, top=1, width=4, height=4)
    assert match.center == Point(x=3, y=3)
    assert match.confidence == pytest.approx(1.0)
    assert match.scale == pytest.approx(2.0)
    assert match.rotation == pytest.approx(0.0)
    assert (
        find_template(
            image,
            _template_image(),
            region=Rect(left=0, top=0, width=1, height=1),
            min_confidence=0.99,
            scales=(1.0, 2.0),
        )
        is None
    )


def test_find_template_supports_rotated_matches() -> None:
    match = find_template(
        _rotated_template_scene_image(rotation=90),
        _asymmetric_template_image(),
        min_confidence=0.99,
        rotations=(0.0, 90.0),
    )

    assert isinstance(match, Match)
    assert match.bounds == Rect(left=2, top=1, width=3, height=2)
    assert match.center == Point(x=3, y=2)
    assert match.confidence == pytest.approx(1.0)
    assert match.scale == pytest.approx(1.0)
    assert match.rotation == pytest.approx(90.0)


def test_find_template_supports_frame_image_pil_path_and_threshold_alias(tmp_path) -> None:  # noqa: ANN001
    image = _template_scene_image(scale=1, altered=True)
    source_pil = image.to_pil_image()
    template_pil = _template_image().to_pil_image()
    source_path = tmp_path / "scene.png"
    template_path = tmp_path / "badge.png"

    try:
        assert find_template(source_pil, template_pil, min_confidence=0.95) is None

        source_pil.save(source_path)
        template_pil.save(template_path)
        match = find_template(source_path, template_path, threshold=0.4)
    finally:
        source_pil.close()
        template_pil.close()

    assert isinstance(match, Match)
    assert match.bounds == Rect(left=1, top=1, width=2, height=2)
    assert match.confidence >= 0.4


def test_find_template_ignores_transparent_template_padding() -> None:
    image, template = _transparent_padded_template_scene()

    match = find_template(image, template, min_confidence=0.99)

    assert isinstance(match, Match)
    assert match.bounds == Rect(left=2, top=2, width=4, height=4)
    assert match.confidence == pytest.approx(1.0)


def test_find_template_rejects_fully_transparent_template() -> None:
    image = _template_scene_image(scale=1)
    template = Image.new("RGBA", (4, 4), (0, 0, 0, 0))

    with pytest.raises(ValueError, match="alpha mask"):
        find_template(image, template)


def test_find_template_preserves_non_alpha_template_matching() -> None:
    image, transparent_template = _transparent_padded_template_scene()
    rgb_template = transparent_template.convert("RGB")

    try:
        assert find_template(image, rgb_template, min_confidence=0.99) is None
    finally:
        rgb_template.close()


def test_find_feature_match_uses_orb_and_respects_roi() -> None:
    image, template = _feature_scene_image()

    match = find_feature_match(image, template, min_matches=8, min_confidence=0.25)

    assert isinstance(match, FeatureMatch)
    assert match.match_count >= 8
    assert match.confidence >= 0.25
    assert match.bounds.left == pytest.approx(70, abs=4)
    assert match.bounds.top == pytest.approx(55, abs=4)
    assert match.bounds.width == pytest.approx(120, abs=8)
    assert match.bounds.height == pytest.approx(90, abs=8)
    assert match.center.x == pytest.approx(130, abs=6)
    assert match.center.y == pytest.approx(100, abs=6)

    roi_match = find_feature_match(
        image,
        template,
        region=Rect(left=60, top=45, width=150, height=120),
        min_matches=8,
        min_confidence=0.25,
    )
    assert isinstance(roi_match, FeatureMatch)
    assert (
        find_feature_match(
            image,
            template,
            region=Rect(left=0, top=0, width=40, height=40),
            min_matches=8,
            min_confidence=0.25,
        )
        is None
    )


def test_find_feature_match_uses_alpha_mask_for_padded_template() -> None:
    image, template = _transparent_padded_feature_scene()

    match = find_feature_match(image, template, min_matches=8, min_confidence=0.20)

    assert isinstance(match, FeatureMatch)
    assert match.match_count >= 8
    assert match.center.x == pytest.approx(150, abs=8)
    assert match.center.y == pytest.approx(115, abs=8)


def test_find_feature_match_returns_none_for_fully_transparent_template() -> None:
    image, _ = _feature_scene_image()
    template = Image.new("RGBA", (80, 80), (0, 0, 0, 0))

    assert find_feature_match(image, template, min_matches=4, min_confidence=0.0) is None


def test_find_template_validates_threshold_scales_and_rotations() -> None:
    image = _template_scene_image(scale=1)
    template = _template_image()

    with pytest.raises(ValueError, match="min_confidence"):
        find_template(image, template, min_confidence=1.1)

    with pytest.raises(ValueError, match="scales"):
        find_template(image, template, scales=(0.0,))

    with pytest.raises(ValueError, match="rotations"):
        find_template(image, template, rotations=(float("nan"),))

    with pytest.raises(ValueError, match="min_matches"):
        find_feature_match(image, template, min_matches=3)

    with pytest.raises(ValueError, match="min_confidence"):
        find_feature_match(image, template, min_confidence=1.1)

    with pytest.raises(ValueError, match="alpha_threshold"):
        find_template(image, template, alpha_threshold=256)

    with pytest.raises(ValueError, match="alpha_threshold"):
        find_feature_match(image, template, alpha_threshold=-1)


def _template_image() -> FrameImage:
    image = Image.new("RGBA", (2, 2), (20, 20, 20, 255))
    image.putpixel((0, 0), (255, 255, 255, 255))
    image.putpixel((1, 1), (255, 255, 255, 255))
    return FrameImage.from_pil_image(image)


def _asymmetric_template_image() -> FrameImage:
    image = Image.new("RGBA", (2, 3), (20, 20, 20, 255))
    image.putpixel((0, 0), (240, 240, 240, 255))
    image.putpixel((1, 0), (40, 40, 40, 255))
    image.putpixel((0, 1), (80, 80, 80, 255))
    image.putpixel((1, 1), (160, 160, 160, 255))
    image.putpixel((0, 2), (200, 200, 200, 255))
    image.putpixel((1, 2), (120, 120, 120, 255))
    return FrameImage.from_pil_image(image)


def _template_scene_image(*, scale: int, altered: bool = False) -> FrameImage:
    template = _template_image().to_pil_image()
    scaled = template.resize(
        (template.width * scale, template.height * scale),
        Image.Resampling.NEAREST,
    )
    scene = Image.new("RGBA", (5, 5), (20, 20, 20, 255))
    scene.paste(scaled, (1, 1))
    if altered:
        scene.putpixel((1, 1), (20, 20, 20, 255))

    return FrameImage(
        size=Size(width=scene.width, height=scene.height),
        pixel_format=PixelFormat.RGBA32,
        data=scene.tobytes(),
        captured_at=datetime.now(UTC),
    )


def _transparent_padded_template_scene() -> tuple[FrameImage, Image.Image]:
    visible = Image.new("RGBA", (2, 2), (0, 0, 0, 255))
    visible.putpixel((0, 0), (240, 240, 240, 255))
    visible.putpixel((1, 0), (30, 30, 30, 255))
    visible.putpixel((0, 1), (90, 90, 90, 255))
    visible.putpixel((1, 1), (180, 180, 180, 255))

    scene = Image.new("RGBA", (8, 8), (40, 40, 40, 255))
    scene.paste(visible, (3, 3))

    template = Image.new("RGBA", (4, 4), (255, 255, 255, 0))
    template.paste(visible, (1, 1))
    return FrameImage.from_pil_image(scene), template


def _rotated_template_scene_image(*, rotation: float) -> FrameImage:
    template = _asymmetric_template_image().to_pil_image()
    rotated = template.rotate(rotation, expand=True, resample=Image.Resampling.NEAREST)
    scene = Image.new("RGBA", (6, 6), (20, 20, 20, 255))
    scene.paste(rotated, (2, 1))

    return FrameImage(
        size=Size(width=scene.width, height=scene.height),
        pixel_format=PixelFormat.RGBA32,
        data=scene.tobytes(),
        captured_at=datetime.now(UTC),
    )


def _feature_scene_image() -> tuple[FrameImage, FrameImage]:
    template = _feature_template_image()
    scene = Image.new("RGBA", (260, 220), (80, 80, 80, 255))
    scene.paste(template, (70, 55))

    return (
        FrameImage(
            size=Size(width=scene.width, height=scene.height),
            pixel_format=PixelFormat.RGBA32,
            data=scene.tobytes(),
            captured_at=datetime.now(UTC),
        ),
        FrameImage(
            size=Size(width=template.width, height=template.height),
            pixel_format=PixelFormat.RGBA32,
            data=template.tobytes(),
            captured_at=datetime.now(UTC),
        ),
    )


def _transparent_padded_feature_scene() -> tuple[FrameImage, FrameImage]:
    visible = _feature_template_image()
    scene = Image.new("RGBA", (300, 260), (80, 80, 80, 255))
    scene.paste(visible, (90, 70))

    template = Image.new("RGBA", (160, 130), (255, 0, 255, 0))
    template.paste(visible, (20, 20))

    return FrameImage.from_pil_image(scene), FrameImage.from_pil_image(template)


def _feature_template_image() -> Image.Image:
    image = Image.new("RGBA", (120, 90), (240, 240, 240, 255))
    draw = ImageDraw.Draw(image)
    for x in range(10, 110, 20):
        draw.line((x, 5, 120 - x, 85), fill=(0, 0, 0, 255), width=3)
    for y in range(10, 90, 20):
        draw.ellipse((5, y, 17, y + 12), fill=(255, 0, 0, 255))
        draw.rectangle((95, y, 110, y + 10), fill=(0, 0, 255, 255))
    draw.polygon(
        [(60, 10), (80, 40), (50, 60), (35, 30)],
        outline=(0, 128, 0, 255),
        width=3,
    )
    for x, y in ((30, 20), (70, 70), (15, 70), (100, 20), (60, 45)):
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(0, 0, 0, 255))
    return image
