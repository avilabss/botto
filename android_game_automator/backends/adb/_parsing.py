"""ADB shell output parsing helpers.

Parsing quirks are intentionally isolated here so backend/session flow can stay simple.
"""

from __future__ import annotations

import re

from android_game_automator.core import Size

_ROTATION_PATTERNS = (
    re.compile(r"\bSurfaceOrientation:\s*(?P<value>\d+)\b"),
    re.compile(r"\bmCurrentOrientation(?:=|:)\s*(?P<value>\d+)\b"),
    re.compile(r"\borientation=(?P<value>\d+)\b"),
    re.compile(r"\bmRotation(?:=|:)\s*(?P<value>\d+)\b"),
    re.compile(r"\brotation(?:=|:)\s*(?P<value>\d+)\b"),
)

_OVERRIDE_SIZE_PATTERN = re.compile(r"\bOverride size:\s*(?P<width>\d+)x(?P<height>\d+)\b")
_PHYSICAL_SIZE_PATTERN = re.compile(r"\bPhysical size:\s*(?P<width>\d+)x(?P<height>\d+)\b")
_DISPLAY_VIEWPORT_SIZE_PATTERN = re.compile(
    r"\bdeviceWidth=(?P<width>\d+),\s*deviceHeight=(?P<height>\d+)\b"
)
_DISPLAY_REAL_SIZE_PATTERN = re.compile(r"\breal\s+(?P<width>\d+)\s*x\s*(?P<height>\d+)\b")


def parse_rotation_quadrants(output: str) -> int | None:
    """Parse display rotation in quarter-turn units (0-3)."""
    for pattern in _ROTATION_PATTERNS:
        match = pattern.search(output)
        if match is None:
            continue
        rotation = _normalize_rotation(int(match.group("value")))
        if rotation is not None:
            return rotation
    return None


def parse_wm_size(output: str) -> Size | None:
    """Parse display size from `wm size` output.

    Override size is preferred when present because Android applies it over physical size.
    """
    override = _OVERRIDE_SIZE_PATTERN.search(output)
    if override is not None:
        return _size_from_match(override)

    physical = _PHYSICAL_SIZE_PATTERN.search(output)
    if physical is not None:
        return _size_from_match(physical)

    return None


def parse_display_size(output: str) -> Size | None:
    """Parse display size from `dumpsys display`/`dumpsys window` output."""
    viewport = _DISPLAY_VIEWPORT_SIZE_PATTERN.search(output)
    if viewport is not None:
        return _size_from_match(viewport)

    real = _DISPLAY_REAL_SIZE_PATTERN.search(output)
    if real is not None:
        return _size_from_match(real)

    return None


def orient_size_for_rotation(size: Size, rotation_quadrants: int) -> Size:
    """Adjust a base size into current orientation dimensions."""
    if rotation_quadrants % 2 == 1:
        return Size(width=size.height, height=size.width)
    return size


def _size_from_match(match: re.Match[str]) -> Size | None:
    width = int(match.group("width"))
    height = int(match.group("height"))
    if width <= 0 or height <= 0:
        return None
    return Size(width=width, height=height)


def _normalize_rotation(raw_value: int) -> int | None:
    if raw_value in (0, 1, 2, 3):
        return raw_value
    if raw_value in (90, 180, 270):
        return raw_value // 90
    return None
