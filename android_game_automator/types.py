"""Shared SDK data models and value types."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType

_NORMALIZED_EDGE_TOLERANCE = Decimal("1e-12")


@dataclass(frozen=True, slots=True)
class Size:
    """Pixel dimensions for a frame or display area."""

    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError("width must be > 0")
        if self.height <= 0:
            raise ValueError("height must be > 0")


@dataclass(frozen=True, slots=True)
class Point:
    """Absolute point in pixel coordinates."""

    x: int
    y: int

    def __post_init__(self) -> None:
        if self.x < 0:
            raise ValueError("x must be >= 0")
        if self.y < 0:
            raise ValueError("y must be >= 0")


@dataclass(frozen=True, slots=True)
class Rect:
    """Absolute rectangle in pixel coordinates."""

    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.left < 0:
            raise ValueError("left must be >= 0")
        if self.top < 0:
            raise ValueError("top must be >= 0")
        if self.width <= 0:
            raise ValueError("width must be > 0")
        if self.height <= 0:
            raise ValueError("height must be > 0")

    @property
    def right(self) -> int:
        """The exclusive right edge in pixels."""
        return self.left + self.width

    @property
    def bottom(self) -> int:
        """The exclusive bottom edge in pixels."""
        return self.top + self.height


@dataclass(frozen=True, slots=True)
class NormalizedPoint:
    """Point normalized to the inclusive range [0.0, 1.0]."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.x <= 1.0:
            raise ValueError("x must be within [0.0, 1.0]")
        if not 0.0 <= self.y <= 1.0:
            raise ValueError("y must be within [0.0, 1.0]")


@dataclass(frozen=True, slots=True)
class NormalizedRect:
    """Rectangle normalized to the inclusive range [0.0, 1.0]."""

    left: float
    top: float
    width: float
    height: float

    def __post_init__(self) -> None:
        left = _decimal_from_normalized(self.left)
        top = _decimal_from_normalized(self.top)
        width = _decimal_from_normalized(self.width)
        height = _decimal_from_normalized(self.height)
        right = _snap_decimal_to_integer_edge(left + width)
        bottom = _snap_decimal_to_integer_edge(top + height)

        if not 0.0 <= self.left <= 1.0:
            raise ValueError("left must be within [0.0, 1.0]")
        if not 0.0 <= self.top <= 1.0:
            raise ValueError("top must be within [0.0, 1.0]")
        if not 0.0 < self.width <= 1.0:
            raise ValueError("width must be within (0.0, 1.0]")
        if not 0.0 < self.height <= 1.0:
            raise ValueError("height must be within (0.0, 1.0]")
        if right > Decimal("1.0"):
            raise ValueError("left + width must be <= 1.0")
        if bottom > Decimal("1.0"):
            raise ValueError("top + height must be <= 1.0")

    @property
    def right(self) -> float:
        """The normalized right edge."""
        return self.left + self.width

    @property
    def bottom(self) -> float:
        """The normalized bottom edge."""
        return self.top + self.height


@dataclass(frozen=True, slots=True)
class Viewport:
    """A target surface region that normalized coordinates can map into."""

    surface_size: Size
    region: Rect | None = None

    def __post_init__(self) -> None:
        if self.region is None:
            object.__setattr__(
                self,
                "region",
                Rect(
                    left=0,
                    top=0,
                    width=self.surface_size.width,
                    height=self.surface_size.height,
                ),
            )
        region = self.region
        if region is None:
            return

        if region.right > self.surface_size.width:
            raise ValueError("region must fit within surface width")
        if region.bottom > self.surface_size.height:
            raise ValueError("region must fit within surface height")

    def map_point(self, point: NormalizedPoint) -> Point:
        """Map a normalized point into an inclusive pixel coordinate."""
        region = self._require_region()
        x = region.left + _map_inclusive_axis(point.x, region.width)
        y = region.top + _map_inclusive_axis(point.y, region.height)
        return Point(x=x, y=y)

    def map_rect(self, rect: NormalizedRect) -> Rect:
        """Map a normalized rect into pixel edges within the viewport region."""
        region = self._require_region()
        left = region.left + _map_rect_start_axis(rect.left, region.width)
        top = region.top + _map_rect_start_axis(rect.top, region.height)
        right = region.left + _map_rect_end_axis_from_components(
            rect.left,
            rect.width,
            region.width,
        )
        bottom = region.top + _map_rect_end_axis_from_components(
            rect.top,
            rect.height,
            region.height,
        )
        return Rect(left=left, top=top, width=right - left, height=bottom - top)

    def _require_region(self) -> Rect:
        region = self.region
        if region is None:
            raise RuntimeError("viewport region was not initialized")
        return region


