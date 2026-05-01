"""Read-only scrcpy live preview and debug flows for Botto."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from math import isfinite
from os import PathLike
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
from android_game_automator.artifacts import ArtifactStore
from android_game_automator.image import FrameImage
from android_game_automator.scrcpy import DEFAULT_SCRCPY_MAX_FPS, ScrcpyFrameSource
from android_game_automator.types import (
    NormalizedPoint,
    NormalizedRect,
    PixelFormat,
    Point,
    Rect,
    SessionInfo,
    Size,
    Viewport,
)

from android_game_automator.adb import AdbDeviceBackend
from botto.runner import DEFAULT_ARTIFACT_ROOT, DEFAULT_CLASH_PACKAGE, serialize_screen_analysis
from botto.screen_detector import analyze_screen
from botto.screens import Overlay, ScreenAnalysis

DEFAULT_LIVE_DEBUG_WINDOW_TITLE = "Botto live debug"
DEFAULT_LIVE_DEBUG_ANALYZE_EVERY_SECONDS = 1.0
DEFAULT_LIVE_PREVIEW_WINDOW_TITLE = "Botto live preview"
EXIT_KEY_CODES = frozenset((27, ord("q")))
_SAVE_RAW_KEY_CODE = ord("s")
_SAVE_DEBUG_KEY_CODE = ord("d")
_SAVE_STATUS_SECONDS = 3.0

type BgrArray = npt.NDArray[np.uint8]
type ClockFn = Callable[[], float]
type BgrColor = tuple[int, int, int]
type StatusWriter = Callable[[str], None]

_STATUS_TEXT_COLOR: BgrColor = (255, 255, 255)
_STATUS_BACKGROUND_COLOR: BgrColor = (0, 0, 0)
_NORMAL_BOUNDS_COLOR: BgrColor = (40, 210, 40)
_NORMAL_REGION_COLOR: BgrColor = (255, 210, 40)
_PROBLEM_BOUNDS_COLOR: BgrColor = (40, 40, 255)
_PROBLEM_REGION_COLOR: BgrColor = (0, 165, 255)
_TARGET_COLOR: BgrColor = (255, 0, 255)
_TEXT_SCALE = 0.5
_TEXT_THICKNESS = 1
_LINE_THICKNESS = 2


class LivePreviewSession(Protocol):
    """ADB session operations used by live preview."""

    @property
    def info(self) -> SessionInfo: ...

    async def close(self) -> None: ...

    async def launch_app(self, package_name: str) -> None: ...


class LivePreviewBackend(Protocol):
    """Backend operations used by live preview."""

    async def open_session(self, device_id: str | None = None) -> LivePreviewSession: ...


class LiveFrameSource(Protocol):
    """Read-only frame source operations used by live preview."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def latest_frame(self) -> FrameImage | None: ...

    def frames(self) -> Iterator[FrameImage]: ...


class LiveFrameSourceFactory(Protocol):
    """Factory for creating a source once the ADB device id is resolved."""

    def __call__(self, *, serial: str, max_fps: int) -> LiveFrameSource: ...


class LiveScreenAnalyzer(Protocol):
    """Callable used by live debug to analyze throttled frames."""

    def __call__(self, image: FrameImage) -> ScreenAnalysis: ...


@dataclass(frozen=True, slots=True)
class LiveAnalysisSnapshot:
    """Latest screen analysis plus timing metadata for overlay display."""

    analysis: ScreenAnalysis
    analyzed_at: float
    duration_seconds: float | None = None
    frame_id: str | None = None


class DebugOverlayRenderer(Protocol):
    """Callable that annotates a frame with the latest live debug state."""

    def __call__(
        self,
        frame: FrameImage,
        snapshot: LiveAnalysisSnapshot | None,
        *,
        now: float | None = None,
        analysis_running: bool = False,
    ) -> FrameImage: ...


@dataclass(frozen=True, slots=True)
class _PendingLiveAnalysis:
    future: asyncio.Future[ScreenAnalysis]
    started_at: float
    frame_id: str | None


@dataclass(frozen=True, slots=True)
class _SavedLiveDebugArtifacts:
    kind: str
    label: str
    image_path: Path
    analysis_path: Path | None = None


class PreviewWindow(Protocol):
    """OpenCV-like preview window operations used by the read-only loop."""

    def open(self, window_title: str) -> None: ...

    def show(self, window_title: str, frame: FrameImage) -> None: ...

    def wait_key(self, delay_ms: int) -> int: ...

    def close(self, window_title: str) -> None: ...


