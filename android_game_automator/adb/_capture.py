"""ADB screenshot capture helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from struct import error as StructError
from struct import unpack_from
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from android_game_automator.image import FrameImage
from android_game_automator.types import PixelFormat, Size

from .errors import AdbFrameCaptureError

_RAW_SCREENCAP_HEADER_SIZE = 12
_RAW_SCREENCAP_BYTES_PER_PIXEL_32 = 4
_ANDROID_PIXEL_FORMAT_RGBA_8888 = 1
_ANDROID_PIXEL_FORMAT_RGBX_8888 = 2


def decode_screencap_raw(
    raw_bytes: bytes,
    *,
    capture_strategy: str = "adbutils-raw",
) -> FrameImage:
    """Decode raw adb screencap bytes into the SDK image model."""
    if len(raw_bytes) < _RAW_SCREENCAP_HEADER_SIZE:
        raise AdbFrameCaptureError("ADB raw screencap output is too short.")

    try:
        width, height, android_pixel_format = unpack_from("<III", raw_bytes)
    except StructError as exc:
        raise AdbFrameCaptureError("Unable to parse adb raw screencap header.") from exc

    if width <= 0 or height <= 0:
        raise AdbFrameCaptureError("ADB raw screencap dimensions must be positive.")
    if android_pixel_format not in {
        _ANDROID_PIXEL_FORMAT_RGBA_8888,
        _ANDROID_PIXEL_FORMAT_RGBX_8888,
    }:
        raise AdbFrameCaptureError(
            f"Unsupported adb raw screencap pixel format: {android_pixel_format}."
        )

    expected_pixel_length = width * height * _RAW_SCREENCAP_BYTES_PER_PIXEL_32
    actual_pixel_length = len(raw_bytes) - _RAW_SCREENCAP_HEADER_SIZE
    if actual_pixel_length != expected_pixel_length:
        raise AdbFrameCaptureError(
            "ADB raw screencap byte length does not match dimensions and pixel format."
        )

    pixel_bytes = raw_bytes[_RAW_SCREENCAP_HEADER_SIZE:]
    if android_pixel_format == _ANDROID_PIXEL_FORMAT_RGBX_8888:
        rgba_bytes = bytearray(pixel_bytes)
        rgba_bytes[3::4] = b"\xff" * (width * height)
        pixel_bytes = bytes(rgba_bytes)

    return FrameImage(
        size=Size(width=width, height=height),
        pixel_format=PixelFormat.RGBA32,
        data=pixel_bytes,
        captured_at=datetime.now(UTC),
        frame_id=_capture_frame_id(capture_strategy),
    )


def decode_screencap_png(
    png_bytes: bytes,
    *,
    capture_strategy: str = "adbutils-png",
) -> FrameImage:
    """Decode an adb screencap PNG into the SDK image model."""
    if not png_bytes:
        raise AdbFrameCaptureError("ADB screencap returned empty output.")

    try:
        with Image.open(BytesIO(png_bytes)) as image:
            rgba_image = image.convert("RGBA")
            try:
                return FrameImage(
                    size=Size(width=rgba_image.width, height=rgba_image.height),
                    pixel_format=PixelFormat.RGBA32,
                    data=rgba_image.tobytes(),
                    captured_at=datetime.now(UTC),
                    frame_id=_capture_frame_id(capture_strategy),
                )
            finally:
                rgba_image.close()
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise AdbFrameCaptureError("Unable to decode adb screencap PNG output.") from exc


def normalize_shell_screencap_output(output: bytes) -> bytes:
    """Fix newline mangling from adb shell fallback screencap output."""
    return output.replace(b"\r\n", b"\n")


def _capture_frame_id(capture_strategy: str) -> str:
    return f"adb-frame:{capture_strategy}:{uuid4().hex}"
