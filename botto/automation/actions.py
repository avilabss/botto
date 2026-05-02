"""Normalized gameplay action primitives for Botto."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from android_game_automator.types import NormalizedPoint, Point, Size, Viewport

_LOGGER = logging.getLogger(__name__)


class ActionBackend(Protocol):
    """Minimal absolute-coordinate control surface used by Botto actions."""

    @property
    def action_surface_size(self) -> Size: ...

    def tap_pixels(self, point: Point, *, hold_seconds: float = 0.05) -> None: ...

    def swipe_pixels(
        self,
        start: Point,
        end: Point,
        *,
        duration_ms: int = 300,
        steps: int = 12,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ActionExecutor:
    """Execute normalized gameplay actions through one sanctioned Botto API."""

    backend: ActionBackend

    def tap(
        self,
        point: NormalizedPoint,
        *,
        label: str | None = None,
        reason: str | None = None,
        hold_seconds: float = 0.05,
    ) -> Point:
        """Map a normalized point to pixels and tap it through the backend."""

        pixel = self._map_point(point)
        _LOGGER.debug(
            "Executing tap action label=%r reason=%r normalized=(%.6f, %.6f) pixel=(%d, %d)",
            label,
            reason,
            point.x,
            point.y,
            pixel.x,
            pixel.y,
        )
        self.backend.tap_pixels(pixel, hold_seconds=hold_seconds)
        return pixel

    def swipe(
        self,
        start: NormalizedPoint,
        end: NormalizedPoint,
        *,
        label: str | None = None,
        reason: str | None = None,
        duration_ms: int = 300,
        steps: int = 12,
    ) -> tuple[Point, Point]:
        """Map normalized endpoints to pixels and swipe through the backend."""

        start_pixel = self._map_point(start)
        end_pixel = self._map_point(end)
        _LOGGER.debug(
            "Executing swipe action label=%r reason=%r "
            "start_normalized=(%.6f, %.6f) end_normalized=(%.6f, %.6f) "
            "start_pixel=(%d, %d) end_pixel=(%d, %d) duration_ms=%d steps=%d",
            label,
            reason,
            start.x,
            start.y,
            end.x,
            end.y,
            start_pixel.x,
            start_pixel.y,
            end_pixel.x,
            end_pixel.y,
            duration_ms,
            steps,
        )
        self.backend.swipe_pixels(
            start_pixel,
            end_pixel,
            duration_ms=duration_ms,
            steps=steps,
        )
        return start_pixel, end_pixel

    def _map_point(self, point: NormalizedPoint) -> Point:
        return Viewport(self.backend.action_surface_size).map_point(point)


GameActionExecutor = ActionExecutor


__all__ = [
    "ActionBackend",
    "ActionExecutor",
    "GameActionExecutor",
]
