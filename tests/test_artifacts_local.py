"""Tests for local artifact persistence."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from android_game_automator.artifacts import LocalArtifactRecorder
from android_game_automator.core import (
    CapturedFrame,
    DebugRecord,
    FrameMetadata,
    LogLevel,
    LogRecord,
    PixelFormat,
    Size,
)
from android_game_automator.core.artifacts import ArtifactKind, ArtifactRecord
from PIL import Image


def test_local_artifact_recorder_persists_manifest_logs_and_debug_records(tmp_path) -> None:
    recorder = LocalArtifactRecorder(tmp_path)
    now = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)

    artifact_record = ArtifactRecord(
        artifact_id="artifact-1",
        kind=ArtifactKind.TEXT,
        created_at=now,
        label="session summary",
        persisted_path="artifacts/artifact-1-session-summary.txt",
        metadata={"session_id": "session-1"},
    )
    log_record = LogRecord(
        timestamp=now,
        level=LogLevel.INFO,
        message="capture complete",
        context={"session_id": "session-1"},
    )
    debug_record = DebugRecord(
        timestamp=now,
        name="capture.metrics",
        fields={"attempt": 1, "success": True},
    )

    asyncio.run(recorder.record_artifact(artifact_record))
    asyncio.run(recorder.record_log(log_record))
    asyncio.run(recorder.record_debug(debug_record))

    manifest_lines = (tmp_path / "artifacts.jsonl").read_text(encoding="utf-8").splitlines()
    log_lines = (tmp_path / "logs.jsonl").read_text(encoding="utf-8").splitlines()
    debug_lines = (tmp_path / "debug.jsonl").read_text(encoding="utf-8").splitlines()

    assert json.loads(manifest_lines[0]) == {
        "artifact_id": "artifact-1",
        "created_at": now.isoformat(),
        "kind": "text",
        "label": "session summary",
        "metadata": {"session_id": "session-1"},
        "persisted_path": "artifacts/artifact-1-session-summary.txt",
    }
    assert json.loads(log_lines[0]) == {
        "context": {"session_id": "session-1"},
        "level": "info",
        "message": "capture complete",
        "timestamp": now.isoformat(),
    }
    assert json.loads(debug_lines[0]) == {
        "fields": {"attempt": 1, "success": True},
        "name": "capture.metrics",
        "timestamp": now.isoformat(),
    }


def test_local_artifact_recorder_saves_text_json_and_binary_artifacts(tmp_path) -> None:
    recorder = LocalArtifactRecorder(tmp_path)

    text_record = asyncio.run(
        recorder.save_text_artifact(
            label="Run Notes",
            text="hello world",
            metadata={"kind": "notes"},
            artifact_id="text-1",
        )
    )
    json_record = asyncio.run(
        recorder.save_json_artifact(
            label="Detection Result",
            payload={"score": 0.9, "ok": True},
            artifact_id="json-1",
        )
    )
    binary_record = asyncio.run(
        recorder.save_binary_artifact(
            label="Model Weights",
            data=b"\x00\x01\x02",
            artifact_id="bin-1",
            suffix=".dat",
        )
    )

    assert text_record.persisted_path == "artifacts/text-1-run-notes.txt"
    assert json_record.persisted_path == "artifacts/json-1-detection-result.json"
    assert binary_record.persisted_path == "artifacts/bin-1-model-weights.dat"

    assert (tmp_path / text_record.persisted_path).read_text(encoding="utf-8") == "hello world"
    assert json.loads((tmp_path / json_record.persisted_path).read_text(encoding="utf-8")) == {
        "ok": True,
        "score": 0.9,
    }
    assert (tmp_path / binary_record.persisted_path).read_bytes() == b"\x00\x01\x02"

    manifest_lines = (tmp_path / "artifacts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(manifest_lines) == 3


def test_local_artifact_recorder_saves_frame_image_artifact(tmp_path) -> None:
    recorder = LocalArtifactRecorder(tmp_path)
    frame = CapturedFrame(
        data=bytes([12, 34, 56, 255, 90, 80, 70, 255]),
        metadata=FrameMetadata(
            size=Size(width=2, height=1),
            captured_at=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
            pixel_format=PixelFormat.RGBA32,
            frame_id="frame-123",
        ),
    )

    record = asyncio.run(
        recorder.save_frame_image_artifact(
            label="Captured Frame",
            frame=frame,
            artifact_id="frame-1",
        )
    )

    assert record.kind is ArtifactKind.IMAGE
    assert record.persisted_path == "artifacts/frame-1-captured-frame.png"
    assert record.metadata == {
        "frame_id": "frame-123",
        "pixel_format": "rgba32",
        "width": "2",
        "height": "1",
    }

    with Image.open(tmp_path / record.persisted_path) as image:
        assert image.mode == "RGBA"
        assert image.size == (2, 1)
        assert image.getpixel((0, 0)) == (12, 34, 56, 255)
        assert image.getpixel((1, 0)) == (90, 80, 70, 255)


def test_local_artifact_recorder_rejects_paths_that_escape_artifact_root(tmp_path) -> None:
    recorder = LocalArtifactRecorder(tmp_path)

    with pytest.raises(ValueError, match="artifact path must stay within the artifact directory"):
        asyncio.run(
            recorder.save_text_artifact(
                label="Run Notes",
                text="hello world",
                artifact_id="../escape",
            )
        )

    with pytest.raises(ValueError, match="artifact path must stay within the artifact directory"):
        asyncio.run(
            recorder.save_binary_artifact(
                label="Payload",
                data=b"abc",
                artifact_id="safe-id",
                suffix="/../../escape.bin",
            )
        )

    assert not (tmp_path / "artifacts").exists()
    assert not (tmp_path / "artifacts.jsonl").exists()


def test_local_artifact_recorder_rejects_duplicate_artifact_paths(tmp_path) -> None:
    recorder = LocalArtifactRecorder(tmp_path)

    first_record = asyncio.run(
        recorder.save_text_artifact(
            label="Run Notes",
            text="first version",
            artifact_id="artifact-1",
        )
    )

    with pytest.raises(FileExistsError):
        asyncio.run(
            recorder.save_text_artifact(
                label="Run Notes",
                text="second version",
                artifact_id="artifact-1",
            )
        )

    assert (tmp_path / first_record.persisted_path).read_text(encoding="utf-8") == "first version"
    manifest_lines = (tmp_path / "artifacts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(manifest_lines) == 1


def test_local_artifact_recorder_validates_metadata_before_writing_bytes(tmp_path) -> None:
    recorder = LocalArtifactRecorder(tmp_path)

    with pytest.raises(TypeError, match="artifact metadata keys and values must be strings"):
        asyncio.run(
            recorder.save_text_artifact(
                label="Run Notes",
                text="hello world",
                metadata={"attempt": 1},  # type: ignore[arg-type]
                artifact_id="artifact-1",
            )
        )

    assert not (tmp_path / "artifacts").exists()
    assert not (tmp_path / "artifacts.jsonl").exists()