class PixelFormat(StrEnum):
    """Minimal shared pixel format declarations."""

    RGB24 = "rgb24"
    RGBA32 = "rgba32"
    BGR24 = "bgr24"
    BGRA32 = "bgra32"
    GRAY8 = "gray8"


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """Stable identity for a device exposed by a backend."""

    backend_name: str
    device_id: str
    display_name: str | None = None

    def __post_init__(self) -> None:
        if not self.backend_name.strip():
            raise ValueError("backend_name must be non-empty")
        if not self.device_id.strip():
            raise ValueError("device_id must be non-empty")
        if self.display_name is not None and not self.display_name.strip():
            raise ValueError("display_name must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Identity and metadata for a discovered device."""

    identity: DeviceIdentity
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Metadata for an active automation session."""

    session_id: str
    device: DeviceInfo
    started_at: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must be non-empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class Match:
    """Single best template match in absolute source-image pixels."""

    bounds: Rect
    confidence: float
    scale: float
    rotation: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        if not math.isfinite(self.scale) or self.scale <= 0.0:
            raise ValueError("scale must be finite and > 0.0")
        if not math.isfinite(self.rotation):
            raise ValueError("rotation must be finite")

    @property
    def center(self) -> Point:
        """Integer pixel point near the center of the match bounds."""

        return Point(
            x=self.bounds.left + self.bounds.width // 2,
            y=self.bounds.top + self.bounds.height // 2,
        )


@dataclass(frozen=True, slots=True)
class TextBlock:
    """Single OCR text block recognized within an image or ROI."""

    text: str
    confidence: float | None = None
    bounds: NormalizedRect | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("text must be non-empty")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0] when provided")


def _map_inclusive_axis(value: float, size: int) -> int:
    if size == 1:
        return 0
    scaled = _decimal_from_normalized(value) * Decimal(size - 1)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def _map_rect_start_axis(value: float, size: int) -> int:
    scaled = _snap_decimal_to_integer_edge(_decimal_from_normalized(value) * Decimal(size))
    return int(scaled.to_integral_value(rounding=ROUND_FLOOR))


def _map_rect_end_axis_from_components(start: float, extent: float, size: int) -> int:
    scaled = _snap_decimal_to_integer_edge(
        (_decimal_from_normalized(start) + _decimal_from_normalized(extent)) * Decimal(size)
    )
    return int(scaled.to_integral_value(rounding=ROUND_CEILING))


def _decimal_from_normalized(value: float) -> Decimal:
    return Decimal(repr(value))


def _snap_decimal_to_integer_edge(value: Decimal) -> Decimal:
    floor = value.to_integral_value(rounding=ROUND_FLOOR)
    if value - floor <= _NORMALIZED_EDGE_TOLERANCE:
        return floor

    ceiling = value.to_integral_value(rounding=ROUND_CEILING)
    if ceiling - value <= _NORMALIZED_EDGE_TOLERANCE:
        return ceiling

    return value


ScreenPoint = Point | NormalizedPoint
ScreenRect = Rect | NormalizedRect

__all__ = [
    "DeviceIdentity",
    "DeviceInfo",
    "Match",
    "NormalizedPoint",
    "NormalizedRect",
    "PixelFormat",
    "Point",
    "Rect",
    "ScreenPoint",
    "ScreenRect",
    "SessionInfo",
    "Size",
    "TextBlock",
    "Viewport",
]
