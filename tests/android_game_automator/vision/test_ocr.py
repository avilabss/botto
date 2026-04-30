"""Tests for function-first OCR helpers."""

from __future__ import annotations

from typing import Any

import android_game_automator.ocr as ocr_module
import pytest
from android_game_automator.image import FrameImage
from android_game_automator.ocr import (
    OcrPreprocessConfig,
    preprocess_ocr_region,
    read_text,
    read_text_blocks,
)
from android_game_automator.types import NormalizedRect, Rect, Size, TextBlock
from PIL import Image

_NO_PREPROCESS = OcrPreprocessConfig(scale=1, threshold=None)


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


def test_read_text_blocks_maps_roi_local_bounds_back_to_source_image(monkeypatch) -> None:  # noqa: ANN001
    captured_shapes: list[tuple[int, ...]] = []

    def fake_recognizer(payload: Any) -> tuple[list[list[Any]], float]:
        captured_shapes.append(payload.shape)
        return (
            [
                [
                    [[2, 0], [4, 0], [4, 4], [2, 4]],
                    "  gold  ",
                    0.9,
                ],
                ["ready", 0.8],
            ],
            0.01,
        )

    monkeypatch.setattr(ocr_module, "_rapidocr_recognizer", fake_recognizer)
    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))

    blocks = read_text_blocks(image, region=Rect(left=1, top=1, width=2, height=2))

    assert captured_shapes == [(4, 4, 3)]
    assert [block.text for block in blocks] == ["gold", "ready"]
    assert blocks[0].confidence == pytest.approx(0.9)
    assert blocks[0].bounds == NormalizedRect(
        left=0.5,
        top=0.25,
        width=0.25,
        height=0.5,
    )
    assert blocks[1].bounds is None


def test_read_text_uses_full_image_when_region_is_omitted(monkeypatch) -> None:  # noqa: ANN001
    captured_shapes: list[tuple[int, ...]] = []

    def fake_recognizer(payload: Any) -> tuple[list[list[Any]], float]:
        captured_shapes.append(payload.shape)
        return (
            [
                ["  Play  ", 0.88],
                ["Ready", 0.75],
            ],
            0.01,
        )

    monkeypatch.setattr(ocr_module, "_rapidocr_recognizer", fake_recognizer)
    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))

    text = read_text(image, preprocess=_NO_PREPROCESS)

    assert text == "Play\nReady"
    assert captured_shapes == [(4, 4, 3)]


def test_rapidocr_payload_normalizes_detected_text(monkeypatch) -> None:  # noqa: ANN001
    blocks = _read_blocks_from_payload(
        monkeypatch,
        [
            [
                [[1, 1], [3, 1], [3, 2], [1, 2]],
                "  Play  ",
                0.88,
            ],
            [None, "", 0.7],
        ],
    )

    assert len(blocks) == 1
    assert blocks[0].text == "Play"
    assert blocks[0].confidence == pytest.approx(0.88)
    assert blocks[0].bounds == NormalizedRect(left=0.25, top=0.25, width=0.5, height=0.25)


def test_rapidocr_payload_accepts_recognition_only_payload(monkeypatch) -> None:  # noqa: ANN001
    blocks = _read_blocks_from_payload(
        monkeypatch,
        [
            ["  Ready  ", 0.73],
            ["", 0.91],
        ],
    )

    assert len(blocks) == 1
    assert blocks[0].text == "Ready"
    assert blocks[0].confidence == pytest.approx(0.73)
    assert blocks[0].bounds is None


def test_rapidocr_payload_accepts_short_recognition_only_payload(monkeypatch) -> None:  # noqa: ANN001
    blocks = _read_blocks_from_payload(
        monkeypatch,
        [
            ["OK", 0.82],
            ["", 0.91],
        ],
    )

    assert len(blocks) == 1
    assert blocks[0].text == "OK"
    assert blocks[0].confidence == pytest.approx(0.82)
    assert blocks[0].bounds is None


def test_rapidocr_payload_skips_detection_only_payload(monkeypatch) -> None:  # noqa: ANN001
    blocks = _read_blocks_from_payload(
        monkeypatch,
        [
            [[1, 1], [3, 1], [3, 2], [1, 2]],
            [[[0, 0], [2, 0], [2, 1], [0, 1]], "Fight", 0.84],
        ],
    )

    assert len(blocks) == 1
    assert blocks[0].text == "Fight"
    assert blocks[0].confidence == pytest.approx(0.84)
    assert blocks[0].bounds == NormalizedRect(left=0.0, top=0.0, width=0.5, height=0.25)


def test_rapidocr_payload_skips_non_string_text_payloads(monkeypatch) -> None:  # noqa: ANN001
    blocks = _read_blocks_from_payload(
        monkeypatch,
        [
            [None, 0.73],
            [[[0, 0], [2, 0], [2, 1], [0, 1]], None, 0.84],
            ["Ready", 0.91],
        ],
    )

    assert len(blocks) == 1
    assert blocks[0].text == "Ready"
    assert blocks[0].confidence == pytest.approx(0.91)
    assert blocks[0].bounds is None


def test_rapidocr_payload_treats_non_numeric_confidence_as_unavailable(monkeypatch) -> None:  # noqa: ANN001
    blocks = _read_blocks_from_payload(
        monkeypatch,
        [
            ["Ready", "high"],
        ],
    )

    assert len(blocks) == 1
    assert blocks[0].text == "Ready"
    assert blocks[0].confidence is None
    assert blocks[0].bounds is None


def test_rapidocr_payload_treats_non_numeric_box_coordinates_as_unavailable(monkeypatch) -> None:  # noqa: ANN001
    blocks = _read_blocks_from_payload(
        monkeypatch,
        [
            [[[0, 0], [2, "x"], [2, 1], [0, 1]], "Fight", 0.84],
        ],
    )

    assert len(blocks) == 1
    assert blocks[0].text == "Fight"
    assert blocks[0].confidence == pytest.approx(0.84)
    assert blocks[0].bounds is None


def test_rapidocr_payload_treats_non_finite_box_coordinates_as_unavailable(monkeypatch) -> None:  # noqa: ANN001
    blocks = _read_blocks_from_payload(
        monkeypatch,
        [
            [[[0, 0], [2, float("nan")], [2, 1], [0, 1]], "Fight", 0.84],
            [[[0, 0], [2, float("inf")], [2, 1], [0, 1]], "Ready", 0.91],
        ],
    )

    assert len(blocks) == 2
    assert blocks[0].text == "Fight"
    assert blocks[0].confidence == pytest.approx(0.84)
    assert blocks[0].bounds is None
    assert blocks[1].text == "Ready"
    assert blocks[1].confidence == pytest.approx(0.91)
    assert blocks[1].bounds is None


def _read_blocks_from_payload(monkeypatch, raw_result: Any) -> tuple[TextBlock, ...]:  # noqa: ANN001
    def fake_recognizer(_payload: Any) -> tuple[Any, float]:
        return raw_result, 0.01

    monkeypatch.setattr(ocr_module, "_rapidocr_recognizer", fake_recognizer)
    image = FrameImage.from_pil_image(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    return read_text_blocks(image, preprocess=_NO_PREPROCESS)
