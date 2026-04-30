"""ROI-first vision helpers and reusable detector plumbing."""

from .detectors import (
    CompositeVisionDetector,
    PixelColorDetector,
    TemplateMatchingDetector,
    VisionDetector,
    run_detector,
)
from .image import (
    Color,
    FrameImage,
    channel_count,
    crop_image,
    frame_image_from_captured_frame,
    intersect_regions,
    pixel_color_matches,
    probe_color,
    rect_to_normalized,
    resolve_point,
    resolve_region,
)
from .ocr import (
    OcrEngine,
    OcrPreprocessConfig,
    OcrResult,
    OcrService,
    RapidOcrEngine,
    RecognizedText,
    preprocess_ocr_region,
)
from .templates import VisionTemplate

__all__ = [
    "Color",
    "CompositeVisionDetector",
    "FrameImage",
    "OcrEngine",
    "OcrPreprocessConfig",
    "OcrResult",
    "OcrService",
    "PixelColorDetector",
    "RapidOcrEngine",
    "RecognizedText",
    "TemplateMatchingDetector",
    "VisionDetector",
    "VisionTemplate",
    "channel_count",
    "crop_image",
    "frame_image_from_captured_frame",
    "intersect_regions",
    "pixel_color_matches",
    "probe_color",
    "preprocess_ocr_region",
    "rect_to_normalized",
    "resolve_point",
    "resolve_region",
    "run_detector",
]
