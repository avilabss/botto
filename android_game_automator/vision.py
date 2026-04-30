"""OpenCV-backed template matching helpers."""

from __future__ import annotations

import math
from collections.abc import Iterable
from os import PathLike
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt
from PIL import Image

from android_game_automator.image import FrameImage, resolve_region
from android_game_automator.types import Match, Point, Rect, ScreenRect, Viewport

type GrayImage = npt.NDArray[np.uint8]
type ImageInput = FrameImage | Image.Image | str | PathLike[str]


def find_template(
    source: ImageInput,
    template: ImageInput,
    *,
    region: ScreenRect | None = None,
    min_confidence: float = 0.9,
    threshold: float | None = None,
    scales: Iterable[float] = (1.0,),
    rotations: Iterable[float] = (0.0,),
) -> Match | None:
    """Return the best OpenCV template match, or ``None`` below the threshold."""

    resolved_min_confidence = _resolve_min_confidence(min_confidence, threshold)
    resolved_scales = _normalize_scales(scales)
    resolved_rotations = _normalize_rotations(rotations)
    source_image = _coerce_image(source, name="source")
    template_image = _coerce_image(template, name="template")
    search_region = resolve_region(region, Viewport(surface_size=source_image.size))

    match = _match_template(
        source_image,
        search_region,
        template_image,
        scales=resolved_scales,
        rotations=resolved_rotations,
    )
    if match is None or match.confidence < resolved_min_confidence:
        return None
    return match


def _resolve_min_confidence(min_confidence: float, threshold: float | None) -> float:
    if threshold is not None:
        _validate_confidence(threshold, name="threshold")
        return threshold
    _validate_confidence(min_confidence, name="min_confidence")
    return min_confidence


def _validate_confidence(value: float, *, name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0.0, 1.0]")


def _normalize_scales(scales: Iterable[float]) -> tuple[float, ...]:
    resolved_scales = tuple(scales)
    if not resolved_scales:
        raise ValueError("scales must contain at least one value")
    if any(not math.isfinite(scale) or scale <= 0.0 for scale in resolved_scales):
        raise ValueError("scales must be finite and > 0.0")
    return resolved_scales


def _normalize_rotations(rotations: Iterable[float]) -> tuple[float, ...]:
    resolved_rotations = tuple(rotations)
    if not resolved_rotations:
        raise ValueError("rotations must contain at least one value")
    if any(not math.isfinite(rotation) for rotation in resolved_rotations):
        raise ValueError("rotations must be finite")
    return resolved_rotations


def _coerce_image(image: ImageInput, *, name: str) -> FrameImage:
    if isinstance(image, FrameImage):
        return image
    if isinstance(image, Image.Image):
        return FrameImage.from_pil_image(image)
    if isinstance(image, (str, PathLike)):
        with Image.open(image) as loaded_image:
            return FrameImage.from_pil_image(loaded_image)

    raise TypeError(f"{name} must be a FrameImage, PIL image, or filesystem path")


def _match_template(
    source: FrameImage,
    search_region: Rect,
    template: FrameImage,
    *,
    scales: tuple[float, ...],
    rotations: tuple[float, ...],
) -> Match | None:
    search_image = source.crop(search_region)
    search_array = _frame_image_to_grayscale_array(search_image)
    template_array = _frame_image_to_grayscale_array(template)

    best_confidence = -1.0
    best_rect: Rect | None = None
    best_scale: float | None = None
    best_rotation: float | None = None
    best_area = -1

    for scale in scales:
        scaled_template = _scaled_template_array(template_array, scale)
        for rotation in rotations:
            transformed_template = _rotated_template_array(scaled_template, rotation)
            template_height, template_width = transformed_template.shape[:2]
            if template_width > search_region.width or template_height > search_region.height:
                continue

            confidence, offset = _best_template_match(search_array, transformed_template)
            transformed_area = template_width * template_height
            if confidence < best_confidence:
                continue
            if confidence == best_confidence and transformed_area <= best_area:
                continue

            best_confidence = confidence
            best_scale = scale
            best_rotation = rotation
            best_area = transformed_area
            best_rect = Rect(
                left=search_region.left + offset.x,
                top=search_region.top + offset.y,
                width=template_width,
                height=template_height,
            )

    if best_rect is None or best_scale is None or best_rotation is None:
        return None
    return Match(
        bounds=best_rect,
        confidence=best_confidence,
        scale=best_scale,
        rotation=best_rotation,
    )


def _frame_image_to_grayscale_array(image: FrameImage) -> GrayImage:
    source = image.to_pil_image()
    try:
        grayscale = source.convert("L")
        try:
            return cast(GrayImage, np.asarray(grayscale, dtype=np.uint8).copy())
        finally:
            grayscale.close()
    finally:
        source.close()


def _scaled_template_array(template_image: GrayImage, scale: float) -> GrayImage:
    height, width = template_image.shape[:2]
    scaled_width = max(1, round(width * scale))
    scaled_height = max(1, round(height * scale))
    if scaled_width == width and scaled_height == height:
        return template_image
    return cast(
        GrayImage,
        cv2.resize(
            template_image,
            (scaled_width, scaled_height),
            interpolation=cv2.INTER_NEAREST,
        ),
    )


def _rotated_template_array(template_image: GrayImage, rotation: float) -> GrayImage:
    right_angle = _right_angle_rotation(rotation)
    if right_angle == 0:
        return template_image
    if right_angle == 90:
        return cast(GrayImage, cv2.rotate(template_image, cv2.ROTATE_90_COUNTERCLOCKWISE))
    if right_angle == 180:
        return cast(GrayImage, cv2.rotate(template_image, cv2.ROTATE_180))
    if right_angle == 270:
        return cast(GrayImage, cv2.rotate(template_image, cv2.ROTATE_90_CLOCKWISE))

    height, width = template_image.shape[:2]
    center = ((width - 1) / 2.0, (height - 1) / 2.0)
    rotation_matrix = cv2.getRotationMatrix2D(center, rotation, 1.0)
    cosine = abs(rotation_matrix[0, 0])
    sine = abs(rotation_matrix[0, 1])
    new_width = max(1, math.ceil((height * sine) + (width * cosine)))
    new_height = max(1, math.ceil((height * cosine) + (width * sine)))
    rotation_matrix[0, 2] += ((new_width - 1) / 2.0) - center[0]
    rotation_matrix[1, 2] += ((new_height - 1) / 2.0) - center[1]
    return cast(
        GrayImage,
        cv2.warpAffine(
            template_image,
            rotation_matrix,
            (new_width, new_height),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        ),
    )


def _right_angle_rotation(rotation: float) -> int | None:
    normalized = rotation % 360.0
    for angle in (0, 90, 180, 270):
        if math.isclose(normalized, angle, abs_tol=1e-9):
            return angle
    return None


def _best_template_match(
    search_image: GrayImage,
    template_image: GrayImage,
) -> tuple[float, Point]:
    match_result = cv2.matchTemplate(search_image, template_image, cv2.TM_SQDIFF_NORMED)
    min_value, _, min_location, _ = cv2.minMaxLoc(match_result)
    confidence = max(0.0, min(1.0, 1.0 - min_value))
    return confidence, Point(x=min_location[0], y=min_location[1])


__all__ = ["find_template"]