class OpenCvPreviewWindow:
    """Small OpenCV HighGUI adapter for displaying SDK ``FrameImage`` frames."""

    def open(self, window_title: str) -> None:
        import cv2

        cv2.namedWindow(window_title, cv2.WINDOW_NORMAL)

    def show(self, window_title: str, frame: FrameImage) -> None:
        import cv2

        cv2.imshow(window_title, frame_image_to_bgr_array(frame))

    def wait_key(self, delay_ms: int) -> int:
        import cv2

        return int(cv2.waitKey(delay_ms) & 0xFF)

    def close(self, window_title: str) -> None:
        import cv2

        cv2.destroyWindow(window_title)


async def run_live_preview(
    *,
    device_id: str | None = None,
    package_name: str = DEFAULT_CLASH_PACKAGE,
    launch: bool = True,
    max_fps: int = DEFAULT_SCRCPY_MAX_FPS,
    window_title: str = DEFAULT_LIVE_PREVIEW_WINDOW_TITLE,
    backend: LivePreviewBackend | None = None,
    source_factory: LiveFrameSourceFactory | None = None,
    preview_window: PreviewWindow | None = None,
) -> None:
    """Launch if requested and display live scrcpy frames until q/Esc exits."""

    if not package_name.strip():
        raise ValueError("package_name must be non-empty")
    if isinstance(max_fps, bool) or max_fps < 0:
        raise ValueError("max_fps must be >= 0")
    if not window_title.strip():
        raise ValueError("window_title must be non-empty")

    resolved_backend = backend if backend is not None else AdbDeviceBackend()
    resolved_source_factory = (
        source_factory if source_factory is not None else _default_live_frame_source_factory
    )
    window = preview_window if preview_window is not None else OpenCvPreviewWindow()

    session = await resolved_backend.open_session(device_id)
    source: LiveFrameSource | None = None
    window_opened = False
    try:
        if launch:
            await session.launch_app(package_name)

        serial = session.info.device.identity.device_id
        source = resolved_source_factory(serial=serial, max_fps=max_fps)
        source.start()

        window.open(window_title)
        window_opened = True
        for frame in source.frames():
            window.show(window_title, frame)
            if window.wait_key(1) in EXIT_KEY_CODES:
                break
    finally:
        try:
            if source is not None:
                source.stop()
        finally:
            try:
                if window_opened:
                    window.close(window_title)
            finally:
                await session.close()


