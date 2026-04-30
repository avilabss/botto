"""Tests for the lightweight ROI-first vision foundation."""

from __future__ import annotations

from datetime import UTC, datetime

import android_game_automator.vision.detectors as vision_detectors
import pytest
from PIL import Image

from android_game_automator.core import (
    CapturedFrame,
    Detection,
    DetectionRequest,
    FrameMetadata,
    NormalizedPoint,
    NormalizedRect,
    PixelFormat,
    Point,
    Rect,
    Size,
    Viewport,
)
from android_game_automator.vision import (
    CompositeVisionDetector,
    FrameImage,
    PixelColorDetector,
    TemplateMatchingDetector,
    VisionTemplate,
    frame_image_from_captured_frame,
    intersect_regions,
    pixel_color_matches,
    probe_color,
    rect_to_normalized,
    resolve_point,
    resolve_region,
    run_detector,
)


def test_frame_image_converts_captured_frame_into_pixel_array() -> None:
    image = frame_image_from_captured_frame(_rgba_frame())

    assert image.width == 2
    assert image.height == 2
    assert image.pixel(Point(x=1, y=0)) == (0, 255, 0, 255)
    assert image.to_array() == (
        ((255, 0, 0, 255), (0, 255, 0, 255)),
        ((0, 0, 255, 255), (255, 255, 0, 255)),
    )


def test_resolve_region_and_crop_support_normalized_and_absolute_rois() -> None:
    image = frame_image_from_captured_frame(_rgba_frame())
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
    image = frame_image_from_captured_frame(_rgba_frame())

    assert resolve_point(
        NormalizedPoint(x=1.0, y=1.0),
        Viewport(surface_size=image.size),
    ) == Point(x=1, y=1)
    assert probe_color(image, Point(x=0, y=0), (254, 1, 0, 255), tolerance=1)
    assert not probe_color(image, Point(x=0, y=0), (250, 0, 0, 255), tolerance=1)
    assert pixel_color_matches((10, 20, 30), (12, 18, 31), tolerance=2)

    with pytest.raises(ValueError):
        pixel_color_matches((1, 2, 3), (1, 2), tolerance=0)


def test_pixel_color_detector_respects_request_roi_and_filters() -> None:
    frame = _rgba_frame(frame_id="frame-vision")
    detector = PixelColorDetector(
        label="coin",
        point=NormalizedPoint(x=0.5, y=1.0),
        expected_color=(0, 0, 255, 255),
        region=NormalizedRect(left=0.0, top=0.5, width=0.5, height=0.5),
        confidence=0.8,
    )

    result = run_detector(
        detector,
        frame,
        DetectionRequest(
            labels=("coin",),
            min_confidence=0.7,
            region=Rect(left=0, top=1, width=1, height=1),
        ),
    )

    assert result.frame_id == "frame-vision"
    assert result.detector_name == "pixel-color"
    assert len(result.detections) == 1
    assert result.detections[0].label == "coin"
    assert result.detections[0].bounds == NormalizedRect(
        left=0.0,
        top=0.5,
        width=0.5,
        height=0.5,
    )

    filtered = run_detector(detector, frame, DetectionRequest(labels=("enemy",)))
    assert filtered.detections == ()


def test_pixel_color_detector_resolves_detector_roi_before_request_roi() -> None:
    frame = _rgba_frame()
    detector = PixelColorDetector(
        label="green",
        point=NormalizedPoint(x=1.0, y=0.0),
        expected_color=(0, 255, 0, 255),
        region=NormalizedRect(left=0.5, top=0.0, width=0.5, height=0.5),
    )

    result = run_detector(
        detector,
        frame,
        DetectionRequest(region=Rect(left=1, top=0, width=1, height=1)),
    )

    assert [detection.label for detection in result.detections] == ["green"]


def test_pixel_color_detector_keeps_detector_local_point_space_with_subset_request_roi() -> None:
    frame = _rgba_frame()
    detector = PixelColorDetector(
        label="green",
        point=NormalizedPoint(x=1.0, y=0.0),
        expected_color=(0, 255, 0, 255),
        region=NormalizedRect(left=0.0, top=0.0, width=1.0, height=0.5),
    )

    result = run_detector(
        detector,
        frame,
        DetectionRequest(region=Rect(left=1, top=0, width=1, height=1)),
    )

    assert [detection.label for detection in result.detections] == ["green"]


def test_pixel_color_detector_returns_no_detections_for_non_overlapping_rois() -> None:
    frame = _rgba_frame()
    detector = PixelColorDetector(
        label="green",
        point=NormalizedPoint(x=0.0, y=0.0),
        expected_color=(0, 255, 0, 255),
        region=NormalizedRect(left=0.5, top=0.0, width=0.5, height=0.5),
    )

    result = run_detector(
        detector,
        frame,
        DetectionRequest(region=Rect(left=0, top=1, width=1, height=1)),
    )

    assert result.detections == ()


