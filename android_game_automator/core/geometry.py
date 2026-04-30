"""Geometry primitives shared by input, capture, and detection contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

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


def _map_inclusive_axis(value: float, size: int) -> int:
    if size == 1:
        return 0
    scaled = _decimal_from_normalized(value) * Decimal(size - 1)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def _map_rect_start_axis(value: float, size: int) -> int:
    scaled = _snap_decimal_to_integer_edge(_decimal_from_normalized(value) * Decimal(size))
    return int(scaled.to_integral_value(rounding=ROUND_FLOOR))


def _map_rect_end_axis(value: float, size: int) -> int:
    scaled = _snap_decimal_to_integer_edge(_decimal_from_normalized(value) * Decimal(size))
    return int(scaled.to_integral_value(rounding=ROUND_CEILING))


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
