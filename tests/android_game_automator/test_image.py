"""Tests for ROI-first image helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from android_game_automator.image import (
    FrameImage,
    get_color,
    intersect_regions,
    pixel_color_matches,
    probe_color,
    rect_to_normalized,
    resolve_point,
    resolve_region,
)
from android_game_automator.types import (
    NormalizedPoint,
    NormalizedRect,
    PixelFormat,
    Point,
    Rect,
    Size,
    Viewport,
)
from PIL import Image


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


def test_frame_image_model_has_value_semantics_and_validates_data_length() -> None:
    now = datetime.now(UTC)
    image = FrameImage(
        size=Size(width=1, height=1),
        pixel_format=PixelFormat.RGBA32,
        data=b"\x89PNG",
        captured_at=now,
        frame_id="frame-1",
    )

    assert image == FrameImage(
        size=Size(width=1, height=1),
        pixel_format=PixelFormat.RGBA32,
        data=b"\x89PNG",
        captured_at=now,
        frame_id="frame-1",
    )

    with pytest.raises(ValueError):
        FrameImage(size=Size(width=1, height=1), pixel_format=PixelFormat.RGBA32, data=b"")


def test_get_color_reads_absolute_points() -> None:
    image = _rgba_image()

    assert get_color(image, Point(x=1, y=0)) == (0, 255, 0, 255)


def test_get_color_reads_normalized_points_with_viewport() -> None:
    image = _rgba_image()
    viewport = Viewport(surface_size=image.size, region=Rect(left=1, top=1, width=1, height=1))

    assert get_color(image, NormalizedPoint(x=0.0, y=0.0), viewport=viewport) == (
        255,
        255,
        0,
        255,
    )


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
