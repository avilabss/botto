"""Shared core contracts and data models for Android Game Automator."""

from __future__ import annotations

from .artifacts import ArtifactKind, ArtifactRecord, DebugRecord, DebugValue, LogLevel, LogRecord
from .capabilities import Capability, CapabilitySet
from .contracts import (
    AsyncArtifactRecorder,
    AsyncDetector,
    AsyncDeviceBackend,
    AsyncDeviceSession,
    AsyncFrameCapturer,
    AsyncInputExecutor,
)
from .detection import Detection, DetectionRequest, DetectionResult
from .device import DeviceIdentity, DeviceInfo, SessionInfo
from .errors import AndroidGameAutomatorCoreError, CapabilityUnavailableError
from .frame import CapturedFrame, FrameMetadata, PixelFormat
from .geometry import (
    NormalizedPoint,
    NormalizedRect,
    Point,
    Rect,
    ScreenPoint,
    ScreenRect,
    Size,
    Viewport,
)
from .input import (
    InputAction,
    InputActionKind,
    InputActionResult,
    InputStatus,
    KeyPressAction,
    SwipeAction,
    TapAction,
    TextEntryAction,
)

__all__ = [
    "ArtifactKind",
    "ArtifactRecord",
    "AsyncArtifactRecorder",
    "AsyncDetector",
    "AsyncDeviceBackend",
    "AsyncDeviceSession",
    "AsyncFrameCapturer",
    "AsyncInputExecutor",
    "AndroidGameAutomatorCoreError",
    "Capability",
    "CapabilitySet",
    "CapabilityUnavailableError",
    "CapturedFrame",
    "DebugRecord",
    "DebugValue",
    "Detection",
    "DetectionRequest",
    "DetectionResult",
    "DeviceIdentity",
    "DeviceInfo",
    "FrameMetadata",
    "InputAction",
    "InputActionKind",
    "InputActionResult",
    "InputStatus",
    "KeyPressAction",
    "LogLevel",
    "LogRecord",
    "NormalizedPoint",
    "NormalizedRect",
    "PixelFormat",
    "Point",
    "Rect",
    "ScreenPoint",
    "ScreenRect",
    "SessionInfo",
    "Size",
    "SwipeAction",
    "TapAction",
    "TextEntryAction",
    "Viewport",
]
