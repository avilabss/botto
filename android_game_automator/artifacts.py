"""Simple local artifact persistence helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from os import PathLike
from pathlib import Path, PurePath, PureWindowsPath
from typing import Any
from uuid import uuid4

from android_game_automator.image import FrameImage


class ArtifactStore:
    """Concrete synchronous artifact writer for one run and artifact kind directories."""

    def __init__(self, root: str | PathLike[str], run_name: str | None = None) -> None:
        self._root = Path(root)
        self._run_name = _safe_label(
            run_name if run_name is not None else _default_run_name(),
            field_name="artifact run name",
        )
        self._run_dir = self._root / self._run_name
        self._prepare_run_dir()

    @property
    def root(self) -> Path:
        """Configured artifact root."""
        return self._root

    @property
    def run_dir(self) -> Path:
        """Directory where this store writes the current run's artifacts."""
        return self._run_dir

    def save_image(
        self,
        label: str,
        image: FrameImage,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        """Save a frame image as PNG and append a manifest entry."""
        path, artifact_label = self._artifact_path(label, kind="image", suffix=".png")
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
        path, artifact_label = self._artifact_path(label, kind="json", suffix=".json")
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
        path, artifact_label = self._artifact_path(label, kind="text", suffix=".txt")
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
        path, artifact_label = self._artifact_path(label, kind="binary", suffix=".bin")
        self._prepare_output_path(path)
        path.write_bytes(data)
        self._append_manifest(kind="binary", label=artifact_label, path=path, metadata=metadata)
        return path

    def _artifact_path(self, label: str, *, kind: str, suffix: str) -> tuple[Path, str]:
        safe_label = _safe_label(label, field_name="artifact label")
        candidate = self._kind_dir(kind) / f"{safe_label}{suffix}"
        return candidate, safe_label

    def _kind_dir(self, kind: str) -> Path:
        if kind == "image":
            return self._run_dir / "images"
        if kind == "json":
            return self._run_dir / "json"
        if kind == "text":
            return self._run_dir / "text"
        if kind == "binary":
            return self._run_dir / "binary"
        raise ValueError(f"unsupported artifact kind: {kind}")

    def _prepare_run_dir(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if self._run_dir.is_symlink():
            raise ValueError("artifact run directory must not be a symlink")
        self._run_dir.mkdir(parents=True, exist_ok=True)
        if self._run_dir.is_symlink():
            raise ValueError("artifact run directory must not be a symlink")

        resolved_root = self._root.resolve(strict=False)
        resolved_run_dir = self._run_dir.resolve(strict=False)
        try:
            resolved_run_dir.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(
                "artifact run directory must resolve inside the artifact root"
            ) from exc

    def _ensure_inside_run(self, path: Path, *, description: str) -> None:
        resolved_run_dir = self._run_dir.resolve(strict=False)
        resolved_candidate = path.resolve(strict=False)
        try:
            resolved_candidate.relative_to(resolved_run_dir)
        except ValueError as exc:
            raise ValueError(
                f"{description} must resolve inside the artifact run directory"
            ) from exc

    def _prepare_output_path(self, path: Path) -> None:
        self._prepare_run_dir()
        kind_dir = path.parent
        if kind_dir.is_symlink():
            raise ValueError("artifact kind directory must not be a symlink")
        kind_dir.mkdir(parents=True, exist_ok=True)
        if kind_dir.is_symlink():
            raise ValueError("artifact kind directory must not be a symlink")

        self._ensure_inside_run(kind_dir, description="artifact kind directory")
        self._ensure_inside_run(path, description="artifact path")
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
        self._prepare_run_dir()
        manifest_path = self._run_dir / "manifest.jsonl"
        if manifest_path.is_symlink():
            raise ValueError("artifact manifest must not be a symlink")
        self._ensure_inside_run(manifest_path, description="artifact manifest")

        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "kind": kind,
            "label": label,
            "path": path.relative_to(self._root).as_posix(),
            "run_name": self._run_name,
            "run_dir": self._run_dir.relative_to(self._root).as_posix(),
            "metadata": dict(metadata or {}),
        }
        with manifest_path.open("a", encoding="utf-8") as manifest:
            manifest.write(json.dumps(entry, sort_keys=True))
            manifest.write("\n")


def _default_run_name() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{uuid4().hex[:8]}"


def _safe_label(label: str, *, field_name: str) -> str:
    cleaned = label.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    if "\x00" in cleaned:
        raise ValueError(f"{field_name} must not contain NUL bytes")
    if cleaned in {".", ".."}:
        raise ValueError(f"{field_name} must not be a path component")
    if PurePath(cleaned).name != cleaned or PureWindowsPath(cleaned).name != cleaned:
        raise ValueError(f"{field_name} must be a filename stem, not a path")
    return cleaned


__all__ = ["ArtifactStore"]