def test_rect_to_normalized_round_trips_edge_aligned_rects() -> None:
    size = Size(width=3, height=3)
    rect = Rect(left=1, top=1, width=2, height=2)
    normalized = rect_to_normalized(rect, size)

    assert normalized.left == pytest.approx(1 / 3)
    assert normalized.top == pytest.approx(1 / 3)
    assert normalized.right == pytest.approx(1.0)
    assert normalized.bottom == pytest.approx(1.0)
    assert Viewport(surface_size=size).map_rect(normalized) == rect


def test_intersect_regions_excludes_non_overlapping_request_and_detector_rois() -> None:
    assert (
        intersect_regions(
            Rect(left=0, top=0, width=1, height=1),
            Rect(left=1, top=1, width=1, height=1),
        )
        is None
    )


def test_composite_detector_combines_and_limits_results() -> None:
    frame = _rgba_frame()
    detector = CompositeVisionDetector(
        detectors=(
            PixelColorDetector(
                label="red",
                point=Point(x=0, y=0),
                expected_color=(255, 0, 0, 255),
                confidence=0.9,
            ),
            PixelColorDetector(
                label="green",
                point=Point(x=1, y=0),
                expected_color=(0, 255, 0, 255),
                confidence=0.6,
            ),
        )
    )

    result = run_detector(
        detector,
        frame,
        DetectionRequest(min_confidence=0.5, max_results=1),
    )

    assert result.detector_name == "composite"
    assert [detection.label for detection in result.detections] == ["red"]


def test_template_matching_detector_finds_exact_match() -> None:
    frame = _template_scene_frame(scale=1)
    detector = TemplateMatchingDetector(
        templates=(
            VisionTemplate(
                label="badge",
                image=_template_image(),
                min_confidence=0.99,
            ),
        )
    )

    result = run_detector(
        detector,
        frame,
        DetectionRequest(region=Rect(left=0, top=0, width=5, height=5)),
    )

    assert result.detector_name == "template-matcher"
    assert len(result.detections) == 1
    detection = result.detections[0]
    assert detection.label == "badge"
    assert detection.confidence == pytest.approx(1.0)
    assert detection.bounds is not None
    assert detection.bounds.left == pytest.approx(1 / 5)
    assert detection.bounds.top == pytest.approx(1 / 5)
    assert detection.bounds.width == pytest.approx(2 / 5)
    assert detection.bounds.height == pytest.approx(2 / 5)
    assert detection.attributes["scale"] == "1"


def test_template_matching_detector_supports_scaled_matches() -> None:
    frame = _template_scene_frame(scale=2)
    detector = TemplateMatchingDetector(
        templates=(
            VisionTemplate(
                label="badge",
                image=_template_image(),
                min_confidence=0.99,
                scales=(1.0, 2.0),
            ),
        )
    )

    result = run_detector(
        detector,
        frame,
        DetectionRequest(region=Rect(left=0, top=0, width=5, height=5)),
    )

    assert len(result.detections) == 1
    detection = result.detections[0]
    assert detection.confidence == pytest.approx(1.0)
    assert detection.bounds is not None
    assert detection.bounds.left == pytest.approx(1 / 5)
    assert detection.bounds.top == pytest.approx(1 / 5)
    assert detection.bounds.width == pytest.approx(4 / 5)
    assert detection.bounds.height == pytest.approx(4 / 5)
    assert detection.attributes["scale"] == "2"


def test_template_matching_detector_filters_below_template_threshold() -> None:
    frame = _template_scene_frame(scale=1, altered=True)
    detector = TemplateMatchingDetector(
        templates=(
            VisionTemplate(
                label="badge",
                image=_template_image(),
                min_confidence=0.95,
            ),
        )
    )

    result = run_detector(
        detector,
        frame,
        DetectionRequest(region=Rect(left=0, top=0, width=5, height=5)),
    )

    assert result.detections == ()


def test_template_matching_detector_requires_explicit_full_frame_opt_in() -> None:
    frame = _template_scene_frame(scale=1)
    detector = TemplateMatchingDetector(
        templates=(
            VisionTemplate(
                label="badge",
                image=_template_image(),
                min_confidence=0.99,
            ),
        )
    )

    assert run_detector(detector, frame).detections == ()


