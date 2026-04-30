"""ADB screenshot capture helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from android_game_automator.image import FrameImage
from android_game_automator.types import PixelFormat, Size

from .errors import AdbFrameCaptureError


def decode_screencap_png(png_bytes: bytes) -> FrameImage:
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
                    frame_id=f"adb-frame:{uuid4().hex}",
                )
            finally:
                rgba_image.close()
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise AdbFrameCaptureError("Unable to decode adb screencap PNG output.") from exc


def normalize_shell_screencap_output(output: bytes) -> bytes:
    """Fix newline mangling from adb shell fallback screencap output."""
    return output.replace(b"\r\n", b"\n")
