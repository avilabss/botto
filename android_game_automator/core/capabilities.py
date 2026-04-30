"""Capability flags and declarations for sessions/backends."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum

from .errors import CapabilityUnavailableError


class Capability(StrEnum):
    """Shared framework capability flags."""

    FRAME_CAPTURE = "frame.capture"
    INPUT_TAP = "input.tap"
    INPUT_SWIPE = "input.swipe"
    INPUT_KEY_PRESS = "input.key_press"
    INPUT_TEXT_ENTRY = "input.text_entry"
    INPUT_MULTI_TOUCH = "input.multi_touch"
    DETECTION = "detection.run"
    ARTIFACT_RECORDING = "artifact.recording"


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    """Explicit capability declarations for a device or session."""

    values: frozenset[Capability] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        normalized = frozenset(self.values)
        if not all(isinstance(value, Capability) for value in normalized):
            raise ValueError("values must contain only Capability items")
        object.__setattr__(self, "values", normalized)

    @classmethod
    def from_iterable(cls, values: Iterable[Capability]) -> CapabilitySet:
        """Build a normalized capability set from any iterable input."""
        return cls(values=frozenset(values))

    def supports(self, capability: Capability) -> bool:
        """Return whether a capability is declared."""
        return capability in self.values

    def require(self, capability: Capability) -> None:
        """Raise if the provided capability is not declared."""
        if capability not in self.values:
            raise CapabilityUnavailableError(
                f"Capability {capability.value!r} is not available in this session."
            )

    def __contains__(self, capability: object) -> bool:
        return isinstance(capability, Capability) and capability in self.values

    def __iter__(self) -> Iterator[Capability]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)
