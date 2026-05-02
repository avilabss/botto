"""State snapshots produced by the read-only runtime loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from android_game_automator.image import FrameImage
from android_game_automator.types import SessionInfo

from botto.detection import ScreenAnalysis

if TYPE_CHECKING:
    from botto.automation.actions import ActionExecutor


@dataclass(frozen=True, slots=True)
class RuntimeAnalysisSnapshot:
    """Latest screen analysis plus timing metadata for runtime consumers."""

    analysis: ScreenAnalysis
    analyzed_at: float
    duration_seconds: float | None = None
    frame_id: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeLoopState:
    """Current frame and analysis state delivered to a runtime sink."""

    frame: FrameImage | None
    analysis_snapshot: RuntimeAnalysisSnapshot | None
    now: float
    analysis_running: bool
    session_info: SessionInfo
    action_executor: ActionExecutor | None = None
    _analysis_snapshot_refresher: Callable[[], RuntimeAnalysisSnapshot | None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def refresh_analysis_snapshot(self) -> RuntimeAnalysisSnapshot | None:
        """Harvest completed analysis, if available, and return the latest snapshot."""

        if self._analysis_snapshot_refresher is None:
            return self.analysis_snapshot
        return self._analysis_snapshot_refresher()


__all__ = ["RuntimeAnalysisSnapshot", "RuntimeLoopState"]
