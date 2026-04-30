"""Tests for the lightweight ROI-first vision foundation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from android_game_automator.image import (
    FrameImage,
    intersect_regions,
    pixel_color_matches,
    probe_color,
    rect_to_normalized,
    resolve_point,
    resolve_region,
)
from android_game_automator.types import (
    Match,
    NormalizedPoint,
    NormalizedRect,
    PixelFormat,
    Point,
    Rect,
    Size,
    Viewport,
)
from PIL import Image

from android_game_automator.vision import find_template


def test_frame_image_exposes_pixel_array() -> None:
    image = _rgba_image()

    assert image.width == 2
    assert image.height == 2
    assert image.pixel(Point(x=1, y=0)) == (0, 255, 0, 255)
    assert image.to_array() == (
        ((255, 0, 0, 255), (0, 255, 0, 255)),
        ((0, 0, 255, 255), (255, 255, 0, 255)),
    )


def test_frame_image_save_persists_png(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "screenshot.png"

    _rgba_image().save(path)

    with Image.open(path) as image:
        assert image.mode == "RGBA"
        assert image.size == (2, 2)
        assert image.getpixel((0, 0)) == (255, 0, 0, 255)


def test_resolve_region_and_crop_support_normalized_and_absolute_rois() -> None:
    image = _rgba_image()
    viewport = Viewport(surface_size=image.size, region=Rect(left=0, top=0, width=2, height=2))

    assert resolve_region(
        NormalizedRect(left=0.5, top=0.0, width=0.5, height=0.5),
        viewport,
    ) == Rect(
        left=1,
        top=0,
        width=1,
        height=1,
    )
    assert image.crop(Rect(left=0, top=1, width=2, height=1)).to_array() == (
        ((0, 0, 255, 255), (255, 255, 0, 255)),
    )

    with pytest.raises(ValueError):
        resolve_region(Rect(left=2, top=0, width=1, height=1), viewport)


def test_point_probe_and_color_matching_support_tolerance() -> None:
    image = _rgba_image()

    assert resolve_point(
        NormalizedPoint(x=1.0, y=1.0),
        Viewport(surface_size=image.size),
    ) == Point(x=1, y=1)
    assert probe_color(image, Point(x=0, y=0), (254, 1, 0, 255), tolerance=1)
    assert not probe_color(image, Point(x=0, y=0), (250, 0, 0, 255), tolerance=1)
    assert pixel_color_matches((10, 20, 30), (12, 18, 31), tolerance=2)

    with pytest.raises(ValueError):
        pixel_color_matches((1, 2, 3), (1, 2), tolerance=0)


def test_rect_to_normalized_round_trips_edge_aligned_rects() -> None:
    size = Size(width=3, height=3)
    rect = Rect(left=1, top=1, width=2, height=2)
    normalized = rect_to_normalized(rect, size)

    assert normalized.left == pytest.approx(1 / 3)
    assert normalized.top == pytest.approx(1 / 3)
    assert normalized.right == pytest.approx(1.0)
    assert normalized.bottom == pytest.approx(1.0)
    assert Viewport(surface_size=size).map_rect(normalized) == rect


def test_intersect_regions_excludes_non_overlapping_regions() -> None:
    assert (
        intersect_regions(
            Rect(left=0, top=0, width=1, height=1),
            Rect(left=1, top=1, width=1, height=1),
        )
        is None
    )


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


def test_find_template_validates_threshold_scales_and_rotations() -> None:
    image = _template_scene_image(scale=1)
    template = _template_image()

    with pytest.raises(ValueError, match="min_confidence"):
        find_template(image, template, min_confidence=1.1)

    with pytest.raises(ValueError, match="scales"):
        find_template(image, template, scales=(0.0,))

    with pytest.raises(ValueError, match="rotations"):
        find_template(image, template, rotations=(float("nan"),))


def _rgba_image(*, frame_id: str | None = None) -> FrameImage:
    return FrameImage(
        size=Size(width=2, height=2),
        pixel_format=PixelFormat.RGBA32,
        data=bytes(
            [
                255,
                0,
                0,
                255,
                0,
                255,
                0,
                255,
                0,
                0,
                255,
                255,
                255,
                255,
                0,
                255,
            ]
        ),
        captured_at=datetime.now(UTC),
        frame_id=frame_id,
    )


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
