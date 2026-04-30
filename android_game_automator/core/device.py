"""Device/session identity and metadata contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from ._immutables import freeze_mapping
from .capabilities import CapabilitySet


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """Stable identity for a device exposed by a backend."""

    backend_name: str
    device_id: str
    display_name: str | None = None

    def __post_init__(self) -> None:
        if not self.backend_name.strip():
            raise ValueError("backend_name must be non-empty")
        if not self.device_id.strip():
            raise ValueError("device_id must be non-empty")
        if self.display_name is not None and not self.display_name.strip():
            raise ValueError("display_name must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Capability and metadata declarations for a discovered device."""

    identity: DeviceIdentity
    capabilities: CapabilitySet = field(default_factory=CapabilitySet)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Metadata for an active automation session."""

    session_id: str
    device: DeviceInfo
    started_at: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must be non-empty")
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))
