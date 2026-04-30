"""Tests for ROI-first OCR services and adapters."""

from __future__ import annotations

from typing import Any

import pytest
from android_game_automator.core import NormalizedRect, Rect, Size
from android_game_automator.vision import (
    FrameImage,
    OcrPreprocessConfig,
    OcrService,
    RapidOcrEngine,
    RecognizedText,
    preprocess_ocr_region,
)
from PIL import Image


class _FakeOcrEngine:
    @property
    def name(self) -> str:
        return "fake-ocr"

    def recognize(self, image: FrameImage) -> tuple[RecognizedText, ...]:
        assert image.size == Size(width=4, height=4)
        return (
            RecognizedText(
                text="gold",
                confidence=0.9,
                bounds=NormalizedRect(left=0.5, top=0.0, width=0.5, height=1.0),
            ),
            RecognizedText(text="ready"),
        )


def test_preprocess_ocr_region_scales_thresholds_and_inverts() -> None:
    image = Image.new("L", (2, 1))
    image.putpixel((0, 0), 40)
    image.putpixel((1, 0), 200)

    processed = preprocess_ocr_region(
        FrameImage.from_pil_image(image),
        OcrPreprocessConfig(scale=2, threshold=128, invert=True),
    )

    assert processed.size == Size(width=4, height=2)
    assert processed.pixel_format.name == "GRAY8"
    assert processed.to_grayscale_array() == (
        (255, 255, 0, 0),
        (255, 255, 0, 0),
    )


def test_ocr_service_maps_roi_local_bounds_back_to_source_image() -> None:
    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    service = OcrService(engine=_FakeOcrEngine())

    result = service.read(image, region=Rect(left=1, top=1, width=2, height=2))

    assert result.engine_name == "fake-ocr"
    assert result.text == "gold\nready"
    assert result.texts[0].bounds == NormalizedRect(
        left=0.5,
        top=0.25,
        width=0.25,
        height=0.5,
    )
    assert result.texts[1].bounds is None


def test_rapid_ocr_engine_normalizes_backend_payload() -> None:
    captured_payloads: list[Any] = []

    def fake_recognizer(payload: Any) -> tuple[list[list[Any]], float]:
        captured_payloads.append(payload)
        return (
            [
                [
                    [[1, 1], [3, 1], [3, 2], [1, 2]],
                    "  Play  ",
                    0.88,
                ],
                [None, "", 0.7],
            ],
            0.01,
        )

    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    result = RapidOcrEngine(recognizer=fake_recognizer).recognize(image)

    assert len(captured_payloads) == 1
    assert len(result) == 1
    assert result[0].text == "Play"
    assert result[0].confidence == pytest.approx(0.88)
    assert result[0].bounds == NormalizedRect(left=0.25, top=0.25, width=0.5, height=0.25)


def test_rapid_ocr_engine_accepts_recognition_only_payload() -> None:
    def fake_recognizer(_payload: Any) -> tuple[list[list[Any]], float]:
        return (
            [
                ["  Ready  ", 0.73],
                ["", 0.91],
            ],
            0.01,
        )

    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    result = RapidOcrEngine(recognizer=fake_recognizer).recognize(image)

    assert len(result) == 1
    assert result[0].text == "Ready"
    assert result[0].confidence == pytest.approx(0.73)
    assert result[0].bounds is None


def test_rapid_ocr_engine_accepts_short_recognition_only_payload() -> None:
    def fake_recognizer(_payload: Any) -> tuple[list[list[Any]], float]:
        return (
            [
                ["OK", 0.82],
                ["", 0.91],
            ],
            0.01,
        )

    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    result = RapidOcrEngine(recognizer=fake_recognizer).recognize(image)

    assert len(result) == 1
    assert result[0].text == "OK"
    assert result[0].confidence == pytest.approx(0.82)
    assert result[0].bounds is None


def test_rapid_ocr_engine_skips_detection_only_payload() -> None:
    def fake_recognizer(_payload: Any) -> tuple[list[list[Any]], float]:
        return (
            [
                [[1, 1], [3, 1], [3, 2], [1, 2]],
                [[[0, 0], [2, 0], [2, 1], [0, 1]], "Fight", 0.84],
            ],
            0.01,
        )

    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    result = RapidOcrEngine(recognizer=fake_recognizer).recognize(image)

    assert len(result) == 1
    assert result[0].text == "Fight"
    assert result[0].confidence == pytest.approx(0.84)
    assert result[0].bounds == NormalizedRect(left=0.0, top=0.0, width=0.5, height=0.25)


def test_rapid_ocr_engine_skips_non_string_text_payloads() -> None:
    def fake_recognizer(_payload: Any) -> tuple[list[list[Any]], float]:
        return (
            [
                [None, 0.73],
                [[[0, 0], [2, 0], [2, 1], [0, 1]], None, 0.84],
                ["Ready", 0.91],
            ],
            0.01,
        )

    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    result = RapidOcrEngine(recognizer=fake_recognizer).recognize(image)

    assert len(result) == 1
    assert result[0].text == "Ready"
    assert result[0].confidence == pytest.approx(0.91)
    assert result[0].bounds is None


def test_rapid_ocr_engine_treats_non_numeric_confidence_as_unavailable() -> None:
    def fake_recognizer(_payload: Any) -> tuple[list[list[Any]], float]:
        return (
            [
                ["Ready", "high"],
            ],
            0.01,
        )

    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    result = RapidOcrEngine(recognizer=fake_recognizer).recognize(image)

    assert len(result) == 1
    assert result[0].text == "Ready"
    assert result[0].confidence is None
    assert result[0].bounds is None


def test_rapid_ocr_engine_treats_non_numeric_box_coordinates_as_unavailable() -> None:
    def fake_recognizer(_payload: Any) -> tuple[list[list[Any]], float]:
        return (
            [
                [[[0, 0], [2, "x"], [2, 1], [0, 1]], "Fight", 0.84],
            ],
            0.01,
        )

    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    result = RapidOcrEngine(recognizer=fake_recognizer).recognize(image)

    assert len(result) == 1
    assert result[0].text == "Fight"
    assert result[0].confidence == pytest.approx(0.84)
    assert result[0].bounds is None


def test_rapid_ocr_engine_treats_non_finite_box_coordinates_as_unavailable() -> None:
    def fake_recognizer(_payload: Any) -> tuple[list[list[Any]], float]:
        return (
            [
                [[[0, 0], [2, float("nan")], [2, 1], [0, 1]], "Fight", 0.84],
                [[[0, 0], [2, float("inf")], [2, 1], [0, 1]], "Ready", 0.91],
            ],
            0.01,
        )

    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    result = RapidOcrEngine(recognizer=fake_recognizer).recognize(image)

    assert len(result) == 2
    assert result[0].text == "Fight"
    assert result[0].confidence == pytest.approx(0.84)
    assert result[0].bounds is None
    assert result[1].text == "Ready"
    assert result[1].confidence == pytest.approx(0.91)
    assert result[1].bounds is None
