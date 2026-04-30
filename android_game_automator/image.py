"""ROI-first image helpers for screenshot data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from os import PathLike
from typing import cast

from PIL import Image

from android_game_automator.types import (
    NormalizedPoint,
    NormalizedRect,
    PixelFormat,
    Point,
    Rect,
    ScreenPoint,
    ScreenRect,
    Size,
    Viewport,
)

Color = tuple[int, ...]

_CHANNELS_BY_PIXEL_FORMAT = {
    PixelFormat.RGB24: 3,
    PixelFormat.RGBA32: 4,
    PixelFormat.BGR24: 3,
    PixelFormat.BGRA32: 4,
    PixelFormat.GRAY8: 1,
}


@dataclass(frozen=True, slots=True)
class FrameImage:
    """Row-major in-memory image view backed by frame bytes."""

    size: Size
    pixel_format: PixelFormat
    data: bytes
    captured_at: datetime | None = None
    frame_id: str | None = None

    def __post_init__(self) -> None:
        expected_length = self.size.width * self.size.height * self.channels
        if len(self.data) != expected_length:
            raise ValueError(
                f"data length {len(self.data)} does not match expected image size {expected_length}"
            )
        if self.frame_id is not None and not self.frame_id.strip():
            raise ValueError("frame_id must be non-empty when provided")

    @property
    def width(self) -> int:
        return self.size.width

    @property
    def height(self) -> int:
        return self.size.height

    @property
    def channels(self) -> int:
        return _channel_count(self.pixel_format)

    @property
    def stride(self) -> int:
        return self.width * self.channels

    @classmethod
    def from_pil_image(
        cls,
        image: Image.Image,
        *,
        captured_at: datetime | None = None,
        frame_id: str | None = None,
    ) -> FrameImage:
        if image.mode == "L":
            return cls(
                size=Size(width=image.width, height=image.height),
                pixel_format=PixelFormat.GRAY8,
                data=image.tobytes(),
                captured_at=captured_at,
                frame_id=frame_id,
            )
        return cls(
            size=Size(width=image.width, height=image.height),
            pixel_format=PixelFormat.RGBA32,
            data=_converted_image_bytes(image, "RGBA"),
            captured_at=captured_at,
            frame_id=frame_id,
        )

    def crop(self, region: ScreenRect, *, viewport: Viewport | None = None) -> FrameImage:
        resolved_region = resolve_region(region, viewport or Viewport(surface_size=self.size))
        source = self.to_pil_image()
        try:
            cropped = source.crop(
                (
                    resolved_region.left,
                    resolved_region.top,
                    resolved_region.right,
                    resolved_region.bottom,
                )
            )
            try:
                return _frame_image_from_pil_image(
                    cropped,
                    self.pixel_format,
                    captured_at=self.captured_at,
                    frame_id=self.frame_id,
                )
            finally:
                cropped.close()
        finally:
            source.close()

    def pixel(self, point: ScreenPoint, *, viewport: Viewport | None = None) -> Color:
        resolved_point = resolve_point(point, viewport or Viewport(surface_size=self.size))
        index = (resolved_point.y * self.width + resolved_point.x) * self.channels
        return tuple(self.data[index : index + self.channels])

    def to_array(self) -> tuple[tuple[Color, ...], ...]:
        rows: list[tuple[Color, ...]] = []
        for y in range(self.height):
            row: list[Color] = []
            row_offset = y * self.stride
            for x in range(self.width):
                pixel_offset = row_offset + (x * self.channels)
                row.append(tuple(self.data[pixel_offset : pixel_offset + self.channels]))
            rows.append(tuple(row))
        return tuple(rows)

    def to_pil_image(self) -> Image.Image:
        return _frame_image_to_pil_image(self)

    def save(self, path: str | PathLike[str]) -> None:
        image = self.to_pil_image()
        try:
            image.save(path)
        finally:
            image.close()

    def to_grayscale_array(self) -> tuple[tuple[int, ...], ...]:
        grayscale = self.to_pil_image().convert("L")
        rows: list[tuple[int, ...]] = []
        for y in range(grayscale.height):
            row: list[int] = []
            for x in range(grayscale.width):
                row.append(cast(int, grayscale.getpixel((x, y))))
            rows.append(tuple(row))
        return tuple(rows)


def _channel_count(pixel_format: PixelFormat) -> int:
    return _CHANNELS_BY_PIXEL_FORMAT[pixel_format]


def _frame_image_to_pil_image(image: FrameImage) -> Image.Image:
    size = (image.width, image.height)
    if image.pixel_format is PixelFormat.RGB24:
        return Image.frombytes("RGB", size, image.data)
    if image.pixel_format is PixelFormat.RGBA32:
        return Image.frombytes("RGBA", size, image.data)
    if image.pixel_format is PixelFormat.BGR24:
        return Image.frombytes("RGB", size, image.data, "raw", "BGR")
    if image.pixel_format is PixelFormat.BGRA32:
        return Image.frombytes("RGBA", size, image.data, "raw", "BGRA")
    return Image.frombytes("L", size, image.data)


def _frame_image_from_pil_image(
    image: Image.Image,
    pixel_format: PixelFormat,
    *,
    captured_at: datetime | None,
    frame_id: str | None,
) -> FrameImage:
    return FrameImage(
        size=Size(width=image.width, height=image.height),
        pixel_format=pixel_format,
        data=_pil_image_bytes_for_pixel_format(image, pixel_format),
        captured_at=captured_at,
        frame_id=frame_id,
    )


def _pil_image_bytes_for_pixel_format(image: Image.Image, pixel_format: PixelFormat) -> bytes:
    if pixel_format is PixelFormat.RGB24:
        return _converted_image_bytes(image, "RGB")
    if pixel_format is PixelFormat.RGBA32:
        return _converted_image_bytes(image, "RGBA")
    if pixel_format is PixelFormat.BGR24:
        return _converted_image_bytes(image, "RGB", raw_mode="BGR")
    if pixel_format is PixelFormat.BGRA32:
        return _converted_image_bytes(image, "RGBA", raw_mode="BGRA")
    return _converted_image_bytes(image, "L")


def _converted_image_bytes(
    image: Image.Image,
    mode: str,
    *,
    raw_mode: str | None = None,
) -> bytes:
    converted = image.convert(mode)
    try:
        if raw_mode is not None:
            return converted.tobytes("raw", raw_mode)
        return converted.tobytes()
    finally:
        converted.close()


def resolve_region(region: ScreenRect | None, viewport: Viewport) -> Rect:
    if region is None:
        resolved = viewport.region
        if resolved is None:
            raise RuntimeError("viewport region was not initialized")
        return resolved
    if isinstance(region, NormalizedRect):
        return viewport.map_rect(region)

    viewport_region = _require_viewport_region(viewport)
    if region.left < viewport_region.left or region.top < viewport_region.top:
        raise ValueError("region must stay within the viewport region")
    if region.right > viewport_region.right or region.bottom > viewport_region.bottom:
        raise ValueError("region must stay within the viewport region")
    return region


def resolve_point(point: ScreenPoint, viewport: Viewport) -> Point:
    if isinstance(point, NormalizedPoint):
        return viewport.map_point(point)

    viewport_region = _require_viewport_region(viewport)
    if not (viewport_region.left <= point.x < viewport_region.right):
        raise ValueError("point.x must stay within the viewport region")
    if not (viewport_region.top <= point.y < viewport_region.bottom):
        raise ValueError("point.y must stay within the viewport region")
    return point


def pixel_color_matches(actual: Color, expected: Color, *, tolerance: int = 0) -> bool:
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    if len(actual) != len(expected):
        raise ValueError("actual and expected colors must have the same channel count")
    return all(
        abs(actual_channel - expected_channel) <= tolerance
        for actual_channel, expected_channel in zip(actual, expected, strict=True)
    )


def probe_color(
    image: FrameImage,
    point: ScreenPoint,
    expected: Color,
    *,
    tolerance: int = 0,
    viewport: Viewport | None = None,
) -> bool:
    return pixel_color_matches(
        image.pixel(point, viewport=viewport),
        expected,
        tolerance=tolerance,
    )


def get_color(
    image: FrameImage,
    point: ScreenPoint,
    *,
    viewport: Viewport | None = None,
) -> Color:
    """Read the color at a point using FrameImage coordinate handling."""

    return image.pixel(point, viewport=viewport)


def rect_to_normalized(rect: Rect, size: Size) -> NormalizedRect:
    if rect.right > size.width or rect.bottom > size.height:
        raise ValueError("rect must fit within image size")

    left = rect.left / size.width
    top = rect.top / size.height
    right = rect.right / size.width
    bottom = rect.bottom / size.height
    return NormalizedRect(
        left=left,
        top=top,
        width=right - left,
        height=bottom - top,
    )


def intersect_regions(first: Rect, second: Rect) -> Rect | None:
    left = max(first.left, second.left)
    top = max(first.top, second.top)
    right = min(first.right, second.right)
    bottom = min(first.bottom, second.bottom)

    if left >= right or top >= bottom:
        return None
    return Rect(left=left, top=top, width=right - left, height=bottom - top)


def _require_viewport_region(viewport: Viewport) -> Rect:
    region = viewport.region
    if region is None:
        raise RuntimeError("viewport region was not initialized")
    return region


__all__ = [
    "Color",
    "FrameImage",
    "get_color",
    "intersect_regions",
    "pixel_color_matches",
    "probe_color",
    "rect_to_normalized",
    "resolve_point",
    "resolve_region",
]