async def run_live_debug(
    *,
    device_id: str | None = None,
    package_name: str = DEFAULT_CLASH_PACKAGE,
    launch: bool = True,
    max_fps: int = DEFAULT_SCRCPY_MAX_FPS,
    window_title: str = DEFAULT_LIVE_DEBUG_WINDOW_TITLE,
    analyze_every_seconds: float = DEFAULT_LIVE_DEBUG_ANALYZE_EVERY_SECONDS,
    artifact_root: str | PathLike[str] = DEFAULT_ARTIFACT_ROOT,
    run_name: str | None = None,
    backend: LivePreviewBackend | None = None,
    source_factory: LiveFrameSourceFactory | None = None,
    preview_window: PreviewWindow | None = None,
    screen_analyzer: LiveScreenAnalyzer | None = None,
    overlay_renderer: DebugOverlayRenderer | None = None,
    status_writer: StatusWriter | None = None,
    clock: ClockFn = monotonic,
) -> None:
    """Display live scrcpy frames with throttled read-only detector annotations."""

    if not package_name.strip():
        raise ValueError("package_name must be non-empty")
    if isinstance(max_fps, bool) or max_fps < 0:
        raise ValueError("max_fps must be >= 0")
    if not window_title.strip():
        raise ValueError("window_title must be non-empty")
    if analyze_every_seconds <= 0:
        raise ValueError("analyze_every_seconds must be > 0")

    resolved_backend = backend if backend is not None else AdbDeviceBackend()
    resolved_source_factory = (
        source_factory if source_factory is not None else _default_live_frame_source_factory
    )
    window = preview_window if preview_window is not None else OpenCvPreviewWindow()
    analyzer = screen_analyzer if screen_analyzer is not None else analyze_screen

    session = await resolved_backend.open_session(device_id)
    source: LiveFrameSource | None = None
    window_opened = False
    latest_snapshot: LiveAnalysisSnapshot | None = None
    last_analysis_started_at: float | None = None
    pending_analysis: _PendingLiveAnalysis | None = None
    artifact_store: ArtifactStore | None = None
    artifact_sequence = 0
    save_status_message: str | None = None
    save_status_until = 0.0
    analysis_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="botto-live-debug-analysis",
    )

    def complete_pending_analysis_if_ready() -> None:
        nonlocal latest_snapshot, pending_analysis
        if pending_analysis is not None and pending_analysis.future.done():
            latest_snapshot = _completed_live_analysis_snapshot(pending_analysis, clock=clock)
            pending_analysis = None

    def get_artifact_store() -> ArtifactStore:
        nonlocal artifact_store
        if artifact_store is None:
            artifact_store = ArtifactStore(artifact_root, run_name=run_name)
        return artifact_store

    def save_artifacts_for_hotkey(
        *,
        key_code: int,
        raw_frame: FrameImage,
        annotated_frame: FrameImage,
        now: float,
    ) -> _SavedLiveDebugArtifacts | None:
        nonlocal artifact_sequence, save_status_message, save_status_until

        if key_code == _SAVE_RAW_KEY_CODE:
            kind = "raw"
            image = raw_frame
            hotkey = "s"
        elif key_code == _SAVE_DEBUG_KEY_CODE:
            kind = "debug"
            image = annotated_frame
            hotkey = "d"
        else:
            return None

        complete_pending_analysis_if_ready()
        artifact_sequence += 1
        label = _live_debug_artifact_label(kind=kind, sequence=artifact_sequence)
        saved = _save_live_debug_artifacts(
            store=get_artifact_store(),
            label=label,
            kind=kind,
            hotkey=hotkey,
            image=image,
            snapshot=latest_snapshot,
            session_info=session.info,
            package_name=package_name,
            launched=launch,
        )
        save_status_message = _live_debug_overlay_save_message(saved)
        save_status_until = now + _SAVE_STATUS_SECONDS
        if status_writer is not None:
            status_writer(_live_debug_stdout_save_message(saved))
        return saved

    try:
        if launch:
            await session.launch_app(package_name)

        serial = session.info.device.identity.device_id
        source = resolved_source_factory(serial=serial, max_fps=max_fps)
        source.start()

        window.open(window_title)
        window_opened = True
        while True:
            complete_pending_analysis_if_ready()

            frame = source.latest_frame()
            frame_time = clock()
            if frame is None:
                if window.wait_key(1) in EXIT_KEY_CODES:
                    break
                await asyncio.sleep(0)
                continue

            if pending_analysis is None and (
                last_analysis_started_at is None
                or frame_time - last_analysis_started_at >= analyze_every_seconds
            ):
                last_analysis_started_at = frame_time
                pending_analysis = _start_live_analysis(
                    analyzer,
                    frame,
                    started_at=frame_time,
                    executor=analysis_executor,
                )

            if save_status_message is not None and frame_time > save_status_until:
                save_status_message = None
            active_save_status = save_status_message
            if overlay_renderer is None:
                annotated_frame = render_debug_overlay(
                    frame,
                    latest_snapshot,
                    now=frame_time,
                    analysis_running=pending_analysis is not None,
                    status_message=active_save_status,
                )
            else:
                annotated_frame = overlay_renderer(
                    frame,
                    latest_snapshot,
                    now=frame_time,
                    analysis_running=pending_analysis is not None,
                )
            window.show(window_title, annotated_frame)
            key_code = window.wait_key(1)
            if key_code in EXIT_KEY_CODES:
                break
            save_artifacts_for_hotkey(
                key_code=key_code,
                raw_frame=frame,
                annotated_frame=annotated_frame,
                now=frame_time,
            )
            await asyncio.sleep(0)
    finally:
        try:
            if source is not None:
                source.stop()
        finally:
            try:
                if window_opened:
                    window.close(window_title)
            finally:
                try:
                    await session.close()
                finally:
                    try:
                        await _finish_pending_live_analysis(pending_analysis)
                    finally:
                        analysis_executor.shutdown(wait=True, cancel_futures=True)


def _start_live_analysis(
    analyzer: LiveScreenAnalyzer,
    frame: FrameImage,
    *,
    started_at: float,
    executor: ThreadPoolExecutor,
) -> _PendingLiveAnalysis:
    loop = asyncio.get_running_loop()
    return _PendingLiveAnalysis(
        future=loop.run_in_executor(executor, analyzer, frame),
        started_at=started_at,
        frame_id=frame.frame_id,
    )


