"""Artifact, log, and debug record contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ._immutables import freeze_mapping


class ArtifactKind(StrEnum):
    """Shared artifact categories emitted by framework components."""

    IMAGE = "image"
    TEXT = "text"
    JSON = "json"
    BINARY = "binary"


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Metadata descriptor for a produced artifact."""

    artifact_id: str
    kind: ArtifactKind
    created_at: datetime
    label: str
    persisted_path: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must be non-empty")
        if not self.label.strip():
            raise ValueError("label must be non-empty")
        if self.persisted_path is not None and not self.persisted_path.strip():
            raise ValueError("persisted_path must be non-empty when provided")
        _validate_metadata(self.metadata)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


class LogLevel(StrEnum):
    """Log severity levels for framework event records."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class LogRecord:
    """Structured framework log record."""

    timestamp: datetime
    level: LogLevel
    message: str
    context: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("message must be non-empty")
        object.__setattr__(self, "context", freeze_mapping(self.context))


DebugValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class DebugRecord:
    """Structured debug payload record for diagnostics."""

    timestamp: datetime
    name: str
    fields: Mapping[str, DebugValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must be non-empty")
        object.__setattr__(self, "fields", freeze_mapping(self.fields))


def _validate_metadata(metadata: Mapping[str, str]) -> None:
    for key, value in metadata.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("artifact metadata keys and values must be strings")
