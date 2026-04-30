"""Single-shot read-only screen analysis runner for Botto."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from os import PathLike
from pathlib import Path
from time import monotonic
from typing import Any, Protocol, cast

from android_game_automator.artifacts import ArtifactStore
from android_game_automator.image import FrameImage
from android_game_automator.types import SessionInfo

from android_game_automator.adb import AdbDeviceBackend
from botto.screen_detector import analyze_screen
from botto.screens import ScreenAnalysis

DEFAULT_ARTIFACT_ROOT = ".botto-artifacts"
DEFAULT_CLASH_PACKAGE = "com.supercell.clashofclans"
DEFAULT_LAUNCH_WAIT_SECONDS = 2.0
_SCREENSHOT_LABEL = "screenshot"
_ANALYSIS_LABEL = "screen-analysis"
_TIMING_FIELDS = (
    "open_session",
    "launch_app",
    "launch_wait",
    "screenshot",
    "analysis",
    "artifact_save",
    "total",
)


class AnalysisSession(Protocol):
    """Session operations used by the read-only analysis runner."""

    @property
    def info(self) -> SessionInfo: ...

    async def close(self) -> None: ...

    async def launch_app(self, package_name: str) -> None: ...

    async def screenshot(self) -> FrameImage: ...


class AnalysisBackend(Protocol):
    """Backend operations used by the read-only analysis runner."""

    async def open_session(self, device_id: str | None = None) -> AnalysisSession: ...


class ScreenAnalyzer(Protocol):
    """Callable used to analyze a captured screenshot."""

    def __call__(self, image: FrameImage) -> ScreenAnalysis: ...


SleepFn = Callable[[float], Awaitable[None]]


async def analyze_once(
    *,
    device_id: str | None = None,
    artifact_root: str | PathLike[str] = DEFAULT_ARTIFACT_ROOT,
    run_name: str | None = None,
    package_name: str = DEFAULT_CLASH_PACKAGE,
    launch: bool = True,
    launch_wait_seconds: float = DEFAULT_LAUNCH_WAIT_SECONDS,
    backend: AnalysisBackend | None = None,
    screen_analyzer: ScreenAnalyzer = analyze_screen,
    sleep_fn: SleepFn = asyncio.sleep,
) -> dict[str, Any]:
    """Launch if requested, capture one screenshot, analyze it, and save artifacts."""

    if launch_wait_seconds < 0:
        raise ValueError("launch_wait_seconds must be >= 0")

    total_start = monotonic()
    timings = _empty_timings()
    artifact_store = ArtifactStore(artifact_root, run_name=run_name)
    resolved_backend = backend if backend is not None else AdbDeviceBackend()

    phase_start = monotonic()
    session = await resolved_backend.open_session(device_id)
    timings["open_session"] = _elapsed_since(phase_start)

    try:
        if launch:
            phase_start = monotonic()
            await session.launch_app(package_name)
            timings["launch_app"] = _elapsed_since(phase_start)
            if launch_wait_seconds > 0:
                phase_start = monotonic()
                await sleep_fn(launch_wait_seconds)
                timings["launch_wait"] = _elapsed_since(phase_start)

        phase_start = monotonic()
        image = await session.screenshot()
        timings["screenshot"] = _elapsed_since(phase_start)

        phase_start = monotonic()
        analysis = screen_analyzer(image)
        timings["analysis"] = _elapsed_since(phase_start)

        analysis_payload = serialize_screen_analysis(analysis)
        frame_payload = _serialize_frame(image)
        metadata = _artifact_metadata(
            session=session,
            image=image,
            package_name=package_name,
            launched=launch,
        )

        artifact_start = monotonic()
        screenshot_path = artifact_store.save_image(
            _SCREENSHOT_LABEL,
            image,
            metadata=metadata,
        )
        saved_json_timings = dict(timings)
        saved_json_timings["artifact_save"] = _elapsed_since(artifact_start)
        saved_json_timings["total"] = _elapsed_since(total_start)
        analysis_path = artifact_store.save_json(
            _ANALYSIS_LABEL,
            {
                "analysis": analysis_payload,
                "device_id": session.info.device.identity.device_id,
                "frame": frame_payload,
                "launched": launch,
                "package": package_name,
                "session_id": session.info.session_id,
                "timings": saved_json_timings,
            },
            metadata=metadata,
        )
        timings["artifact_save"] = _elapsed_since(artifact_start)
    finally:
        await session.close()

    timings["total"] = _elapsed_since(total_start)

    return {
        "analysis": analysis_payload,
        "artifacts": {
            "analysis_json": str(analysis_path),
            "screenshot": str(screenshot_path),
        },
        "device_id": session.info.device.identity.device_id,
        "frame": frame_payload,
        "launched": launch,
        "output_dir": str(artifact_store.root),
        "package": package_name,
        "run_dir": str(artifact_store.run_dir),
        "session_id": session.info.session_id,
        "timings": timings,
    }


def serialize_screen_analysis(analysis: ScreenAnalysis) -> dict[str, Any]:
    """Return a JSON-serializable representation of a screen analysis."""

    payload = _jsonable(analysis)
    if not isinstance(payload, dict):
        raise TypeError("serialized ScreenAnalysis must be a JSON object")
    return payload


def _serialize_frame(image: FrameImage) -> dict[str, Any]:
    return {
        "captured_at": image.captured_at.isoformat() if image.captured_at is not None else None,
        "frame_id": image.frame_id,
        "pixel_format": image.pixel_format.value,
        "size": {
            "height": image.size.height,
            "width": image.size.width,
        },
    }


def _artifact_metadata(
    *,
    session: AnalysisSession,
    image: FrameImage,
    package_name: str,
    launched: bool,
) -> dict[str, Any]:
    return {
        "device_id": session.info.device.identity.device_id,
        "frame_id": image.frame_id,
        "height": image.size.height,
        "launched": launched,
        "package": package_name,
        "pixel_format": image.pixel_format.value,
        "session_id": session.info.session_id,
        "width": image.size.width,
    }


def _empty_timings() -> dict[str, float]:
    return {field: 0.0 for field in _TIMING_FIELDS}


def _elapsed_since(start: float) -> float:
    return max(0.0, monotonic() - start)


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


__all__ = [
    "AnalysisBackend",
    "AnalysisSession",
    "DEFAULT_ARTIFACT_ROOT",
    "DEFAULT_CLASH_PACKAGE",
    "DEFAULT_LAUNCH_WAIT_SECONDS",
    "ScreenAnalyzer",
    "analyze_once",
    "serialize_screen_analysis",
]