def _completed_live_analysis_snapshot(
    pending: _PendingLiveAnalysis,
    *,
    clock: ClockFn,
) -> LiveAnalysisSnapshot:
    analysis = pending.future.result()
    finished_at = clock()
    return LiveAnalysisSnapshot(
        analysis=analysis,
        analyzed_at=finished_at,
        duration_seconds=max(0.0, finished_at - pending.started_at),
        frame_id=pending.frame_id,
    )


async def _finish_pending_live_analysis(pending: _PendingLiveAnalysis | None) -> None:
    if pending is None:
        return

    await asyncio.shield(pending.future)


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
        "analysis": serialize_screen_analysis(snapshot.analysis),
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


def render_debug_overlay(
    frame: FrameImage,
    snapshot: LiveAnalysisSnapshot | None,
    *,
    now: float | None = None,
    analysis_running: bool = False,
    status_message: str | None = None,
) -> FrameImage:
    """Return a copy of ``frame`` annotated with live detector state and evidence."""

    bgr = frame_image_to_bgr_array(frame)
    status_lines = _debug_status_lines(
        snapshot,
        now=now,
        analysis_running=analysis_running,
        frame_size=frame.size,
        status_message=status_message,
    )
    _draw_status_lines(bgr, status_lines)

    if snapshot is not None:
        analysis = snapshot.analysis
        evidence_is_problem = analysis.overlay is not Overlay.NONE
        for evidence in analysis.evidence:
            _draw_evidence(bgr, frame.size, evidence, is_problem=evidence_is_problem)
        _draw_recommended_action(bgr, frame.size, analysis)

    rgba = np.frombuffer(frame.data, dtype=np.uint8).reshape((frame.height, frame.width, 4))
    annotated_rgba = np.empty((frame.height, frame.width, 4), dtype=np.uint8)
    annotated_rgba[..., 0] = bgr[..., 2]
    annotated_rgba[..., 1] = bgr[..., 1]
    annotated_rgba[..., 2] = bgr[..., 0]
    annotated_rgba[..., 3] = rgba[..., 3]
    return FrameImage(
        size=frame.size,
        pixel_format=PixelFormat.RGBA32,
        data=annotated_rgba.tobytes(),
        captured_at=frame.captured_at,
        frame_id=frame.frame_id,
    )


def frame_image_to_bgr_array(frame: FrameImage) -> BgrArray:
    """Convert SDK RGBA32 frame data into BGR pixels for ``cv2.imshow``."""

    if frame.pixel_format is not PixelFormat.RGBA32:
        raise ValueError("live preview expects RGBA32 FrameImage data")

    rgba = np.frombuffer(frame.data, dtype=np.uint8).reshape((frame.height, frame.width, 4))
    bgr = np.empty((frame.height, frame.width, 3), dtype=np.uint8)
    bgr[..., 0] = rgba[..., 2]
    bgr[..., 1] = rgba[..., 1]
    bgr[..., 2] = rgba[..., 0]
    return bgr


def _debug_status_lines(
    snapshot: LiveAnalysisSnapshot | None,
    *,
    now: float | None,
    analysis_running: bool = False,
    frame_size: Size | None = None,
    status_message: str | None = None,
) -> tuple[str, ...]:
    lines: list[str] = []
    if frame_size is not None:
        lines.append(f"frame: {frame_size.width}x{frame_size.height}")

    if snapshot is None:
        lines.append("analysis: running" if analysis_running else "analysis: pending")
        if status_message:
            lines.append(status_message)
        return tuple(lines)

    analysis = snapshot.analysis
    lines.extend(
        (
            f"base: {analysis.base_screen.value}",
            f"overlay: {analysis.overlay.value}  conf: {analysis.confidence:.2f}",
        )
    )
    timing_parts: list[str] = []
    if now is not None:
        timing_parts.append(f"age: {max(0.0, now - snapshot.analyzed_at):.1f}s")
    if snapshot.duration_seconds is not None:
        timing_parts.append(f"took: {snapshot.duration_seconds:.2f}s")
    if analysis_running:
        timing_parts.append("running")
    if timing_parts:
        lines.append("analysis " + "  ".join(timing_parts))
    elif analysis_running:
        lines.append("analysis running")
    if status_message:
        lines.append(status_message)
    return tuple(lines)


