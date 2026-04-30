"""Local filesystem artifact recorder implementation."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from android_game_automator.core import (
    ArtifactKind,
    ArtifactRecord,
    CapturedFrame,
    DebugRecord,
    LogRecord,
)
from android_game_automator.vision.image import FrameImage

_DEFAULT_ARTIFACT_DIRNAME = "artifacts"
_MANIFEST_FILENAME = "artifacts.jsonl"
_LOG_FILENAME = "logs.jsonl"
_DEBUG_FILENAME = "debug.jsonl"
_SAFE_NAME_PATTERN = re.compile(r"[^a-z0-9]+")


class LocalArtifactRecorder:
    """Persist artifacts and structured diagnostics to a local directory."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._artifact_dir = self._root / _DEFAULT_ARTIFACT_DIRNAME
        self._manifest_path = self._root / _MANIFEST_FILENAME
        self._log_path = self._root / _LOG_FILENAME
        self._debug_path = self._root / _DEBUG_FILENAME
        self._append_lock = asyncio.Lock()

    @property
    def root(self) -> Path:
        return self._root

    async def record_artifact(self, record: ArtifactRecord) -> None:
        await self._append_jsonl(self._manifest_path, _serialize_artifact_record(record))

    async def record_log(self, record: LogRecord) -> None:
        await self._append_jsonl(self._log_path, _serialize_log_record(record))

    async def record_debug(self, record: DebugRecord) -> None:
        await self._append_jsonl(self._debug_path, _serialize_debug_record(record))

    async def save_text_artifact(
        self,
        *,
        label: str,
        text: str,
        metadata: Mapping[str, str] | None = None,
        artifact_id: str | None = None,
    ) -> ArtifactRecord:
        return await self._save_artifact(
            kind=ArtifactKind.TEXT,
            label=label,
            data=text.encode("utf-8"),
            suffix=".txt",
            metadata=metadata,
            artifact_id=artifact_id,
        )

    async def save_json_artifact(
        self,
        *,
        label: str,
        payload: Any,
        metadata: Mapping[str, str] | None = None,
        artifact_id: str | None = None,
    ) -> ArtifactRecord:
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        return await self._save_artifact(
            kind=ArtifactKind.JSON,
            label=label,
            data=encoded,
            suffix=".json",
            metadata=metadata,
            artifact_id=artifact_id,
        )

    async def save_binary_artifact(
        self,
        *,
        label: str,
        data: bytes,
        metadata: Mapping[str, str] | None = None,
        artifact_id: str | None = None,
        suffix: str = ".bin",
    ) -> ArtifactRecord:
        return await self._save_artifact(
            kind=ArtifactKind.BINARY,
            label=label,
            data=data,
            suffix=suffix,
            metadata=metadata,
            artifact_id=artifact_id,
        )

    async def save_frame_image_artifact(
        self,
        *,
        label: str,
        frame: CapturedFrame,
        metadata: Mapping[str, str] | None = None,
        artifact_id: str | None = None,
    ) -> ArtifactRecord:
        image_bytes = await asyncio.to_thread(_encode_frame_as_png, frame)
        merged_metadata = dict(metadata or {})
        if frame.metadata.frame_id is not None:
            merged_metadata.setdefault("frame_id", frame.metadata.frame_id)
        merged_metadata.setdefault("pixel_format", frame.metadata.pixel_format.value)
        merged_metadata.setdefault("width", str(frame.metadata.size.width))
        merged_metadata.setdefault("height", str(frame.metadata.size.height))
        return await self._save_artifact(
            kind=ArtifactKind.IMAGE,
            label=label,
            data=image_bytes,
            suffix=".png",
            metadata=merged_metadata,
            artifact_id=artifact_id,
        )

    async def _save_artifact(
        self,
        *,
        kind: ArtifactKind,
        label: str,
        data: bytes,
        suffix: str,
        metadata: Mapping[str, str] | None,
        artifact_id: str | None,
    ) -> ArtifactRecord:
        created_at = datetime.now(UTC)
        resolved_artifact_id = artifact_id or str(uuid.uuid4())
        relative_path, absolute_path = self._build_artifact_path(
            artifact_id=resolved_artifact_id,
            label=label,
            suffix=suffix,
        )

        record = ArtifactRecord(
            artifact_id=resolved_artifact_id,
            kind=kind,
            created_at=created_at,
            label=label,
            persisted_path=relative_path.as_posix(),
            metadata=dict(metadata or {}),
        )

        await asyncio.to_thread(_write_bytes, absolute_path, data)
        await self.record_artifact(record)
        return record

    def _build_artifact_path(
        self, *, artifact_id: str, label: str, suffix: str
    ) -> tuple[Path, Path]:
        filename = f"{artifact_id}-{_slugify_label(label)}{suffix}"
        relative_path = Path(_DEFAULT_ARTIFACT_DIRNAME) / filename
        absolute_path = (self._root / relative_path).resolve()
        artifact_root = self._artifact_dir.resolve()

        try:
            absolute_path.relative_to(artifact_root)
        except ValueError as exc:
            raise ValueError("artifact path must stay within the artifact directory") from exc

        return absolute_path.relative_to(self._root.resolve()), absolute_path

    async def _append_jsonl(self, path: Path, payload: Mapping[str, Any]) -> None:
        async with self._append_lock:
            await asyncio.to_thread(_append_jsonl, path, payload)


def _serialize_artifact_record(record: ArtifactRecord) -> dict[str, Any]:
    return {
        "artifact_id": record.artifact_id,
        "kind": record.kind.value,
        "created_at": record.created_at.isoformat(),
        "label": record.label,
        "persisted_path": record.persisted_path,
        "metadata": dict(record.metadata),
    }


def _serialize_log_record(record: LogRecord) -> dict[str, Any]:
    return {
        "timestamp": record.timestamp.isoformat(),
        "level": record.level.value,
        "message": record.message,
        "context": dict(record.context),
    }


def _serialize_debug_record(record: DebugRecord) -> dict[str, Any]:
    return {
        "timestamp": record.timestamp.isoformat(),
        "name": record.name,
        "fields": dict(record.fields),
    }


def _slugify_label(label: str) -> str:
    slug = _SAFE_NAME_PATTERN.sub("-", label.strip().lower()).strip("-")
    return slug or "artifact"


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")


def _encode_frame_as_png(frame: CapturedFrame) -> bytes:
    image = FrameImage.from_captured_frame(frame).to_pil_image()
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
