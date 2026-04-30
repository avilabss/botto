"""Tests for the simple concrete artifact store."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from android_game_automator.artifacts import ArtifactStore
from android_game_automator.image import FrameImage
from android_game_automator.types import PixelFormat, Size
from PIL import Image


def test_artifact_store_saves_files_and_manifest(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    image_path = store.save_image("screen", _rgba_image(), metadata={"source": "test"})
    json_path = store.save_json("payload", {"ready": True})
    text_path = store.save_text("note", "hello")
    binary_path = store.save_binary("blob", b"\x00\x01")

    assert image_path == tmp_path / "screen.png"
    assert json.loads(json_path.read_text(encoding="utf-8")) == {"ready": True}
    assert text_path.read_text(encoding="utf-8") == "hello"
    assert binary_path.read_bytes() == b"\x00\x01"
    with Image.open(image_path) as saved_image:
        assert saved_image.mode == "RGBA"
        assert saved_image.size == (1, 1)

    entries = [
        json.loads(line)
        for line in (tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(entry["kind"], entry["label"], entry["path"]) for entry in entries] == [
        ("image", "screen", "screen.png"),
        ("json", "payload", "payload.json"),
        ("text", "note", "note.txt"),
        ("binary", "blob", "blob.bin"),
    ]
    assert entries[0]["metadata"] == {"source": "test"}
    assert all(entry["timestamp"] for entry in entries)


@pytest.mark.parametrize("label", ["../escape", "subdir/escape", "..\\escape", ".", " "])
def test_artifact_store_rejects_path_labels(tmp_path: Path, label: str) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="artifact label"):
        store.save_text(label, "should not be written")

    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "artifacts" / "subdir").exists()


def test_artifact_store_rejects_broken_artifact_symlink(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    missing_target = tmp_path / "missing-target.txt"
    path.symlink_to(missing_target)
    store = ArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="artifact path"):
        store.save_text("note", "should not be written")

    assert path.is_symlink()
    assert not missing_target.exists()


def test_artifact_store_rejects_broken_manifest_symlink(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.jsonl"
    missing_target = tmp_path / "missing-manifest.jsonl"
    manifest_path.symlink_to(missing_target)
    store = ArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="artifact manifest"):
        store.save_text("note", "hello")

    assert manifest_path.is_symlink()
    assert not missing_target.exists()


def _rgba_image() -> FrameImage:
    return FrameImage(
        size=Size(width=1, height=1),
        pixel_format=PixelFormat.RGBA32,
        data=bytes((255, 0, 0, 255)),
        captured_at=datetime.now(UTC),
        frame_id="frame-1",
    )
