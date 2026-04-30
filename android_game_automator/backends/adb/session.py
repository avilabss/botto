"""ADB-backed device session, display helpers, and input execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from android_game_automator.core import (
    CapturedFrame,
    InputAction,
    InputActionResult,
    InputStatus,
    NormalizedPoint,
    SessionInfo,
    Size,
    SwipeAction,
    TapAction,
    Viewport,
)

from ._capture import decode_screencap_png, normalize_shell_screencap_output
from ._input import AdbInputHumanizationPolicy, build_adb_input_command
from ._parsing import (
    orient_size_for_rotation,
    parse_display_size,
    parse_rotation_quadrants,
    parse_wm_size,
)
from ._types import AdbDeviceHandle
from .errors import AdbDisplayStateError, AdbFrameCaptureError, AdbSessionClosedError


@dataclass(frozen=True, slots=True)
class AdbDisplayState:
    """Current display dimensions and rotation metadata."""

    size: Size
    rotation_quadrants: int

    def __post_init__(self) -> None:
        if self.rotation_quadrants not in (0, 1, 2, 3):
            raise ValueError("rotation_quadrants must be one of 0, 1, 2, 3")

    @property
    def viewport(self) -> Viewport:
        """The full active display as a generic viewport."""
        return Viewport(surface_size=self.size)


@dataclass(frozen=True, slots=True)
class AdbDefaultViewports:
    """Default full-surface viewports for the current frame and display."""

    frame: Viewport
    display: Viewport


def build_default_viewports(
    frame: CapturedFrame,
    display_state: AdbDisplayState,
) -> AdbDefaultViewports:
    """Build the honest default full-surface frame/display viewports.

    This deliberately avoids inferring content areas or letterboxing that adb output
    cannot establish reliably.
    """
    return AdbDefaultViewports(
        frame=Viewport(surface_size=frame.metadata.size),
        display=display_state.viewport,
    )


class AdbDeviceSession:
    """Concrete AsyncDeviceSession implementation for ADB devices."""

    def __init__(
        self,
        device: AdbDeviceHandle,
        info: SessionInfo,
        input_humanization: AdbInputHumanizationPolicy | None = None,
    ) -> None:
        self._device = device
        self._info = info
        self._closed = False
        self._input_humanization = (
            input_humanization
            if input_humanization is not None
            else AdbInputHumanizationPolicy()
        )

    @property
    def info(self) -> SessionInfo:
        return self._info

    async def close(self) -> None:
        self._closed = True

    async def is_healthy(self) -> bool:
        """Return whether adb still reports this session device as healthy."""
        if self._closed:
            return False

        try:
            return (await self._device.get_state()).strip() == "device"
        except Exception:
            return False

    async def get_rotation_quadrants(self) -> int:
        """Return the current display rotation in quarter turns (0-3)."""
        return await self._get_rotation_quadrants()

    async def get_display_state(self) -> AdbDisplayState:
        """Return current display size adjusted to orientation."""
        rotation = await self._get_rotation_quadrants()
        size = await self._get_display_size()
        oriented_size = orient_size_for_rotation(size, rotation)
        return AdbDisplayState(size=oriented_size, rotation_quadrants=rotation)

    async def capture_frame(self) -> CapturedFrame:
        """Capture the latest device screenshot as decoded RGBA pixels."""
        self._ensure_open()

        errors: list[Exception] = []
        for capture, normalize in (
            (self._run_exec_bytes, False),
            (self._run_shell_bytes, True),
        ):
            try:
                output = await capture("screencap -p")
            except Exception as exc:
                errors.append(exc)
                continue

            candidates: tuple[bytes, ...] = (output,)
            if normalize:
                normalized_output = normalize_shell_screencap_output(output)
                if normalized_output != output:
                    candidates = (output, normalized_output)

            for candidate in candidates:
                try:
                    return decode_screencap_png(candidate)
                except AdbFrameCaptureError as exc:
                    errors.append(exc)

        raise AdbFrameCaptureError("Unable to capture a screenshot through adb.") from (
            errors[-1] if errors else None
        )

    async def execute_input(self, action: InputAction) -> InputActionResult:
        """Execute a single ADB-backed input action."""
        self._ensure_open()

        try:
            viewport = None
            if _action_requires_viewport(action):
                viewport = (await self.get_display_state()).viewport
            command = build_adb_input_command(
                action,
                viewport=viewport,
                humanization=self._input_humanization,
            )
        except Exception as exc:
            return InputActionResult(
                action_kind=action.kind,
                status=InputStatus.FAILED,
                completed_at=datetime.now(UTC),
                message=str(exc),
            )

        if command.rejection_message is not None:
            return InputActionResult(
                action_kind=action.kind,
                status=InputStatus.REJECTED,
                completed_at=datetime.now(UTC),
                message=command.rejection_message,
            )

        try:
            await self._run_shell(command.shell_command)
        except Exception as exc:
            return InputActionResult(
                action_kind=action.kind,
                status=InputStatus.FAILED,
                completed_at=datetime.now(UTC),
                message=str(exc),
            )

        return InputActionResult(
            action_kind=action.kind,
            status=InputStatus.APPLIED,
            completed_at=datetime.now(UTC),
        )
    async def _get_rotation_quadrants(self) -> int:
        self._ensure_open()

        for command in ("dumpsys input", "dumpsys display", "dumpsys window displays"):
            output = await self._try_shell(command)
            if output is None:
                continue
            rotation = parse_rotation_quadrants(output)
            if rotation is not None:
                return rotation

        raise AdbDisplayStateError("Unable to determine display rotation from adb output.")

    async def _get_display_size(self) -> Size:
        self._ensure_open()

        wm_output = await self._try_shell("wm size")
        if wm_output is not None:
            wm_size = parse_wm_size(wm_output)
            if wm_size is not None:
                return wm_size

        for command in ("dumpsys display", "dumpsys window displays"):
            output = await self._try_shell(command)
            if output is None:
                continue
            display_size = parse_display_size(output)
            if display_size is not None:
                return display_size

        raise AdbDisplayStateError("Unable to determine display size from adb output.")

    async def _run_shell(self, command: str) -> str:
        output = await self._device.shell(command)
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return output

    async def _run_exec_bytes(self, command: str) -> bytes:
        transport = await self._device.open_transport()
        try:
            await transport.send_command(f"exec:{command}")
            output = await transport.read_until_close(encoding=None)
        finally:
            await transport.close()

        if isinstance(output, bytes):
            return output
        return output.encode("utf-8", errors="surrogateescape")

    async def _run_shell_bytes(self, command: str) -> bytes:
        output = await self._device.shell(command, encoding=None)
        if isinstance(output, bytes):
            return output
        return output.encode("utf-8", errors="surrogateescape")

    async def _try_shell(self, command: str) -> str | None:
        try:
            return await self._run_shell(command)
        except Exception:
            return None

    def _ensure_open(self) -> None:
        if self._closed:
            raise AdbSessionClosedError("ADB session is closed.")


def _action_requires_viewport(action: InputAction) -> bool:
    if isinstance(action, TapAction):
        return isinstance(action.point, NormalizedPoint)

    if isinstance(action, SwipeAction):
        return isinstance(action.start, NormalizedPoint) or isinstance(action.end, NormalizedPoint)

    return False
