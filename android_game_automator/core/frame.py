"""Frame and image metadata contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .geometry import Size


class PixelFormat(StrEnum):
    """Minimal shared pixel format declarations."""

    RGB24 = "rgb24"
    RGBA32 = "rgba32"
    BGR24 = "bgr24"
    BGRA32 = "bgra32"
    GRAY8 = "gray8"


@dataclass(frozen=True, slots=True)
class FrameMetadata:
    """Capture metadata that accompanies an image frame."""

    size: Size
    captured_at: datetime
    pixel_format: PixelFormat = PixelFormat.RGBA32
    frame_id: str | None = None

    def __post_init__(self) -> None:
        if self.frame_id is not None and not self.frame_id.strip():
            raise ValueError("frame_id must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """Raw captured image bytes and associated metadata."""

    data: bytes
    metadata: FrameMetadata

    def __post_init__(self) -> None:
        if len(self.data) == 0:
            raise ValueError("data must be non-empty")
