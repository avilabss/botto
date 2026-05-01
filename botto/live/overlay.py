"""Debug overlay rendering helpers."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import TYPE_CHECKING

import cv2
import numpy as np
from android_game_automator.image import FrameImage
from android_game_automator.types import (
    NormalizedPoint,
    NormalizedRect,
    PixelFormat,
    Point,
    Rect,
    Size,
    Viewport,
)

from botto.detection import Overlay, ScreenAnalysis

from .window import BgrArray, frame_image_to_bgr_array

if TYPE_CHECKING:
    from botto.live.debug_preview import DebugPreviewAnalysisSnapshot

type BgrColor = tuple[int, int, int]

_STATUS_TEXT_COLOR: BgrColor = (255, 255, 255)
_STATUS_BACKGROUND_COLOR: BgrColor = (0, 0, 0)
_NORMAL_BOUNDS_COLOR: BgrColor = (40, 210, 40)
_NORMAL_REGION_COLOR: BgrColor = (255, 210, 40)
_PROBLEM_BOUNDS_COLOR: BgrColor = (40, 40, 255)
_PROBLEM_REGION_COLOR: BgrColor = (0, 165, 255)
_TARGET_COLOR: BgrColor = (255, 0, 255)
_TEXT_SCALE = 0.5
_TEXT_THICKNESS = 1
_LINE_THICKNESS = 2


def render_debug_overlay(
    frame: FrameImage,
    snapshot: DebugPreviewAnalysisSnapshot | None,
    *,
    now: float | None = None,
    analysis_running: bool = False,
    status_message: str | None = None,
) -> FrameImage:
    """Return a copy of ``frame`` annotated with live detector state and evidence."""

    bgr = frame_image_to_bgr_array(frame)
    status_lines = _debug_status_lines(
        snapshot,
        now=now,
        analysis_running=analysis_running,
        frame_size=frame.size,
        status_message=status_message,
    )
    _draw_status_lines(bgr, status_lines)

    if snapshot is not None:
        analysis = snapshot.analysis
        evidence_is_problem = analysis.overlay is not Overlay.NONE
        for evidence in analysis.evidence:
            _draw_evidence(bgr, frame.size, evidence, is_problem=evidence_is_problem)
        _draw_recommended_action(bgr, frame.size, analysis)

    rgba = np.frombuffer(frame.data, dtype=np.uint8).reshape((frame.height, frame.width, 4))
    annotated_rgba = np.empty((frame.height, frame.width, 4), dtype=np.uint8)
    annotated_rgba[..., 0] = bgr[..., 2]
    annotated_rgba[..., 1] = bgr[..., 1]
    annotated_rgba[..., 2] = bgr[..., 0]
    annotated_rgba[..., 3] = rgba[..., 3]
    return FrameImage(
        size=frame.size,
        pixel_format=PixelFormat.RGBA32,
        data=annotated_rgba.tobytes(),
        captured_at=frame.captured_at,
        frame_id=frame.frame_id,
    )


def _debug_status_lines(
    snapshot: DebugPreviewAnalysisSnapshot | None,
    *,
    now: float | None,
    analysis_running: bool = False,
    frame_size: Size | None = None,
    status_message: str | None = None,
) -> tuple[str, ...]:
    lines: list[str] = []
    if frame_size is not None:
        lines.append(f"frame: {frame_size.width}x{frame_size.height}")

    if snapshot is None:
        lines.append("analysis: running" if analysis_running else "analysis: pending")
        if status_message:
            lines.append(status_message)
        return tuple(lines)

    analysis = snapshot.analysis
    lines.extend(
        (
            f"base: {analysis.base_screen.value}",
            f"overlay: {analysis.overlay.value}  conf: {analysis.confidence:.2f}",
        )
    )
    timing_parts: list[str] = []
    if now is not None:
        timing_parts.append(f"age: {max(0.0, now - snapshot.analyzed_at):.1f}s")
    if snapshot.duration_seconds is not None:
        timing_parts.append(f"took: {snapshot.duration_seconds:.2f}s")
    if analysis_running:
        timing_parts.append("running")
    if timing_parts:
        lines.append("analysis " + "  ".join(timing_parts))
    elif analysis_running:
        lines.append("analysis running")
    if status_message:
        lines.append(status_message)
    return tuple(lines)


def _draw_status_lines(bgr: BgrArray, lines: tuple[str, ...]) -> None:
    if not lines:
        return

    line_height = 18
    background_height = 8 + line_height * len(lines)
    cv2.rectangle(
        bgr,
        (0, 0),
        (min(bgr.shape[1] - 1, 420), min(bgr.shape[0] - 1, background_height)),
        _STATUS_BACKGROUND_COLOR,
        thickness=-1,
    )
    for index, line in enumerate(lines):
        cv2.putText(
            bgr,
            line,
            (8, 18 + index * line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            _TEXT_SCALE,
            _STATUS_TEXT_COLOR,
            _TEXT_THICKNESS,
            cv2.LINE_AA,
        )


def _draw_evidence(
    bgr: BgrArray,
    size: Size,
    evidence: object,
    *,
    is_problem: bool,
) -> None:
    details = getattr(evidence, "details", None)
    if not isinstance(details, Mapping):
        return

    label = _evidence_label(evidence)
    bounds = _coerce_rect(details.get("bounds"), size)
    region = _coerce_rect(details.get("region"), size)
    bounds_color = _PROBLEM_BOUNDS_COLOR if is_problem else _NORMAL_BOUNDS_COLOR
    region_color = _PROBLEM_REGION_COLOR if is_problem else _NORMAL_REGION_COLOR

    if region is not None:
        _draw_rect(bgr, region, region_color)
        _draw_label(bgr, label, region, region_color)
    if bounds is not None:
        _draw_rect(bgr, bounds, bounds_color)
        _draw_label(bgr, label, bounds, bounds_color)


def _draw_rect(bgr: BgrArray, rect: Rect, color: BgrColor) -> None:
    cv2.rectangle(
        bgr,
        (rect.left, rect.top),
        (rect.right - 1, rect.bottom - 1),
        color,
        thickness=_LINE_THICKNESS,
    )


def _draw_label(bgr: BgrArray, label: str, rect: Rect, color: BgrColor) -> None:
    if not label:
        return

    y = max(12, rect.top - 4)
    cv2.putText(
        bgr,
        label,
        (rect.left, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        _TEXT_SCALE,
        color,
        _TEXT_THICKNESS,
        cv2.LINE_AA,
    )


def _draw_recommended_action(bgr: BgrArray, size: Size, analysis: ScreenAnalysis) -> None:
    action = analysis.recommended_action
    if action is None or action.tap_target is None:
        return

    target = _coerce_point(action.tap_target, size)
    if target is None:
        return

    radius = 8
    cv2.circle(bgr, (target.x, target.y), radius, _TARGET_COLOR, thickness=_LINE_THICKNESS)
    cv2.line(
        bgr,
        (max(0, target.x - radius), target.y),
        (min(size.width - 1, target.x + radius), target.y),
        _TARGET_COLOR,
        thickness=_LINE_THICKNESS,
    )
    cv2.line(
        bgr,
        (target.x, max(0, target.y - radius)),
        (target.x, min(size.height - 1, target.y + radius)),
        _TARGET_COLOR,
        thickness=_LINE_THICKNESS,
    )
    cv2.putText(
        bgr,
        f"target: {_display_label(action)}",
        (max(0, target.x + 10), max(12, target.y - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        _TEXT_SCALE,
        _TARGET_COLOR,
        _TEXT_THICKNESS,
        cv2.LINE_AA,
    )


def _evidence_label(evidence: object) -> str:
    label = _display_label(evidence)
    confidence = getattr(evidence, "confidence", None)
    if isinstance(confidence, int | float) and not isinstance(confidence, bool):
        return f"{label} {confidence:.2f}" if label else f"{confidence:.2f}"
    return label


def _display_label(value: object) -> str:
    label = getattr(value, "display_label", "")
    if isinstance(label, str):
        return label.strip()
    return ""


def _coerce_rect(value: object, size: Size) -> Rect | None:
    if isinstance(value, Rect):
        return _clip_rect(value.left, value.top, value.width, value.height, size)
    if isinstance(value, NormalizedRect):
        return _map_normalized_rect(value, size)

    components = _rect_components(value)
    if components is None:
        return None

    left, top, width, height = components
    if _looks_normalized_rect(left, top, width, height):
        try:
            return _map_normalized_rect(
                NormalizedRect(left=left, top=top, width=width, height=height),
                size,
            )
        except ValueError:
            return None
    return _clip_rect(round(left), round(top), round(width), round(height), size)


def _map_normalized_rect(rect: NormalizedRect, size: Size) -> Rect | None:
    try:
        mapped = Viewport(surface_size=size).map_rect(rect)
    except ValueError:
        return None
    return _clip_rect(mapped.left, mapped.top, mapped.width, mapped.height, size)


def _rect_components(value: object) -> tuple[float, float, float, float] | None:
    raw_components: tuple[object, object, object, object] | None
    if isinstance(value, Mapping):
        try:
            raw_components = (
                value["left"],
                value["top"],
                value["width"],
                value["height"],
            )
        except KeyError:
            return None
    elif all(hasattr(value, name) for name in ("left", "top", "width", "height")):
        raw_components = (
            _attribute(value, "left"),
            _attribute(value, "top"),
            _attribute(value, "width"),
            _attribute(value, "height"),
        )
    else:
        return None

    left = _number(raw_components[0])
    top = _number(raw_components[1])
    width = _number(raw_components[2])
    height = _number(raw_components[3])
    if left is None or top is None or width is None or height is None:
        return None
    if width <= 0 or height <= 0:
        return None
    return left, top, width, height


def _coerce_point(value: object, size: Size) -> Point | None:
    if isinstance(value, Point):
        return _point_within_size(value, size)
    if isinstance(value, NormalizedPoint):
        try:
            return Viewport(surface_size=size).map_point(value)
        except ValueError:
            return None

    components = _point_components(value)
    if components is None:
        return None

    x, y = components
    if _looks_normalized_point(x, y):
        try:
            return Viewport(surface_size=size).map_point(NormalizedPoint(x=x, y=y))
        except ValueError:
            return None
    return _point_from_components(round(x), round(y), size)


def _point_components(value: object) -> tuple[float, float] | None:
    raw_components: tuple[object, object] | None
    if isinstance(value, Mapping):
        try:
            raw_components = (value["x"], value["y"])
        except KeyError:
            return None
    elif all(hasattr(value, name) for name in ("x", "y")):
        raw_components = (_attribute(value, "x"), _attribute(value, "y"))
    else:
        return None

    x = _number(raw_components[0])
    y = _number(raw_components[1])
    if x is None or y is None:
        return None
    return x, y


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not isfinite(number):
        return None
    return number


def _attribute(value: object, name: str) -> object:
    return getattr(value, name)


def _looks_normalized_rect(left: float, top: float, width: float, height: float) -> bool:
    return (
        0.0 <= left <= 1.0
        and 0.0 <= top <= 1.0
        and 0.0 < width <= 1.0
        and 0.0 < height <= 1.0
        and left + width <= 1.0
        and top + height <= 1.0
    )


def _looks_normalized_point(x: float, y: float) -> bool:
    return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def _clip_rect(left: int, top: int, width: int, height: int, size: Size) -> Rect | None:
    if width <= 0 or height <= 0:
        return None

    right = left + width
    bottom = top + height
    clipped_left = min(max(left, 0), size.width)
    clipped_top = min(max(top, 0), size.height)
    clipped_right = min(max(right, 0), size.width)
    clipped_bottom = min(max(bottom, 0), size.height)
    if clipped_left >= clipped_right or clipped_top >= clipped_bottom:
        return None
    return Rect(
        left=clipped_left,
        top=clipped_top,
        width=clipped_right - clipped_left,
        height=clipped_bottom - clipped_top,
    )


def _point_within_size(point: Point, size: Size) -> Point | None:
    if not (0 <= point.x < size.width and 0 <= point.y < size.height):
        return None
    return point


def _point_from_components(x: int, y: int, size: Size) -> Point | None:
    if not (0 <= x < size.width and 0 <= y < size.height):
        return None
    return Point(x=x, y=y)


__all__ = ["render_debug_overlay"]
