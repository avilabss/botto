"""Composable detector helpers built on the lightweight vision layer."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from PIL import Image

from android_game_automator.core import (
    CapturedFrame,
    Detection,
    DetectionRequest,
    DetectionResult,
    Point,
    Rect,
    ScreenPoint,
    ScreenRect,
    Viewport,
)

from .image import (
    Color,
    FrameImage,
    intersect_regions,
    probe_color,
    rect_to_normalized,
    resolve_point,
    resolve_region,
)
from .templates import VisionTemplate


class VisionDetector(Protocol):
    """Synchronous detector contract reused by detector runners."""

    @property
    def name(self) -> str: ...

    def detect(
        self,
        image: FrameImage,
        *,
        region: Rect,
        request: DetectionRequest,
    ) -> Iterable[Detection]: ...


@dataclass(frozen=True, slots=True)
class CompositeVisionDetector:
    """Simple detector fan-out for reusable detector composition."""

    detectors: tuple[VisionDetector, ...]
    detector_name: str = "composite"

    @property
    def name(self) -> str:
        return self.detector_name

    def detect(
        self,
        image: FrameImage,
        *,
        region: Rect,
        request: DetectionRequest,
    ) -> tuple[Detection, ...]:
        detections: list[Detection] = []
        for detector in self.detectors:
            detections.extend(detector.detect(image, region=region, request=request))
        return tuple(detections)


@dataclass(frozen=True, slots=True)
class PixelColorDetector:
    """Single-point color detector with optional detector-local ROI."""

    label: str
    point: ScreenPoint
    expected_color: Color
    tolerance: int = 0
    confidence: float = 1.0
    region: ScreenRect | None = None
    detector_name: str = "pixel-color"

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("label must be non-empty")
        if not self.expected_color:
            raise ValueError("expected_color must be non-empty")
        if self.tolerance < 0:
            raise ValueError("tolerance must be >= 0")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        if not self.detector_name.strip():
            raise ValueError("detector_name must be non-empty")

    @property
    def name(self) -> str:
        return self.detector_name

    def detect(
        self,
        image: FrameImage,
        *,
        region: Rect,
        request: DetectionRequest,
    ) -> tuple[Detection, ...]:
        point = resolve_point(
            self.point,
            Viewport(
                surface_size=image.size,
                region=_resolve_point_region(image, region, self.region),
            ),
        )
        if not _point_in_region(point, region):
            return ()
        if not probe_color(image, point, self.expected_color, tolerance=self.tolerance):
            return ()

        return (
            Detection(
                label=self.label,
                confidence=self.confidence,
                bounds=rect_to_normalized(
                    Rect(left=point.x, top=point.y, width=1, height=1),
                    image.size,
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class TemplateMatchingDetector:
    """ROI-first grayscale template matching over one or more templates."""

    templates: tuple[VisionTemplate, ...]
    detector_name: str = "template-matcher"

    def __post_init__(self) -> None:
        templates = tuple(self.templates)
        if not templates:
            raise ValueError("templates must be non-empty")
        if not self.detector_name.strip():
            raise ValueError("detector_name must be non-empty")
        object.__setattr__(self, "templates", templates)

    @property
    def name(self) -> str:
        return self.detector_name

    def detect(
        self,
        image: FrameImage,
        *,
        region: Rect,
        request: DetectionRequest,
    ) -> tuple[Detection, ...]:
        detections: list[Detection] = []
        for template in self.templates:
            if request.labels and template.label not in request.labels:
                continue

            search_region = _resolve_search_region(
                image,
                request_region=region,
                requested_region=request.region,
                template_region=template.region,
            )
            if search_region is None:
                continue

            match = _match_template(image, search_region, template)
            if match is None or match.confidence < template.min_confidence:
                continue
            detections.append(match)

        return tuple(detections)


def run_detector(
    detector: VisionDetector,
    frame: CapturedFrame,
    request: DetectionRequest | None = None,
) -> DetectionResult:
    resolved_request = request or DetectionRequest()
    image = FrameImage.from_captured_frame(frame)
    region = resolve_region(resolved_request.region, Viewport(surface_size=image.size))
    detections = tuple(detector.detect(image, region=region, request=resolved_request))
    filtered = _apply_request_filters(detections, resolved_request)
    return DetectionResult(
        detections=filtered,
        produced_at=datetime.now(UTC),
        frame_id=frame.metadata.frame_id,
        detector_name=detector.name,
    )


def _apply_request_filters(
    detections: tuple[Detection, ...], request: DetectionRequest
) -> tuple[Detection, ...]:
    filtered = tuple(
        detection
        for detection in detections
        if detection.confidence >= request.min_confidence
        and (not request.labels or detection.label in request.labels)
    )
    ordered = tuple(sorted(filtered, key=lambda detection: detection.confidence, reverse=True))
    if request.max_results is None:
        return ordered
    return ordered[: request.max_results]


def _resolve_point_region(
    image: FrameImage,
    base_region: Rect,
    region: ScreenRect | None,
) -> Rect:
    if region is None:
        return base_region
    return resolve_region(region, Viewport(surface_size=image.size))


def _point_in_region(point: Point, region: Rect) -> bool:
    return region.left <= point.x < region.right and region.top <= point.y < region.bottom


def _resolve_search_region(
    image: FrameImage,
    request_region: Rect,
    requested_region: ScreenRect | None,
    template_region: ScreenRect | None,
) -> Rect | None:
    full_frame_region = Rect(left=0, top=0, width=image.width, height=image.height)
    if (
        template_region is None
        and requested_region is None
        and request_region == full_frame_region
    ):
        return None
    if template_region is None:
        return request_region
    resolved_template_region = resolve_region(template_region, Viewport(surface_size=image.size))
    return intersect_regions(request_region, resolved_template_region)


def _match_template(
    image: FrameImage,
    search_region: Rect,
    template: VisionTemplate,
) -> Detection | None:
    search_image = image.crop(search_region)
    search_rows = search_image.to_grayscale_array()

    best_confidence = -1.0
    best_rect: Rect | None = None
    best_scale: float | None = None
    best_area = -1

    template_image = template.image.to_pil_image().convert("L")
    for scale in template.scales:
        scaled_template = _scaled_template_image(template_image, scale)
        if (
            scaled_template.width > search_region.width
            or scaled_template.height > search_region.height
        ):
            continue

        confidence, offset = _best_template_match(search_rows, scaled_template)
        scaled_area = scaled_template.width * scaled_template.height
        if confidence < best_confidence:
            continue
        if confidence == best_confidence and scaled_area <= best_area:
            continue

        best_confidence = confidence
        best_scale = scale
        best_area = scaled_area
        best_rect = Rect(
            left=search_region.left + offset.x,
            top=search_region.top + offset.y,
            width=scaled_template.width,
            height=scaled_template.height,
        )

    if best_rect is None or best_scale is None:
        return None

    attributes = dict(template.attributes)
    attributes["scale"] = f"{best_scale:g}"
    return Detection(
        label=template.label,
        confidence=best_confidence,
        bounds=rect_to_normalized(best_rect, image.size),
        attributes=attributes,
    )


def _scaled_template_image(template_image: Image.Image, scale: float) -> Image.Image:
    width = max(1, round(template_image.width * scale))
    height = max(1, round(template_image.height * scale))
    if width == template_image.width and height == template_image.height:
        return template_image
    return template_image.resize((width, height), Image.Resampling.NEAREST)


def _best_template_match(
    search_rows: tuple[tuple[int, ...], ...],
    template_image: Image.Image,
) -> tuple[float, Point]:
    template_rows = _grayscale_rows(template_image)
    template_height = len(template_rows)
    template_width = len(template_rows[0])
    max_error = 255 * template_width * template_height

    best_error = max_error + 1
    best_point = Point(x=0, y=0)

    # Exhaustive grayscale SAD matching keeps the implementation dependency-light.
    for top in range(len(search_rows) - template_height + 1):
        for left in range(len(search_rows[0]) - template_width + 1):
            error = 0
            for template_y, template_row in enumerate(template_rows):
                search_row = search_rows[top + template_y]
                for template_x, template_value in enumerate(template_row):
                    error += abs(search_row[left + template_x] - template_value)
                if error >= best_error:
                    break

            if error < best_error:
                best_error = error
                best_point = Point(x=left, y=top)

    confidence = 1.0 - (best_error / max_error)
    return confidence, best_point


def _grayscale_rows(image: Image.Image) -> tuple[tuple[int, ...], ...]:
    rows: list[tuple[int, ...]] = []
    for y in range(image.height):
        row: list[int] = []
        for x in range(image.width):
            row.append(cast(int, image.getpixel((x, y))))
        rows.append(tuple(row))
    return tuple(rows)
