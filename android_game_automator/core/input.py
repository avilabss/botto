"""Input action and result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .geometry import ScreenPoint


class InputActionKind(StrEnum):
    """Supported input action variants."""

    TAP = "tap"
    SWIPE = "swipe"
    KEY_PRESS = "key_press"
    TEXT_ENTRY = "text_entry"


@dataclass(frozen=True, slots=True)
class TapAction:
    """Single tap input on a point coordinate."""

    point: ScreenPoint
    hold_ms: int = 0

    def __post_init__(self) -> None:
        if self.hold_ms < 0:
            raise ValueError("hold_ms must be >= 0")

    @property
    def kind(self) -> InputActionKind:
        return InputActionKind.TAP


@dataclass(frozen=True, slots=True)
class SwipeAction:
    """Swipe gesture between two points."""

    start: ScreenPoint
    end: ScreenPoint
    duration_ms: int = 120

    def __post_init__(self) -> None:
        if self.duration_ms <= 0:
            raise ValueError("duration_ms must be > 0")

    @property
    def kind(self) -> InputActionKind:
        return InputActionKind.SWIPE


@dataclass(frozen=True, slots=True)
class KeyPressAction:
    """Press an abstract backend key identifier."""

    key: str

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("key must be non-empty")

    @property
    def kind(self) -> InputActionKind:
        return InputActionKind.KEY_PRESS


@dataclass(frozen=True, slots=True)
class TextEntryAction:
    """Enter a text payload via backend input APIs."""

    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("text must be non-empty")

    @property
    def kind(self) -> InputActionKind:
        return InputActionKind.TEXT_ENTRY


InputAction = TapAction | SwipeAction | KeyPressAction | TextEntryAction


class InputStatus(StrEnum):
    """Possible execution outcomes for an input action."""

    APPLIED = "applied"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class InputActionResult:
    """Outcome metadata returned by an input executor."""

    action_kind: InputActionKind
    status: InputStatus
    completed_at: datetime
    message: str | None = None
