"""OpenCV-backed template and feature matching helpers."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from os import PathLike
from typing import Any, cast

import cv2
import numpy as np
import numpy.typing as npt
from PIL import Image

from android_game_automator.image import FrameImage, resolve_region
from android_game_automator.types import Match, PixelFormat, Point, Rect, ScreenRect, Size, Viewport

type GrayImage = npt.NDArray[np.uint8]
type ImageInput = FrameImage | Image.Image | str | PathLike[str]

_MIN_VISIBLE_ALPHA_PIXELS = 4


@dataclass(frozen=True, slots=True)
class FeatureMatch:
    """Single best ORB feature match in absolute source-image pixels."""

    bounds: Rect
    confidence: float
    match_count: int
    center: Point

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        if self.match_count <= 0:
            raise ValueError("match_count must be > 0")


def find_template(
    source: ImageInput,
    template: ImageInput,
    *,
    region: ScreenRect | None = None,
    min_confidence: float = 0.9,
    threshold: float | None = None,
    scales: Iterable[float] = (1.0,),
    rotations: Iterable[float] = (0.0,),
    alpha_threshold: int = 16,
) -> Match | None:
    """Return the best OpenCV template match, or ``None`` below the threshold.

    Transparent template pixels with alpha below ``alpha_threshold`` are ignored.
    """

    resolved_min_confidence = _resolve_min_confidence(min_confidence, threshold)
    resolved_scales = _normalize_scales(scales)
    resolved_rotations = _normalize_rotations(rotations)
    resolved_alpha_threshold = _normalize_alpha_threshold(alpha_threshold)
    source_image = _coerce_image(source, name="source")
    template_image = _coerce_image(template, name="template")
    template_mask = _template_alpha_mask(template_image, alpha_threshold=resolved_alpha_threshold)
    if template_mask is not None:
        _validate_visible_alpha_mask(template_mask)
    search_region = resolve_region(region, Viewport(surface_size=source_image.size))

    match = _match_template(
        source_image,
        search_region,
        template_image,
        template_mask=template_mask,
        scales=resolved_scales,
        rotations=resolved_rotations,
    )
    if match is None or match.confidence < resolved_min_confidence:
        return None
    return match


def find_feature_match(
    source: ImageInput,
    template: ImageInput,
    *,
    region: ScreenRect | None = None,
    min_matches: int = 8,
    min_confidence: float = 0.25,
    alpha_threshold: int = 16,
) -> FeatureMatch | None:
    """Return the best ORB feature match for textured objects, or ``None``.

    ORB matching is useful for feature-rich/textured objects. For flat UI icons or
    buttons, prefer :func:`find_template`. Transparent template pixels with alpha
    below ``alpha_threshold`` are excluded from template keypoint detection.
    """

    if min_matches < 4:
        raise ValueError("min_matches must be >= 4")
    _validate_confidence(min_confidence, name="min_confidence")
    resolved_alpha_threshold = _normalize_alpha_threshold(alpha_threshold)

    source_image = _coerce_image(source, name="source")
    template_image = _coerce_image(template, name="template")
    template_mask = _template_alpha_mask(template_image, alpha_threshold=resolved_alpha_threshold)
    search_region = resolve_region(region, Viewport(surface_size=source_image.size))

    match = _match_features(
        source_image,
        search_region,
        template_image,
        template_mask=template_mask,
        min_matches=min_matches,
    )
    if match is None or match.confidence < min_confidence:
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


def _normalize_alpha_threshold(alpha_threshold: int) -> int:
    if isinstance(alpha_threshold, bool) or not isinstance(alpha_threshold, int):
        raise ValueError("alpha_threshold must be an int within [0, 255]")
    if not 0 <= alpha_threshold <= 255:
        raise ValueError("alpha_threshold must be within [0, 255]")
    return alpha_threshold


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
    template_mask: GrayImage | None,
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
        scaled_mask = (
            _scaled_template_array(template_mask, scale) if template_mask is not None else None
        )
        for rotation in rotations:
            transformed_template = _rotated_template_array(scaled_template, rotation)
            transformed_mask = (
                _rotated_template_array(scaled_mask, rotation) if scaled_mask is not None else None
            )
            if (
                transformed_mask is not None
                and _visible_mask_pixel_count(transformed_mask) < _MIN_VISIBLE_ALPHA_PIXELS
            ):
                continue
            template_height, template_width = transformed_template.shape[:2]
            if template_width > search_region.width or template_height > search_region.height:
                continue

            best_match = _best_template_match(
                search_array,
                transformed_template,
                template_mask=transformed_mask,
            )
            if best_match is None:
                continue
            confidence, offset = best_match
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


def _match_features(
    source: FrameImage,
    search_region: Rect,
    template: FrameImage,
    *,
    template_mask: GrayImage | None,
    min_matches: int,
) -> FeatureMatch | None:
    if (
        template_mask is not None
        and _visible_mask_pixel_count(template_mask) < _MIN_VISIBLE_ALPHA_PIXELS
    ):
        return None

    search_image = source.crop(search_region)
    search_array = _frame_image_to_grayscale_array(search_image)
    template_array = _frame_image_to_grayscale_array(template)

    orb = cast(Any, cv2).ORB_create(nfeatures=1000, edgeThreshold=5)
    template_keypoints, template_descriptors = orb.detectAndCompute(template_array, template_mask)
    search_keypoints, search_descriptors = orb.detectAndCompute(search_array, None)
    if template_descriptors is None or search_descriptors is None:
        return None
    if len(template_keypoints) < min_matches or len(search_keypoints) < min_matches:
        return None

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(
        matcher.match(template_descriptors, search_descriptors),
        key=lambda match: match.distance,
    )
    if len(matches) < min_matches:
        return None

    template_points = np.array(
        [template_keypoints[match.queryIdx].pt for match in matches],
        dtype=np.float32,
    ).reshape(-1, 1, 2)
    search_points = np.array(
        [search_keypoints[match.trainIdx].pt for match in matches],
        dtype=np.float32,
    ).reshape(
        -1,
        1,
        2,
    )
    homography, inlier_mask = cv2.findHomography(
        template_points,
        search_points,
        cv2.RANSAC,
        5.0,
    )
    if homography is None or inlier_mask is None:
        return None

    mask_values = [bool(value) for value in inlier_mask.ravel().tolist()]
    inlier_distances = [
        match.distance for match, is_inlier in zip(matches, mask_values, strict=True) if is_inlier
    ]
    inlier_count = len(inlier_distances)
    if inlier_count < min_matches:
        return None

    bounds = _feature_match_bounds(
        homography,
        template_width=template_array.shape[1],
        template_height=template_array.shape[0],
        search_region=search_region,
        source_size=source.size,
    )
    if bounds is None:
        return None

    confidence = _feature_confidence(
        distances=inlier_distances,
        inlier_count=inlier_count,
        min_matches=min_matches,
    )
    return FeatureMatch(
        bounds=bounds,
        confidence=confidence,
        match_count=inlier_count,
        center=Point(
            x=bounds.left + bounds.width // 2,
            y=bounds.top + bounds.height // 2,
        ),
    )


def _feature_match_bounds(
    homography: npt.NDArray[Any],
    *,
    template_width: int,
    template_height: int,
    search_region: Rect,
    source_size: Size,
) -> Rect | None:
    corners = np.array(
        [
            [0, 0],
            [template_width, 0],
            [template_width, template_height],
            [0, template_height],
        ],
        dtype=np.float32,
    ).reshape(-1, 1, 2)
    projected = cv2.perspectiveTransform(corners, homography)
    if not bool(np.isfinite(projected).all()):
        return None
    xs = projected[:, 0, 0]
    ys = projected[:, 0, 1]

    left = search_region.left + math.floor(float(xs.min()))
    top = search_region.top + math.floor(float(ys.min()))
    right = search_region.left + math.ceil(float(xs.max()))
    bottom = search_region.top + math.ceil(float(ys.max()))

    source_width = source_size.width
    source_height = source_size.height
    left = max(0, min(left, source_width))
    top = max(0, min(top, source_height))
    right = max(0, min(right, source_width))
    bottom = max(0, min(bottom, source_height))

    if right <= left or bottom <= top:
        return None
    return Rect(left=left, top=top, width=right - left, height=bottom - top)


def _feature_confidence(
    *,
    distances: Iterable[float],
    inlier_count: int,
    min_matches: int,
) -> float:
    resolved_distances = tuple(distances)
    if not resolved_distances:
        return 0.0
    average_distance = sum(resolved_distances) / len(resolved_distances)
    distance_quality = 1.0 - min(96.0, average_distance) / 96.0
    support_quality = min(1.0, inlier_count / min_matches)
    return max(0.0, min(1.0, support_quality * distance_quality))


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


def _template_alpha_mask(template: FrameImage, *, alpha_threshold: int) -> GrayImage | None:
    alpha_array = _frame_image_alpha_array(template)
    if alpha_array is None or bool(np.all(alpha_array == 255)):
        return None
    return cast(GrayImage, np.where(alpha_array >= alpha_threshold, 255, 0).astype(np.uint8))


def _frame_image_alpha_array(image: FrameImage) -> GrayImage | None:
    if image.pixel_format not in (PixelFormat.RGBA32, PixelFormat.BGRA32):
        return None
    rgba_array = np.frombuffer(image.data, dtype=np.uint8).reshape(
        image.height,
        image.width,
        image.channels,
    )
    return cast(GrayImage, rgba_array[:, :, 3].copy())


def _visible_mask_pixel_count(mask: GrayImage) -> int:
    return int(np.count_nonzero(mask))


def _validate_visible_alpha_mask(mask: GrayImage) -> None:
    visible_pixels = _visible_mask_pixel_count(mask)
    if visible_pixels < _MIN_VISIBLE_ALPHA_PIXELS:
        raise ValueError(
            f"template alpha mask must contain at least {_MIN_VISIBLE_ALPHA_PIXELS} visible pixels"
        )


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
    *,
    template_mask: GrayImage | None,
) -> tuple[float, Point] | None:
    if template_mask is None:
        match_result = cv2.matchTemplate(search_image, template_image, cv2.TM_SQDIFF_NORMED)
    else:
        match_result = cv2.matchTemplate(
            search_image,
            template_image,
            cv2.TM_SQDIFF_NORMED,
            mask=template_mask,
        )
    if template_mask is not None:
        finite_values = np.isfinite(match_result)
        if not bool(finite_values.any()):
            return None
        match_result = match_result.copy()
        match_result[~finite_values] = np.inf
    min_value, _, min_location, _ = cv2.minMaxLoc(match_result)
    if template_mask is not None and not math.isfinite(min_value):
        return None
    confidence = max(0.0, min(1.0, 1.0 - min_value))
    return confidence, Point(x=min_location[0], y=min_location[1])


__all__ = ["FeatureMatch", "find_feature_match", "find_template"]
