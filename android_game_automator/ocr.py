"""Function-first OCR helpers backed by RapidOCR."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps

from android_game_automator.image import FrameImage, rect_to_normalized, resolve_region
from android_game_automator.types import NormalizedRect, Rect, ScreenRect, Size, TextBlock, Viewport


@dataclass(frozen=True, slots=True)
class OcrPreprocessConfig:
    """Minimal OCR-focused preprocessing controls for ROI reads."""

    scale: int = 2
    threshold: int | None = 180
    invert: bool = False

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise ValueError("scale must be > 0")
        if self.threshold is not None and not 0 <= self.threshold <= 255:
            raise ValueError("threshold must be within [0, 255] when provided")


_rapidocr_recognizer: Any | None = None


def read_text(
    image: FrameImage,
    *,
    region: ScreenRect | None = None,
    preprocess: OcrPreprocessConfig | None = None,
) -> str:
    """Read OCR text from an image or optional ROI."""

    return "\n".join(
        block.text for block in read_text_blocks(image, region=region, preprocess=preprocess)
    )


def read_text_blocks(
    image: FrameImage,
    *,
    region: ScreenRect | None = None,
    preprocess: OcrPreprocessConfig | None = None,
) -> tuple[TextBlock, ...]:
    """Read OCR text blocks from an image or optional ROI."""

    source_region = resolve_region(region, Viewport(surface_size=image.size))
    prepared = preprocess_ocr_region(
        image.crop(source_region),
        preprocess,
    )
    return tuple(
        _map_text_block_bounds(block, source_region, image.size)
        for block in _recognize_text_blocks(prepared)
    )


def preprocess_ocr_region(
    image: FrameImage,
    config: OcrPreprocessConfig | None = None,
) -> FrameImage:
    """Prepare a cropped ROI for OCR-oriented reads."""

    resolved_config = config or OcrPreprocessConfig()
    prepared = image.to_pil_image().convert("L")
    if resolved_config.scale != 1:
        prepared = prepared.resize(
            (
                prepared.width * resolved_config.scale,
                prepared.height * resolved_config.scale,
            ),
            Image.Resampling.BICUBIC,
        )
    if resolved_config.threshold is not None:
        prepared = prepared.point(
            lambda value: 255 if value >= resolved_config.threshold else 0,
            mode="L",
        )
    if resolved_config.invert:
        prepared = ImageOps.invert(prepared)
    return FrameImage.from_pil_image(prepared)


def _map_text_block_bounds(
    block: TextBlock,
    source_region: Rect,
    source_size: Size,
) -> TextBlock:
    if block.bounds is None:
        return block

    mapped_rect = Viewport(surface_size=source_size, region=source_region).map_rect(block.bounds)
    return TextBlock(
        text=block.text,
        confidence=block.confidence,
        bounds=rect_to_normalized(mapped_rect, source_size),
    )


def _recognize_text_blocks(image: FrameImage) -> tuple[TextBlock, ...]:
    numpy = _require_numpy()
    recognizer = _get_rapidocr_recognizer()
    payload = _frame_image_to_rgb_numpy_array(image, numpy)
    raw_result = recognizer(payload)

    blocks: list[TextBlock] = []
    for entry in _rapidocr_entries(raw_result):
        block = _parse_rapidocr_entry(entry, image.size)
        if block is not None:
            blocks.append(block)
    return tuple(blocks)


def _frame_image_to_rgb_numpy_array(image: FrameImage, numpy: Any) -> Any:
    source = image.to_pil_image()
    try:
        rgb = source.convert("RGB")
        try:
            return numpy.array(rgb)
        finally:
            rgb.close()
    finally:
        source.close()


def _get_rapidocr_recognizer() -> Any:
    global _rapidocr_recognizer

    if _rapidocr_recognizer is None:
        _rapidocr_recognizer = _create_rapidocr_recognizer()
    return _rapidocr_recognizer


def _create_rapidocr_recognizer() -> Any:
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "OCR requires RapidOCR; install 'rapidocr-onnxruntime' to use read_text"
        ) from exc

    try:
        return RapidOCR()
    except Exception as exc:
        raise RuntimeError(
            "OCR requires RapidOCR; failed to initialize 'rapidocr-onnxruntime'"
        ) from exc


def _require_numpy() -> Any:
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError(
            "OCR requires RapidOCR and NumPy; install 'rapidocr-onnxruntime' to use read_text"
        ) from exc
    return numpy


def _rapidocr_entries(raw_result: Any) -> Iterable[Any]:
    if isinstance(raw_result, tuple) and len(raw_result) == 2:
        entries = raw_result[0]
    else:
        entries = raw_result

    if entries is None:
        return ()
    if isinstance(entries, (str, bytes)) or not isinstance(entries, Iterable):
        return ()
    return entries


def _parse_rapidocr_entry(entry: Any, size: Size) -> TextBlock | None:
    if not _is_sequence(entry) or len(entry) < 2:
        return None
    if _is_box_like(entry):
        return None
    if len(entry) > 2 or _is_box_like(entry[0]):
        return _parse_detected_text_entry(entry, size)
    return _parse_recognition_text_entry(entry)


def _parse_detected_text_entry(entry: Sequence[Any], size: Size) -> TextBlock | None:
    text = _parse_rapidocr_text(entry[1])
    if text is None:
        return None

    confidence = _parse_confidence(entry[2]) if len(entry) > 2 else None
    return TextBlock(
        text=text,
        confidence=confidence,
        bounds=_rapidocr_box_to_normalized(entry[0], size),
    )


def _parse_recognition_text_entry(entry: Sequence[Any]) -> TextBlock | None:
    text = _parse_rapidocr_text(entry[0])
    if text is None:
        return None

    return TextBlock(text=text, confidence=_parse_confidence(entry[1]))


def _parse_rapidocr_text(raw_text: Any) -> str | None:
    if not isinstance(raw_text, str):
        return None
    text = raw_text.strip()
    if not text:
        return None
    return text


def _parse_confidence(raw_confidence: Any) -> float | None:
    if raw_confidence is None:
        return None
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        return None
    if 0.0 <= confidence <= 1.0:
        return confidence
    return None


def _rapidocr_box_to_normalized(raw_box: Any, size: Size) -> NormalizedRect | None:
    if not _is_box_like(raw_box):
        return None

    points: list[tuple[float, float]] = []
    for point in raw_box:
        try:
            x = float(point[0])
            y = float(point[1])
        except (TypeError, ValueError):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        points.append((x, y))

    left = max(0.0, min(point[0] for point in points))
    top = max(0.0, min(point[1] for point in points))
    right = min(float(size.width), max(point[0] for point in points))
    bottom = min(float(size.height), max(point[1] for point in points))
    if right <= left or bottom <= top:
        return None

    return NormalizedRect(
        left=left / size.width,
        top=top / size.height,
        width=(right - left) / size.width,
        height=(bottom - top) / size.height,
    )


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _is_box_like(value: Any) -> bool:
    if not _is_sequence(value) or not value:
        return False
    return all(_is_sequence(point) and len(point) == 2 for point in value)


__all__ = [
    "OcrPreprocessConfig",
    "preprocess_ocr_region",
    "read_text",
    "read_text_blocks",
]
