"""OpenCV preview window adapter and frame conversion helpers."""

from __future__ import annotations

from typing import Protocol

import numpy as np
import numpy.typing as npt
from android_game_automator.image import FrameImage
from android_game_automator.types import PixelFormat

EXIT_KEY_CODES = frozenset((27, ord("q")))

type BgrArray = npt.NDArray[np.uint8]


class PreviewWindow(Protocol):
    """OpenCV-like preview window operations used by the read-only loop."""

    def open(self, window_title: str) -> None: ...

    def show(self, window_title: str, frame: FrameImage) -> None: ...

    def wait_key(self, delay_ms: int) -> int: ...

    def close(self, window_title: str) -> None: ...


class OpenCvPreviewWindow:
    """Small OpenCV HighGUI adapter for displaying SDK ``FrameImage`` frames."""

    def open(self, window_title: str) -> None:
        import cv2

        cv2.namedWindow(window_title, cv2.WINDOW_NORMAL)

    def show(self, window_title: str, frame: FrameImage) -> None:
        import cv2

        cv2.imshow(window_title, frame_image_to_bgr_array(frame))

    def wait_key(self, delay_ms: int) -> int:
        import cv2

        return int(cv2.waitKey(delay_ms) & 0xFF)

    def close(self, window_title: str) -> None:
        import cv2

        cv2.destroyWindow(window_title)


def frame_image_to_bgr_array(frame: FrameImage) -> BgrArray:
    """Convert SDK RGBA32 frame data into BGR pixels for ``cv2.imshow``."""

    if frame.pixel_format is not PixelFormat.RGBA32:
        raise ValueError("live preview expects RGBA32 FrameImage data")

    rgba = np.frombuffer(frame.data, dtype=np.uint8).reshape((frame.height, frame.width, 4))
    bgr = np.empty((frame.height, frame.width, 3), dtype=np.uint8)
    bgr[..., 0] = rgba[..., 2]
    bgr[..., 1] = rgba[..., 1]
    bgr[..., 2] = rgba[..., 0]
    return bgr


__all__ = [
    "EXIT_KEY_CODES",
    "OpenCvPreviewWindow",
    "PreviewWindow",
    "frame_image_to_bgr_array",
]