def test_template_matching_detector_treats_direct_subset_region_as_explicit_roi() -> None:
    frame = _template_scene_frame(scale=1)
    image = FrameImage.from_captured_frame(frame)
    detector = TemplateMatchingDetector(
        templates=(
            VisionTemplate(
                label="badge",
                image=_template_image(),
                min_confidence=0.99,
            ),
        )
    )

    detections = detector.detect(
        image,
        region=Rect(left=1, top=1, width=3, height=3),
        request=DetectionRequest(),
    )

    assert [detection.label for detection in detections] == ["badge"]


def test_template_matching_detector_respects_request_and_template_rois() -> None:
    frame = _template_scene_frame(scale=1)
    detector = TemplateMatchingDetector(
        templates=(
            VisionTemplate(
                label="badge",
                image=_template_image(),
                min_confidence=0.99,
                region=Rect(left=0, top=0, width=1, height=1),
            ),
        )
    )

    assert run_detector(detector, frame).detections == ()

    detector = TemplateMatchingDetector(
        templates=(
            VisionTemplate(
                label="badge",
                image=_template_image(),
                min_confidence=0.99,
                region=Rect(left=1, top=1, width=3, height=3),
            ),
        )
    )

    result = run_detector(
        detector,
        frame,
        DetectionRequest(region=Rect(left=1, top=1, width=3, height=3)),
    )

    assert [detection.label for detection in result.detections] == ["badge"]


def test_template_matching_detector_applies_request_labels_before_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _template_scene_frame(scale=1)
    detector = TemplateMatchingDetector(
        templates=(
            VisionTemplate(
                label="skip",
                image=_template_image(),
                min_confidence=0.99,
                region=Rect(left=0, top=0, width=5, height=5),
            ),
            VisionTemplate(
                label="badge",
                image=_template_image(),
                min_confidence=0.99,
                region=Rect(left=0, top=0, width=5, height=5),
            ),
        )
    )
    matched_labels: list[str] = []

    def fake_match(
        image: FrameImage,
        search_region: Rect,
        template: VisionTemplate,
    ) -> Detection:
        del image, search_region
        matched_labels.append(template.label)
        return Detection(label=template.label, confidence=1.0)

    monkeypatch.setattr(vision_detectors, "_match_template", fake_match)

    result = run_detector(detector, frame, DetectionRequest(labels=("badge",)))

    assert matched_labels == ["badge"]
    assert [detection.label for detection in result.detections] == ["badge"]


def test_template_matching_detector_sorts_by_confidence_before_max_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _template_scene_frame(scale=1)
    detector = TemplateMatchingDetector(
        templates=(
            VisionTemplate(
                label="weaker",
                image=_template_image(),
                min_confidence=0.5,
                region=Rect(left=0, top=0, width=5, height=5),
            ),
            VisionTemplate(
                label="stronger",
                image=_template_image(),
                min_confidence=0.5,
                region=Rect(left=0, top=0, width=5, height=5),
            ),
        )
    )

    def fake_match(
        image: FrameImage,
        search_region: Rect,
        template: VisionTemplate,
    ) -> Detection:
        del image, search_region
        return Detection(
            label=template.label,
            confidence=0.6 if template.label == "weaker" else 0.9,
        )

    monkeypatch.setattr(vision_detectors, "_match_template", fake_match)

    result = run_detector(
        detector,
        frame,
        DetectionRequest(max_results=1, region=Rect(left=0, top=0, width=5, height=5)),
    )

    assert [detection.label for detection in result.detections] == ["stronger"]


def _rgba_frame(*, frame_id: str | None = None) -> CapturedFrame:
    return CapturedFrame(
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
        metadata=FrameMetadata(
            size=Size(width=2, height=2),
            captured_at=datetime.now(UTC),
            pixel_format=PixelFormat.RGBA32,
            frame_id=frame_id,
        ),
    )


def _template_image() -> FrameImage:
    image = Image.new("RGBA", (2, 2), (20, 20, 20, 255))
    image.putpixel((0, 0), (255, 255, 255, 255))
    image.putpixel((1, 1), (255, 255, 255, 255))
    return FrameImage.from_pil_image(image)


def _template_scene_frame(*, scale: int, altered: bool = False) -> CapturedFrame:
    template = _template_image().to_pil_image()
    scaled = template.resize(
        (template.width * scale, template.height * scale),
        Image.Resampling.NEAREST,
    )
    scene = Image.new("RGBA", (5, 5), (20, 20, 20, 255))
    scene.paste(scaled, (1, 1))
    if altered:
        scene.putpixel((1, 1), (20, 20, 20, 255))

    return CapturedFrame(
        data=scene.tobytes(),
        metadata=FrameMetadata(
            size=Size(width=scene.width, height=scene.height),
            captured_at=datetime.now(UTC),
            pixel_format=PixelFormat.RGBA32,
        ),
    )
