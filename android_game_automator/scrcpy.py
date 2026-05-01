"""scrcpy-backed live frame source helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Protocol, Self

import numpy as np
import numpy.typing as npt
from py_scrcpy_sdk import ScrcpyClient as _PyScrcpyClient  # type: ignore[import-untyped]
from py_scrcpy_sdk import ScrcpyConfig as _PyScrcpyConfig  # type: ignore[import-untyped]

from android_game_automator.image import FrameImage
from android_game_automator.types import PixelFormat, Size

DEFAULT_SCRCPY_MAX_FPS = 30

type ScrcpyFrameArray = npt.NDArray[np.uint8]
type FrameCallback = Callable[[FrameImage], object]


@dataclass(frozen=True, slots=True)
class ScrcpySourceConfig:
    """Configuration for a scrcpy live frame source."""

    serial: str | None = None
    max_fps: int = DEFAULT_SCRCPY_MAX_FPS

    def __post_init__(self) -> None:
        if self.serial is not None and not self.serial.strip():
            raise ValueError("serial must be non-empty when provided")
        if isinstance(self.max_fps, bool) or self.max_fps < 0:
            raise ValueError("max_fps must be >= 0")


class ScrcpyClient(Protocol):
    """Subset of py-scrcpy-sdk's client API used for read-only frames."""

    latest_frame: ScrcpyFrameArray | None
    frame_counter: int

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def get_frame(self, *, timeout: float | None = None, copy: bool = True) -> ScrcpyFrameArray: ...

    def frames(
        self, *, copy: bool = True, timeout: float | None = None
    ) -> Iterator[ScrcpyFrameArray]: ...


class ScrcpyClientFactory(Protocol):
    """Factory for constructing a scrcpy client from source configuration."""

    def __call__(self, config: ScrcpySourceConfig) -> ScrcpyClient: ...


class ScrcpyFrameSource:
    """Read-only scrcpy frame source that exposes SDK ``FrameImage`` objects."""

    def __init__(
        self,
        *,
        serial: str | None = None,
        max_fps: int = DEFAULT_SCRCPY_MAX_FPS,
        client_factory: ScrcpyClientFactory | None = None,
    ) -> None:
        self._config = ScrcpySourceConfig(serial=serial, max_fps=max_fps)
        self._client_factory = client_factory if client_factory is not None else _create_client
        self._client: ScrcpyClient | None = None
        self._started = False

    @property
    def config(self) -> ScrcpySourceConfig:
        return self._config

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        """Start the underlying scrcpy client once."""

        if self._started:
            return

        client = self._client if self._client is not None else self._client_factory(self._config)
        self._client = client
        try:
            client.start()
        except Exception:
            with suppress(Exception):
                client.stop()
            self._started = False
            raise
        self._started = True

    def stop(self) -> None:
        """Stop the underlying scrcpy client if it was started."""

        client = self._client
        if client is None or not self._started:
            return

        try:
            client.stop()
        finally:
            self._started = False

    def close(self) -> None:
        """Alias for ``stop`` for callers using close-style cleanup."""

        self.stop()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type, exc, traceback
        self.stop()

    def latest_frame(self) -> FrameImage | None:
        """Return the most recent decoded frame, if scrcpy has produced one."""

        client = self._client
        if client is None or client.latest_frame is None:
            return None
        return frame_image_from_scrcpy_frame(
            client.latest_frame,
            captured_at=datetime.now(UTC),
            frame_id=_frame_id(client),
        )

    def wait_for_frame(self, *, timeout: float | None = None) -> FrameImage:
        """Wait for one decoded frame and return it as RGBA32 ``FrameImage``."""

        client = self._require_started_client()
        return frame_image_from_scrcpy_frame(
            client.get_frame(timeout=timeout, copy=True),
            captured_at=datetime.now(UTC),
            frame_id=_frame_id(client),
        )

    def frames(self, *, timeout: float | None = None) -> Iterator[FrameImage]:
        """Yield decoded scrcpy frames as RGBA32 ``FrameImage`` objects."""

        client = self._require_started_client()
        for frame in client.frames(copy=True, timeout=timeout):
            yield frame_image_from_scrcpy_frame(
                frame,
                captured_at=datetime.now(UTC),
                frame_id=_frame_id(client),
            )

    def listen(
        self,
        callback: FrameCallback,
        *,
        timeout: float | None = None,
        stop_on_false: bool = True,
    ) -> None:
        """Call ``callback`` for each decoded frame until the stream or callback stops."""

        for frame in self.frames(timeout=timeout):
            result = callback(frame)
            if stop_on_false and result is False:
                break

    def _require_started_client(self) -> ScrcpyClient:
        if self._client is None or not self._started:
            raise RuntimeError("scrcpy frame source is not started")
        return self._client


def frame_image_from_scrcpy_frame(
    frame: npt.ArrayLike,
    *,
    captured_at: datetime | None = None,
    frame_id: str | None = None,
) -> FrameImage:
    """Convert a py-scrcpy-sdk BGR/BGRA frame into SDK RGBA32 pixels."""

    array = np.asarray(frame)
    if array.ndim != 3:
        raise ValueError("scrcpy frame must have shape (height, width, channels)")
    height = int(array.shape[0])
    width = int(array.shape[1])
    channels = int(array.shape[2])
    if channels not in (3, 4):
        raise ValueError("scrcpy frame must have 3 BGR or 4 BGRA channels")
    if array.dtype != np.uint8:
        raise ValueError("scrcpy frame dtype must be uint8")

    source = np.ascontiguousarray(array)
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = source[..., 2]
    rgba[..., 1] = source[..., 1]
    rgba[..., 2] = source[..., 0]
    if channels == 4:
        rgba[..., 3] = source[..., 3]
    else:
        rgba[..., 3] = 255

    return FrameImage(
        size=Size(width=width, height=height),
        pixel_format=PixelFormat.RGBA32,
        data=rgba.tobytes(),
        captured_at=captured_at,
        frame_id=frame_id,
    )


def _create_client(config: ScrcpySourceConfig) -> ScrcpyClient:
    return _PyScrcpyClient(
        _PyScrcpyConfig(
            serial=config.serial,
            max_fps=config.max_fps,
        )
    )


def _frame_id(client: ScrcpyClient) -> str | None:
    counter = client.frame_counter
    if counter > 0:
        return f"scrcpy:{counter}"
    return None


__all__ = [
    "DEFAULT_SCRCPY_MAX_FPS",
    "FrameCallback",
    "ScrcpyClient",
    "ScrcpyClientFactory",
    "ScrcpyFrameArray",
    "ScrcpyFrameSource",
    "ScrcpySourceConfig",
    "frame_image_from_scrcpy_frame",
]
