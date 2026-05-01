"""Live-debug hotkey artifact save helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from android_game_automator.artifacts import ArtifactStore
from android_game_automator.image import FrameImage
from android_game_automator.types import SessionInfo

if TYPE_CHECKING:
    from botto.detection import ScreenAnalysis
    from botto.live.debug import LiveAnalysisSnapshot

_SAVE_RAW_KEY_CODE = ord("s")
_SAVE_DEBUG_KEY_CODE = ord("d")
_SAVE_STATUS_SECONDS = 3.0


@dataclass(frozen=True, slots=True)
class _SavedLiveDebugArtifacts:
    kind: str
    label: str
    image_path: Path
    analysis_path: Path | None = None


def _live_debug_artifact_selection(key_code: int) -> tuple[str, str] | None:
    if key_code == _SAVE_RAW_KEY_CODE:
        return "raw", "s"
    if key_code == _SAVE_DEBUG_KEY_CODE:
        return "debug", "d"
    return None


def _live_debug_artifact_label(*, kind: str, sequence: int) -> str:
    return f"live-debug-{kind}-{sequence:06d}"


def _save_live_debug_artifacts(
    *,
    store: ArtifactStore,
    label: str,
    kind: str,
    hotkey: str,
    image: FrameImage,
    snapshot: LiveAnalysisSnapshot | None,
    session_info: SessionInfo,
    package_name: str,
    launched: bool,
) -> _SavedLiveDebugArtifacts:
    metadata = _live_debug_artifact_metadata(
        label=label,
        kind=kind,
        hotkey=hotkey,
        image=image,
        session_info=session_info,
        package_name=package_name,
        launched=launched,
    )
    image_path = store.save_image(label, image, metadata=metadata)
    analysis_path: Path | None = None
    if snapshot is not None:
        analysis_path = store.save_json(
            label,
            _live_debug_analysis_payload(
                snapshot=snapshot,
                saved_frame=image,
                session_info=session_info,
                package_name=package_name,
                launched=launched,
                image_kind=kind,
                artifact_label=label,
            ),
            metadata=metadata
            | {
                "analysis_frame_id": snapshot.frame_id,
            },
        )
    return _SavedLiveDebugArtifacts(
        kind=kind,
        label=label,
        image_path=image_path,
        analysis_path=analysis_path,
    )


def _live_debug_artifact_metadata(
    *,
    label: str,
    kind: str,
    hotkey: str,
    image: FrameImage,
    session_info: SessionInfo,
    package_name: str,
    launched: bool,
) -> dict[str, Any]:
    return {
        "artifact_label": label,
        "device_id": session_info.device.identity.device_id,
        "frame_id": image.frame_id,
        "height": image.size.height,
        "hotkey": hotkey,
        "image_kind": kind,
        "launched": launched,
        "package": package_name,
        "pixel_format": image.pixel_format.value,
        "session_id": session_info.session_id,
        "width": image.size.width,
    }


def _live_debug_analysis_payload(
    *,
    snapshot: LiveAnalysisSnapshot,
    saved_frame: FrameImage,
    session_info: SessionInfo,
    package_name: str,
    launched: bool,
    image_kind: str,
    artifact_label: str,
) -> dict[str, Any]:
    return {
        "analysis": _serialize_screen_analysis(snapshot.analysis),
        "analysis_frame_id": snapshot.frame_id,
        "analyzed_at": snapshot.analyzed_at,
        "artifact_label": artifact_label,
        "device_id": session_info.device.identity.device_id,
        "duration_seconds": snapshot.duration_seconds,
        "frame": _serialize_live_debug_frame(saved_frame),
        "image_kind": image_kind,
        "launched": launched,
        "package": package_name,
        "session_id": session_info.session_id,
    }


def _serialize_screen_analysis(analysis: ScreenAnalysis) -> dict[str, Any]:
    """Return a JSON-serializable representation of a screen analysis."""

    payload = _jsonable(analysis)
    if not isinstance(payload, dict):
        raise TypeError("serialized ScreenAnalysis must be a JSON object")
    return payload


def _jsonable(value: object) -> Any:
    if value is None:
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        dataclass_value = cast(Any, value)
        return {
            field.name: _jsonable(getattr(dataclass_value, field.name))
            for field in fields(dataclass_value)
        }
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_jsonable(item) for item in value]
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _serialize_live_debug_frame(image: FrameImage) -> dict[str, Any]:
    return {
        "captured_at": image.captured_at.isoformat() if image.captured_at is not None else None,
        "frame_id": image.frame_id,
        "pixel_format": image.pixel_format.value,
        "size": {
            "height": image.size.height,
            "width": image.size.width,
        },
    }


def _live_debug_overlay_save_message(saved: _SavedLiveDebugArtifacts) -> str:
    analysis_suffix = " + analysis" if saved.analysis_path is not None else ""
    return f"saved {saved.kind}: {saved.label}{analysis_suffix}"


def _live_debug_stdout_save_message(saved: _SavedLiveDebugArtifacts) -> str:
    parts = [f"image={saved.image_path}"]
    if saved.analysis_path is not None:
        parts.append(f"analysis={saved.analysis_path}")
    return f"saved live-debug {saved.kind} artifact {saved.label}: " + ", ".join(parts)
