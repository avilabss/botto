"""ROI-first OCR services and adapters."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from PIL import Image, ImageOps

from android_game_automator.core import NormalizedRect, Rect, ScreenRect, Size, Viewport
from android_game_automator.core._immutables import freeze_mapping

from .image import FrameImage, rect_to_normalized, resolve_region


@dataclass(frozen=True, slots=True)
class RecognizedText:
    """Single OCR text segment recognized within an image or ROI."""

    text: str
    confidence: float | None = None
    bounds: NormalizedRect | None = None
    attributes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("text must be non-empty")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0] when provided")
        object.__setattr__(self, "attributes", freeze_mapping(self.attributes))


@dataclass(frozen=True, slots=True)
class OcrResult:
    """OCR output for a single ROI read."""

    texts: tuple[RecognizedText, ...]
    engine_name: str | None = None

    def __post_init__(self) -> None:
        texts = tuple(self.texts)
        object.__setattr__(self, "texts", texts)
        if self.engine_name is not None and not self.engine_name.strip():
            raise ValueError("engine_name must be non-empty when provided")

    @property
    def text(self) -> str:
        return "\n".join(text.text for text in self.texts)


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


class OcrEngine(Protocol):
    """Backend-agnostic OCR engine contract over a prepared ROI image."""

    @property
    def name(self) -> str: ...

    def recognize(self, image: FrameImage) -> Iterable[RecognizedText]: ...


@dataclass(frozen=True, slots=True)
class OcrService:
    """ROI-first OCR service that handles crop, preprocessing, and bounds mapping."""

    engine: OcrEngine
    preprocess_config: OcrPreprocessConfig = field(default_factory=OcrPreprocessConfig)

    def read(self, image: FrameImage, *, region: ScreenRect) -> OcrResult:
        source_region = resolve_region(region, Viewport(surface_size=image.size))
        prepared = preprocess_ocr_region(
            image.crop(source_region),
            self.preprocess_config,
        )
        texts = tuple(
            _map_recognized_text_bounds(text, source_region, image.size)
            for text in self.engine.recognize(prepared)
        )
        return OcrResult(texts=texts, engine_name=self.engine.name)


class RapidOcrEngine:
    """RapidOCR adapter that normalizes backend results into SDK OCR models."""

    def __init__(self, recognizer: Any | None = None) -> None:
        self._recognizer = recognizer or _create_rapidocr_recognizer()

    @property
    def name(self) -> str:
        return "rapidocr"

    def recognize(self, image: FrameImage) -> tuple[RecognizedText, ...]:
        numpy = _require_numpy()
        payload = numpy.array(image.to_pil_image().convert("RGB"))
        raw_result, _elapsed = self._recognizer(payload)
        if raw_result is None:
            return ()

        texts: list[RecognizedText] = []
        for entry in raw_result:
            recognized = _parse_rapidocr_entry(entry, image.size)
            if recognized is not None:
                texts.append(recognized)
        return tuple(texts)


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


def _map_recognized_text_bounds(
    text: RecognizedText,
    source_region: Rect,
    source_size: Size,
) -> RecognizedText:
    if text.bounds is None:
        return text

    mapped_rect = Viewport(surface_size=source_size, region=source_region).map_rect(text.bounds)
    return RecognizedText(
        text=text.text,
        confidence=text.confidence,
        bounds=rect_to_normalized(mapped_rect, source_size),
        attributes=text.attributes,
    )


def _create_rapidocr_recognizer() -> Any:
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "RapidOCR runtime is unavailable; install 'rapidocr-onnxruntime' to use OCR"
        ) from exc
    return RapidOCR()


def _require_numpy() -> Any:
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("NumPy is required to use the RapidOCR engine") from exc
    return numpy


def _parse_rapidocr_entry(entry: Any, size: Size) -> RecognizedText | None:
    if not isinstance(entry, Sequence) or len(entry) < 2:
        return None

    if _rapidocr_box_to_normalized(entry, size) is not None:
        return None

    if len(entry) > 2 or (
        isinstance(entry[0], Sequence) and not isinstance(entry[0], (str, bytes))
    ):
        text = _parse_rapidocr_text(entry[1])
        if not text:
            return None

        confidence = _parse_confidence(entry[2]) if len(entry) > 2 else None
        bounds = _rapidocr_box_to_normalized(entry[0], size)
        return RecognizedText(text=text, confidence=confidence, bounds=bounds)

    text = _parse_rapidocr_text(entry[0])
    if not text:
        return None

    confidence = _parse_confidence(entry[1])
    bounds = None
    return RecognizedText(text=text, confidence=confidence, bounds=bounds)


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
    if not isinstance(raw_box, Sequence) or isinstance(raw_box, (str, bytes)) or not raw_box:
        return None

    points: list[tuple[float, float]] = []
    for point in raw_box:
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) != 2:
            return None
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
