"""ADB screenshot capture helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from android_game_automator.core import CapturedFrame, FrameMetadata, PixelFormat, Size

from .errors import AdbFrameCaptureError


def decode_screencap_png(png_bytes: bytes) -> CapturedFrame:
    """Decode an adb screencap PNG into the SDK frame model."""
    if not png_bytes:
        raise AdbFrameCaptureError("ADB screencap returned empty output.")

    try:
        with Image.open(BytesIO(png_bytes)) as image:
            rgba_image = image.convert("RGBA")
            try:
                return CapturedFrame(
                    data=rgba_image.tobytes(),
                    metadata=FrameMetadata(
                        size=Size(width=rgba_image.width, height=rgba_image.height),
                        captured_at=datetime.now(UTC),
                        pixel_format=PixelFormat.RGBA32,
                        frame_id=f"adb-frame:{uuid4().hex}",
                    ),
                )
            finally:
                rgba_image.close()
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise AdbFrameCaptureError("Unable to decode adb screencap PNG output.") from exc


def normalize_shell_screencap_output(output: bytes) -> bytes:
    """Fix newline mangling from adb shell fallback screencap output."""
    return output.replace(b"\r\n", b"\n")
