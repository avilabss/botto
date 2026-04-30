"""Tests for the simple concrete artifact store."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from android_game_automator.artifacts import ArtifactStore
from android_game_automator.image import FrameImage
from android_game_automator.types import PixelFormat, Size
from PIL import Image

RUN_NAME_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")


def test_artifact_store_saves_files_and_manifest(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, run_name="run-1")

    image_path = store.save_image("screen", _rgba_image(), metadata={"source": "test"})
    json_path = store.save_json("payload", {"ready": True})
    text_path = store.save_text("note", "hello")
    binary_path = store.save_binary("blob", b"\x00\x01")

    assert store.root == tmp_path
    assert store.run_dir == tmp_path / "run-1"
    assert image_path == store.run_dir / "images" / "screen.png"
    assert json_path == store.run_dir / "json" / "payload.json"
    assert text_path == store.run_dir / "text" / "note.txt"
    assert binary_path == store.run_dir / "binary" / "blob.bin"
    assert json.loads(json_path.read_text(encoding="utf-8")) == {"ready": True}
    assert text_path.read_text(encoding="utf-8") == "hello"
    assert binary_path.read_bytes() == b"\x00\x01"
    with Image.open(image_path) as saved_image:
        assert saved_image.mode == "RGBA"
        assert saved_image.size == (1, 1)

    entries = [
        json.loads(line)
        for line in (store.run_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(entry["kind"], entry["label"], entry["path"]) for entry in entries] == [
        ("image", "screen", "run-1/images/screen.png"),
        ("json", "payload", "run-1/json/payload.json"),
        ("text", "note", "run-1/text/note.txt"),
        ("binary", "blob", "run-1/binary/blob.bin"),
    ]
    assert all(entry["run_name"] == "run-1" for entry in entries)
    assert all(entry["run_dir"] == "run-1" for entry in entries)
    assert entries[0]["metadata"] == {"source": "test"}
    assert all(entry["timestamp"] for entry in entries)


def test_artifact_store_default_run_names_are_distinct_under_root(tmp_path: Path) -> None:
    first = ArtifactStore(tmp_path)
    second = ArtifactStore(tmp_path)

    assert first.run_dir.parent == tmp_path
    assert second.run_dir.parent == tmp_path
    assert RUN_NAME_PATTERN.fullmatch(first.run_dir.name)
    assert RUN_NAME_PATTERN.fullmatch(second.run_dir.name)
    assert first.run_dir != second.run_dir
    assert first.run_dir.is_dir()
    assert second.run_dir.is_dir()

    run_dir = first.run_dir
    first.save_text("note", "hello")
    manifest_entry = json.loads((run_dir / "manifest.jsonl").read_text(encoding="utf-8"))
    assert first.run_dir == run_dir
    assert manifest_entry["path"] == f"{run_dir.name}/text/note.txt"
    assert manifest_entry["run_name"] == run_dir.name
    assert manifest_entry["run_dir"] == run_dir.name


@pytest.mark.parametrize("label", ["../escape", "subdir/escape", "..\\escape", ".", " "])
def test_artifact_store_rejects_path_labels(tmp_path: Path, label: str) -> None:
    store = ArtifactStore(tmp_path / "artifacts", run_name="run-1")

    with pytest.raises(ValueError, match="artifact label"):
        store.save_text(label, "should not be written")

    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "artifacts" / "subdir").exists()


def test_artifact_store_rejects_broken_artifact_symlink(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, run_name="run-1")
    text_dir = store.run_dir / "text"
    text_dir.mkdir()
    path = text_dir / "note.txt"
    missing_target = tmp_path / "missing-target.txt"
    path.symlink_to(missing_target)

    with pytest.raises(ValueError, match="artifact path"):
        store.save_text("note", "should not be written")

    assert path.is_symlink()
    assert not missing_target.exists()


def test_artifact_store_rejects_broken_manifest_symlink(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, run_name="run-1")
    manifest_path = store.run_dir / "manifest.jsonl"
    missing_target = tmp_path / "missing-manifest.jsonl"
    manifest_path.symlink_to(missing_target)

    with pytest.raises(ValueError, match="artifact manifest"):
        store.save_text("note", "hello")

    assert manifest_path.is_symlink()
    assert not missing_target.exists()


def test_artifact_store_rejects_kind_directory_symlink(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, run_name="run-1")
    outside_dir = tmp_path / "outside"
    kind_dir = store.run_dir / "text"
    kind_dir.symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="artifact kind directory"):
        store.save_text("note", "should not be written")

    assert kind_dir.is_symlink()
    assert not outside_dir.exists()


def _rgba_image() -> FrameImage:
    return FrameImage(
        size=Size(width=1, height=1),
        pixel_format=PixelFormat.RGBA32,
        data=bytes((255, 0, 0, 255)),
        captured_at=datetime.now(UTC),
        frame_id="frame-1",
    )
