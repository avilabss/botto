"""Simple local artifact persistence helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from os import PathLike
from pathlib import Path, PurePath, PureWindowsPath
from typing import Any

from android_game_automator.image import FrameImage


class ArtifactStore:
    """Concrete synchronous artifact writer rooted at one local directory."""

    def __init__(self, root: str | PathLike[str]) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """Configured artifact root."""
        return self._root

    def save_image(
        self,
        label: str,
        image: FrameImage,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        """Save a frame image as PNG and append a manifest entry."""
        path, artifact_label = self._artifact_path(label, suffix=".png")
        self._prepare_output_path(path)
        image.save(path)
        self._append_manifest(kind="image", label=artifact_label, path=path, metadata=metadata)
        return path

    def save_json(
        self,
        label: str,
        payload: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        """Save a JSON-serializable payload and append a manifest entry."""
        path, artifact_label = self._artifact_path(label, suffix=".json")
        self._prepare_output_path(path)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._append_manifest(kind="json", label=artifact_label, path=path, metadata=metadata)
        return path

    def save_text(
        self,
        label: str,
        text: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        """Save text and append a manifest entry."""
        path, artifact_label = self._artifact_path(label, suffix=".txt")
        self._prepare_output_path(path)
        path.write_text(text, encoding="utf-8")
        self._append_manifest(kind="text", label=artifact_label, path=path, metadata=metadata)
        return path

    def save_binary(
        self,
        label: str,
        data: bytes,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        """Save bytes and append a manifest entry."""
        path, artifact_label = self._artifact_path(label, suffix=".bin")
        self._prepare_output_path(path)
        path.write_bytes(data)
        self._append_manifest(kind="binary", label=artifact_label, path=path, metadata=metadata)
        return path

    def _artifact_path(self, label: str, *, suffix: str) -> tuple[Path, str]:
        safe_label = _safe_label(label)
        candidate = self._root / f"{safe_label}{suffix}"
        resolved_root = self._root.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=False)
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("artifact label must resolve inside the artifact root") from exc
        return candidate, safe_label

    def _prepare_output_path(self, path: Path) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("artifact path must not be a symlink")

    def _append_manifest(
        self,
        *,
        kind: str,
        label: str,
        path: Path,
        metadata: Mapping[str, Any] | None,
    ) -> None:
        manifest_path = self._root / "manifest.jsonl"
        if manifest_path.is_symlink():
            raise ValueError("artifact manifest must not be a symlink")

        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "kind": kind,
            "label": label,
            "path": str(path.relative_to(self._root)),
            "metadata": dict(metadata or {}),
        }
        with manifest_path.open("a", encoding="utf-8") as manifest:
            manifest.write(json.dumps(entry, sort_keys=True))
            manifest.write("\n")


def _safe_label(label: str) -> str:
    cleaned = label.strip()
    if not cleaned:
        raise ValueError("artifact label must be non-empty")
    if "\x00" in cleaned:
        raise ValueError("artifact label must not contain NUL bytes")
    if cleaned in {".", ".."}:
        raise ValueError("artifact label must not be a path component")
    if PurePath(cleaned).name != cleaned or PureWindowsPath(cleaned).name != cleaned:
        raise ValueError("artifact label must be a filename stem, not a path")
    return cleaned


__all__ = ["ArtifactStore"]