def _draw_status_lines(bgr: BgrArray, lines: tuple[str, ...]) -> None:
    import cv2

    if not lines:
        return

    line_height = 18
    background_height = 8 + line_height * len(lines)
    cv2.rectangle(
        bgr,
        (0, 0),
        (min(bgr.shape[1] - 1, 420), min(bgr.shape[0] - 1, background_height)),
        _STATUS_BACKGROUND_COLOR,
        thickness=-1,
    )
    for index, line in enumerate(lines):
        cv2.putText(
            bgr,
            line,
            (8, 18 + index * line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            _TEXT_SCALE,
            _STATUS_TEXT_COLOR,
            _TEXT_THICKNESS,
            cv2.LINE_AA,
        )


def _draw_evidence(
    bgr: BgrArray,
    size: Size,
    evidence: object,
    *,
    is_problem: bool,
) -> None:
    details = getattr(evidence, "details", None)
    if not isinstance(details, Mapping):
        return

    label = _evidence_label(evidence)
    bounds = _coerce_rect(details.get("bounds"), size)
    region = _coerce_rect(details.get("region"), size)
    bounds_color = _PROBLEM_BOUNDS_COLOR if is_problem else _NORMAL_BOUNDS_COLOR
    region_color = _PROBLEM_REGION_COLOR if is_problem else _NORMAL_REGION_COLOR

    if region is not None:
        _draw_rect(bgr, region, region_color)
        _draw_label(bgr, label, region, region_color)
    if bounds is not None:
        _draw_rect(bgr, bounds, bounds_color)
        _draw_label(bgr, label, bounds, bounds_color)


def _draw_rect(bgr: BgrArray, rect: Rect, color: BgrColor) -> None:
    import cv2

    cv2.rectangle(
        bgr,
        (rect.left, rect.top),
        (rect.right - 1, rect.bottom - 1),
        color,
        thickness=_LINE_THICKNESS,
    )


def _draw_label(bgr: BgrArray, label: str, rect: Rect, color: BgrColor) -> None:
    import cv2

    if not label:
        return

    y = max(12, rect.top - 4)
    cv2.putText(
        bgr,
        label,
        (rect.left, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        _TEXT_SCALE,
        color,
        _TEXT_THICKNESS,
        cv2.LINE_AA,
    )


def _draw_recommended_action(bgr: BgrArray, size: Size, analysis: ScreenAnalysis) -> None:
    import cv2

    action = analysis.recommended_action
    if action is None or action.tap_target is None:
        return

    target = _coerce_point(action.tap_target, size)
    if target is None:
        return

    radius = 8
    cv2.circle(bgr, (target.x, target.y), radius, _TARGET_COLOR, thickness=_LINE_THICKNESS)
    cv2.line(
        bgr,
        (max(0, target.x - radius), target.y),
        (min(size.width - 1, target.x + radius), target.y),
        _TARGET_COLOR,
        thickness=_LINE_THICKNESS,
    )
    cv2.line(
        bgr,
        (target.x, max(0, target.y - radius)),
        (target.x, min(size.height - 1, target.y + radius)),
        _TARGET_COLOR,
        thickness=_LINE_THICKNESS,
    )
    cv2.putText(
        bgr,
        f"target: {action.label}",
        (max(0, target.x + 10), max(12, target.y - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        _TEXT_SCALE,
        _TARGET_COLOR,
        _TEXT_THICKNESS,
        cv2.LINE_AA,
    )


def _evidence_label(evidence: object) -> str:
    label = str(getattr(evidence, "label", "")).strip()
    confidence = getattr(evidence, "confidence", None)
    if isinstance(confidence, int | float) and not isinstance(confidence, bool):
        return f"{label} {confidence:.2f}" if label else f"{confidence:.2f}"
    return label


def _coerce_rect(value: object, size: Size) -> Rect | None:
    if isinstance(value, Rect):
        return _clip_rect(value.left, value.top, value.width, value.height, size)
    if isinstance(value, NormalizedRect):
        return _map_normalized_rect(value, size)

    components = _rect_components(value)
    if components is None:
        return None

    left, top, width, height = components
    if _looks_normalized_rect(left, top, width, height):
        try:
            return _map_normalized_rect(
                NormalizedRect(left=left, top=top, width=width, height=height),
                size,
            )
        except ValueError:
            return None
    return _clip_rect(round(left), round(top), round(width), round(height), size)


def _map_normalized_rect(rect: NormalizedRect, size: Size) -> Rect | None:
    try:
        mapped = Viewport(surface_size=size).map_rect(rect)
    except ValueError:
        return None
    return _clip_rect(mapped.left, mapped.top, mapped.width, mapped.height, size)


def _rect_components(value: object) -> tuple[float, float, float, float] | None:
    raw_components: tuple[object, object, object, object] | None
    if isinstance(value, Mapping):
        try:
            raw_components = (
                value["left"],
                value["top"],
                value["width"],
                value["height"],
            )
        except KeyError:
            return None
    elif all(hasattr(value, name) for name in ("left", "top", "width", "height")):
        raw_components = (
            _attribute(value, "left"),
            _attribute(value, "top"),
            _attribute(value, "width"),
            _attribute(value, "height"),
        )
    else:
        return None

    left = _number(raw_components[0])
    top = _number(raw_components[1])
    width = _number(raw_components[2])
    height = _number(raw_components[3])
    if left is None or top is None or width is None or height is None:
        return None
    if width <= 0 or height <= 0:
        return None
    return left, top, width, height


def _coerce_point(value: object, size: Size) -> Point | None:
    if isinstance(value, Point):
        return _point_within_size(value, size)
    if isinstance(value, NormalizedPoint):
        try:
            return Viewport(surface_size=size).map_point(value)
        except ValueError:
            return None

    components = _point_components(value)
    if components is None:
        return None

    x, y = components
    if _looks_normalized_point(x, y):
        try:
            return Viewport(surface_size=size).map_point(NormalizedPoint(x=x, y=y))
        except ValueError:
            return None
    return _point_from_components(round(x), round(y), size)


def _point_components(value: object) -> tuple[float, float] | None:
    raw_components: tuple[object, object] | None
    if isinstance(value, Mapping):
        try:
            raw_components = (value["x"], value["y"])
        except KeyError:
            return None
    elif all(hasattr(value, name) for name in ("x", "y")):
        raw_components = (_attribute(value, "x"), _attribute(value, "y"))
    else:
        return None

    x = _number(raw_components[0])
    y = _number(raw_components[1])
    if x is None or y is None:
        return None
    return x, y


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not isfinite(number):
        return None
    return number


def _attribute(value: object, name: str) -> object:
    return getattr(value, name)


def _looks_normalized_rect(left: float, top: float, width: float, height: float) -> bool:
    return (
        0.0 <= left <= 1.0
        and 0.0 <= top <= 1.0
        and 0.0 < width <= 1.0
        and 0.0 < height <= 1.0
        and left + width <= 1.0
        and top + height <= 1.0
    )


def _looks_normalized_point(x: float, y: float) -> bool:
    return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def _clip_rect(left: int, top: int, width: int, height: int, size: Size) -> Rect | None:
    if width <= 0 or height <= 0:
        return None

    right = left + width
    bottom = top + height
    clipped_left = min(max(left, 0), size.width)
    clipped_top = min(max(top, 0), size.height)
    clipped_right = min(max(right, 0), size.width)
    clipped_bottom = min(max(bottom, 0), size.height)
    if clipped_left >= clipped_right or clipped_top >= clipped_bottom:
        return None
    return Rect(
        left=clipped_left,
        top=clipped_top,
        width=clipped_right - clipped_left,
        height=clipped_bottom - clipped_top,
    )


def _point_within_size(point: Point, size: Size) -> Point | None:
    if not (0 <= point.x < size.width and 0 <= point.y < size.height):
        return None
    return point


def _point_from_components(x: int, y: int, size: Size) -> Point | None:
    if not (0 <= x < size.width and 0 <= y < size.height):
        return None
    return Point(x=x, y=y)


def _default_live_frame_source_factory(*, serial: str, max_fps: int) -> LiveFrameSource:
    return ScrcpyFrameSource(serial=serial, max_fps=max_fps)


__all__ = [
    "DEFAULT_LIVE_DEBUG_ANALYZE_EVERY_SECONDS",
    "DEFAULT_LIVE_DEBUG_WINDOW_TITLE",
    "DEFAULT_LIVE_PREVIEW_WINDOW_TITLE",
    "DebugOverlayRenderer",
    "EXIT_KEY_CODES",
    "LiveAnalysisSnapshot",
    "LiveFrameSource",
    "LiveFrameSourceFactory",
    "LivePreviewBackend",
    "LivePreviewSession",
    "LiveScreenAnalyzer",
    "OpenCvPreviewWindow",
    "PreviewWindow",
    "frame_image_to_bgr_array",
    "render_debug_overlay",
    "run_live_debug",
    "run_live_preview",
]
