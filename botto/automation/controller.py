"""Runtime automation controller for conservative attack-search navigation."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Protocol

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedPoint, Rect, Size

from botto.automation.battle import (
    BattleLootProgress,
    BattleLootTracker,
    read_active_battle_available_loot,
)
from botto.automation.config import BottoConfig
from botto.automation.planner import StrategyExecutionPlan, plan_strategy_execution
from botto.automation.search import (
    AttackEligibilityResult,
    AvailableLoot,
    BattleSearchTextReader,
    OpponentBaseMetadata,
    evaluate_attack_eligibility,
    read_opponent_base_metadata,
)
from botto.automation.strategy import AttackStrategy
from botto.detection import (
    ActionKind,
    BaseScreen,
    BattleTargetDetection,
    DeployableSlotDetection,
    Evidence,
    HomeElement,
    Overlay,
    PopupButton,
    ScreenAnalysis,
    ScreenElement,
    detect_air_defense_targets,
    detect_deployable_slots,
)

if TYPE_CHECKING:
    from botto.runtime import RuntimeAnalysisSnapshot, RuntimeLoopState

_LOGGER = logging.getLogger(__name__)

_ACTION_RETRY_COOLDOWN_SECONDS = 1.0

type _ActionSignature = tuple[str, ...]
type _DecisionSignature = tuple[str, ...]
type _SnapshotSignature = tuple[str | None, float]
type _OpponentMetadataReader = Callable[[FrameImage], OpponentBaseMetadata | None]
type _BattleLootReader = Callable[[FrameImage], AvailableLoot | None]
type _DeployableSlotDetector = Callable[[FrameImage], Iterable[DeployableSlotDetection]]
type _AirDefenseTargetDetector = Callable[[FrameImage], Iterable[BattleTargetDetection]]


class _StrategyPlanner(Protocol):
    def __call__(
        self,
        strategy: AttackStrategy,
        *,
        deployable_slots: Iterable[DeployableSlotDetection],
        battle_targets: Iterable[BattleTargetDetection],
    ) -> StrategyExecutionPlan: ...


class AutomationController:
    """Execute the first safe gameplay navigation actions from runtime state."""

    def __init__(
        self,
        config: BottoConfig | None = None,
        *,
        strategy: AttackStrategy | None = None,
        metadata_reader: _OpponentMetadataReader | None = None,
        battle_loot_reader: _BattleLootReader | None = None,
        text_reader: BattleSearchTextReader | None = None,
        deployable_slot_detector: _DeployableSlotDetector = detect_deployable_slots,
        air_defense_target_detector: _AirDefenseTargetDetector = detect_air_defense_targets,
        strategy_planner: _StrategyPlanner = plan_strategy_execution,
    ) -> None:
        self._config = config
        self._strategy = strategy
        self._metadata_reader = _resolve_metadata_reader(metadata_reader, text_reader)
        self._battle_loot_reader = _resolve_battle_loot_reader(battle_loot_reader, text_reader)
        self._battle_loot_tracker = BattleLootTracker()
        self._deployable_slot_detector = deployable_slot_detector
        self._air_defense_target_detector = air_defense_target_detector
        self._strategy_planner = strategy_planner
        self._last_action_signature: _ActionSignature | None = None
        self._last_action_snapshot_signature: _SnapshotSignature | None = None
        self._last_action_at: float | None = None
        self._last_logged_decision_signature: _DecisionSignature | None = None
        self._successful_next_taps = 0
        self._strategy_started_for_current_candidate = False
        self._surrender_requested_for_current_candidate = False
        self._surrender_confirmed_for_current_candidate = False
        self._completed_battle_cleanup_actions: set[_ActionSignature] = set()

    @property
    def strategy(self) -> AttackStrategy | None:
        """Return the loaded attack strategy for future automation steps."""

        return self._strategy

    def __call__(self, state: RuntimeLoopState) -> bool:
        """Handle one runtime loop state and return whether runtime should continue."""

        snapshot = state.analysis_snapshot
        if snapshot is None:
            self._log_decision_once(("idle", "no_analysis"), "Automation idle: no analysis yet")
            return True

        analysis = snapshot.analysis
        snapshot_signature = _snapshot_signature(snapshot)
        if self._recover_overlay(state, analysis, snapshot_signature):
            return True

        match analysis.base_screen:
            case BaseScreen.HOME_VILLAGE:
                self._reset_search_session()
                self._tap_home_attack(state, analysis, snapshot_signature)
            case BaseScreen.ATTACK_MENU:
                if self._tap_evidence_anchor(
                    state,
                    analysis,
                    snapshot_signature,
                    subject=BaseScreen.ATTACK_MENU,
                    anchor=ScreenElement.ATTACK_MENU_FIND_A_MATCH_BUTTON,
                    signature=("screen", BaseScreen.ATTACK_MENU.value, "find_a_match"),
                    label="attack_menu.find_a_match",
                    reason="open battle search",
                ):
                    self._reset_search_session()
            case BaseScreen.MY_ARMY:
                if self._tap_evidence_anchor(
                    state,
                    analysis,
                    snapshot_signature,
                    subject=BaseScreen.MY_ARMY,
                    anchor=ScreenElement.MY_ARMY_ATTACK_BUTTON,
                    signature=("screen", BaseScreen.MY_ARMY.value, "attack"),
                    label="my_army.attack",
                    reason="start multiplayer search",
                ):
                    self._reset_search_session()
            case BaseScreen.BATTLE_PREPARATION:
                self._handle_battle_preparation(state, analysis, snapshot_signature)
            case BaseScreen.BATTLE_IN_PROGRESS:
                self._handle_battle_in_progress(state, analysis, snapshot_signature)
            case BaseScreen.BATTLE_SURRENDER_CONFIRMATION:
                self._handle_battle_surrender_confirmation(state, analysis, snapshot_signature)
            case BaseScreen.BATTLE_RESULT:
                self._handle_battle_result(state, analysis, snapshot_signature)
            case BaseScreen.REWARD_CHEST:
                self._handle_reward_chest(state, analysis, snapshot_signature)
            case BaseScreen.STAR_BONUS:
                self._handle_star_bonus(state, analysis, snapshot_signature)
            case _:
                self._log_decision_once(
                    (
                        "idle",
                        analysis.base_screen.value,
                        analysis.overlay.value,
                    ),
                    "Automation idle: unsupported screen=%s overlay=%s",
                    analysis.base_screen.value,
                    analysis.overlay.value,
                )
        return True

    def _recover_overlay(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
    ) -> bool:
        if analysis.overlay is Overlay.NONE:
            return False

        action = analysis.recommended_action
        if action is None:
            self._log_decision_once(
                ("overlay", analysis.overlay.value, "no_recommended_action"),
                "Automation idle: overlay=%s has no recommended action",
                analysis.overlay.value,
            )
            return True
        if action.kind is not ActionKind.TAP:
            self._log_decision_once(
                ("overlay", analysis.overlay.value, "unsupported_action", action.kind.value),
                "Automation idle: overlay=%s recommended unsupported action=%s",
                analysis.overlay.value,
                action.kind.value,
            )
            return True

        point = _tap_point_from_matching_evidence(
            analysis,
            subject=analysis.overlay,
            anchor=action.target,
            frame=state.frame,
        )
        if point is None:
            self._log_decision_once(
                ("overlay", analysis.overlay.value, action.target.value, "no_bounds"),
                "Automation idle: overlay=%s button=%s has no evidence bounds",
                analysis.overlay.value,
                action.target.value,
            )
            return True

        self._tap(
            state,
            point,
            snapshot_signature,
            signature=("overlay", analysis.overlay.value, action.target.value),
            label=f"overlay.{analysis.overlay.value}.{action.target.value}",
            reason=f"recover overlay {analysis.overlay.value}",
        )
        return True

    def _tap_home_attack(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
    ) -> None:
        self._tap_evidence_anchor(
            state,
            analysis,
            snapshot_signature,
            subject=BaseScreen.HOME_VILLAGE,
            anchor=HomeElement.ATTACK_BUTTON,
            signature=("screen", BaseScreen.HOME_VILLAGE.value, "attack"),
            label="home.attack_button",
            reason="navigate from home to attack menu",
        )

    def _handle_battle_preparation(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
    ) -> None:
        if self._strategy_started_for_current_candidate:
            self._log_decision_once(
                (
                    "battle_search",
                    "strategy_started",
                    str(self._current_search_number()),
                ),
                "Strategy execution already started for current candidate; no battle-search action",
                level=logging.INFO,
            )
            return

        if self._config is None:
            self._log_decision_once(
                ("idle", BaseScreen.BATTLE_PREPARATION.value, "no_config"),
                "Automation idle: no Botto config available for battle search",
            )
            return
        if state.frame is None:
            self._log_decision_once(
                ("idle", BaseScreen.BATTLE_PREPARATION.value, "no_frame"),
                "Automation idle: no frame available for battle search metadata",
            )
            return

        metadata = self._read_metadata(state.frame)
        if metadata is None:
            self._log_decision_once(
                ("battle_search", "metadata_unreadable", str(self._current_search_number())),
                "Battle search metadata unreadable; no action",
            )
            return

        eligibility = evaluate_attack_eligibility(metadata, self._config)
        if eligibility.eligible:
            self._handle_eligible_candidate(state, snapshot_signature)
            return

        if not self._search_budget_remains():
            self._log_decision_once(
                ("battle_search", "budget_exhausted", str(self._current_search_number())),
                "Battle search budget exhausted; no Next action",
                level=logging.INFO,
            )
            return

        if self._tap_evidence_anchor(
            state,
            analysis,
            snapshot_signature,
            subject=BaseScreen.BATTLE_PREPARATION,
            anchor=ScreenElement.BATTLE_NEXT_BUTTON,
            signature=("screen", BaseScreen.BATTLE_PREPARATION.value, "next"),
            label="battle_search.next",
            reason=_ineligible_search_reason(eligibility),
        ):
            self._successful_next_taps += 1
            self._reset_strategy_execution_guard()

    def _handle_eligible_candidate(
        self,
        state: RuntimeLoopState,
        snapshot_signature: _SnapshotSignature,
    ) -> None:
        if self._strategy is None:
            self._log_decision_once(
                ("battle_search", "eligible", "no_strategy", str(self._current_search_number())),
                "Battle search candidate eligible; no attack strategy loaded, no deployment action",
                level=logging.INFO,
            )
            return

        if self._strategy_started_for_current_candidate:
            self._log_decision_once(
                (
                    "strategy_execution",
                    "already_started",
                    self._strategy.name,
                    str(self._current_search_number()),
                ),
                "Strategy execution already started for current candidate; not replaying %s",
                self._strategy.name,
                level=logging.INFO,
            )
            return

        if state.frame is None:
            self._log_decision_once(
                ("idle", BaseScreen.BATTLE_PREPARATION.value, "no_frame", "strategy"),
                "Automation idle: no frame available for strategy planning",
            )
            return

        plan = self._build_strategy_plan(state.frame, self._strategy)
        if plan is None:
            return

        self._log_strategy_plan(plan)
        if not plan.steps:
            self._log_decision_once(
                (
                    "strategy_plan",
                    plan.strategy_name,
                    "empty",
                    str(self._current_search_number()),
                ),
                "Strategy plan %s has no tap steps; no deployment action",
                plan.strategy_name,
                level=logging.INFO,
            )
            return

        self._execute_strategy_plan(state, snapshot_signature, plan)

    def _handle_battle_in_progress(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
    ) -> None:
        if not self._strategy_started_for_current_candidate:
            self._log_decision_once(
                ("idle", BaseScreen.BATTLE_IN_PROGRESS.value, "strategy_not_started"),
                "Automation idle: battle in progress before strategy execution start",
            )
            return
        if self._config is None:
            self._log_decision_once(
                ("idle", BaseScreen.BATTLE_IN_PROGRESS.value, "no_config", "battle_loot"),
                "Automation idle: no Botto config available for battle loot tracking",
            )
            return
        if state.frame is None:
            self._log_decision_once(
                ("idle", BaseScreen.BATTLE_IN_PROGRESS.value, "no_frame", "battle_loot"),
                "Automation idle: no frame available for battle loot tracking",
            )
            return

        available_loot = self._read_active_battle_loot(state.frame)
        progress = self._battle_loot_tracker.update(
            available_loot,
            now=state.now,
            resource_stall_seconds=self._config.attack.battle.resource_stall_seconds,
        )
        if available_loot is None:
            self._log_battle_loot_unreadable(progress)
        else:
            self._log_battle_loot_progress(progress)

        if progress.stalled:
            self._request_battle_surrender(state, analysis, snapshot_signature)

    def _request_battle_surrender(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
    ) -> None:
        if self._surrender_requested_for_current_candidate:
            return

        surrender_evidence = _find_evidence(
            analysis,
            subject=BaseScreen.BATTLE_IN_PROGRESS,
            anchor=ScreenElement.BATTLE_SURRENDER_BUTTON,
        )
        if surrender_evidence is not None:
            if self._tap_evidence_anchor(
                state,
                analysis,
                snapshot_signature,
                subject=BaseScreen.BATTLE_IN_PROGRESS,
                anchor=ScreenElement.BATTLE_SURRENDER_BUTTON,
                signature=("screen", BaseScreen.BATTLE_IN_PROGRESS.value, "surrender"),
                label="battle.surrender",
                reason="resource progress stalled; request battle surrender",
            ):
                self._surrender_requested_for_current_candidate = True
            return

        if self._tap_evidence_anchor(
            state,
            analysis,
            snapshot_signature,
            subject=BaseScreen.BATTLE_IN_PROGRESS,
            anchor=ScreenElement.BATTLE_END_BATTLE_BUTTON,
            signature=("screen", BaseScreen.BATTLE_IN_PROGRESS.value, "end_battle"),
            label="battle.end_battle",
            reason="resource progress stalled; request battle end",
        ):
            self._surrender_requested_for_current_candidate = True

    def _handle_battle_surrender_confirmation(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
    ) -> None:
        if not self._surrender_requested_for_current_candidate:
            self._log_decision_once(
                ("idle", BaseScreen.BATTLE_SURRENDER_CONFIRMATION.value, "not_requested"),
                "Automation idle: surrender confirmation detected before Botto requested surrender",
            )
            return
        if self._surrender_confirmed_for_current_candidate:
            return

        if self._tap_evidence_anchor(
            state,
            analysis,
            snapshot_signature,
            subject=BaseScreen.BATTLE_SURRENDER_CONFIRMATION,
            anchor=ScreenElement.BATTLE_SURRENDER_OKAY_BUTTON,
            signature=("screen", BaseScreen.BATTLE_SURRENDER_CONFIRMATION.value, "okay"),
            label="battle.surrender.okay",
            reason="confirm requested battle surrender",
        ):
            self._surrender_confirmed_for_current_candidate = True

    def _handle_battle_result(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
    ) -> None:
        if (
            _find_evidence(
                analysis,
                subject=BaseScreen.BATTLE_RESULT,
                anchor=ScreenElement.BATTLE_CLAIM_REWARD_BUTTON,
            )
            is not None
        ):
            self._tap_battle_cleanup_anchor(
                state,
                analysis,
                snapshot_signature,
                subject=BaseScreen.BATTLE_RESULT,
                anchor=ScreenElement.BATTLE_CLAIM_REWARD_BUTTON,
                signature=("screen", BaseScreen.BATTLE_RESULT.value, "claim_reward"),
                label="battle_result.claim_reward",
                reason="claim available post-battle reward",
            )
            return

        self._tap_battle_cleanup_anchor(
            state,
            analysis,
            snapshot_signature,
            subject=BaseScreen.BATTLE_RESULT,
            anchor=ScreenElement.BATTLE_RETURN_HOME_BUTTON,
            signature=("screen", BaseScreen.BATTLE_RESULT.value, "return_home"),
            label="battle_result.return_home",
            reason="return home after battle result",
        )

    def _handle_reward_chest(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
    ) -> None:
        if (
            _find_evidence(
                analysis,
                subject=BaseScreen.REWARD_CHEST,
                anchor=ScreenElement.REWARD_CHEST_OPEN_CHEST,
            )
            is not None
        ):
            self._tap_battle_cleanup_anchor(
                state,
                analysis,
                snapshot_signature,
                subject=BaseScreen.REWARD_CHEST,
                anchor=ScreenElement.REWARD_CHEST_OPEN_CHEST,
                signature=("screen", BaseScreen.REWARD_CHEST.value, "open_chest"),
                label="reward_chest.open_chest",
                reason="open post-battle reward chest",
            )
            return

        self._tap_battle_cleanup_anchor(
            state,
            analysis,
            snapshot_signature,
            subject=BaseScreen.REWARD_CHEST,
            anchor=ScreenElement.REWARD_CHEST_CONTINUE_BUTTON,
            signature=("screen", BaseScreen.REWARD_CHEST.value, "continue"),
            label="reward_chest.continue",
            reason="continue after opening post-battle reward chest",
        )

    def _handle_star_bonus(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
    ) -> None:
        self._tap_battle_cleanup_anchor(
            state,
            analysis,
            snapshot_signature,
            subject=BaseScreen.STAR_BONUS,
            anchor=ScreenElement.STAR_BONUS_OKAY_BUTTON,
            signature=("screen", BaseScreen.STAR_BONUS.value, "okay"),
            label="star_bonus.okay",
            reason="acknowledge star bonus received",
        )

    def _build_strategy_plan(
        self,
        frame: FrameImage,
        strategy: AttackStrategy,
    ) -> StrategyExecutionPlan | None:
        try:
            deployable_slots = tuple(self._deployable_slot_detector(frame))
            battle_targets = tuple(self._air_defense_target_detector(frame))
            return self._strategy_planner(
                strategy,
                deployable_slots=deployable_slots,
                battle_targets=battle_targets,
            )
        except Exception as exc:
            _LOGGER.warning("Strategy planning failed; no deployment action: %s", exc)
            return None

    def _log_strategy_plan(self, plan: StrategyExecutionPlan) -> None:
        _LOGGER.info(
            "Strategy plan %s prepared: %d tap step(s), %d skip(s)",
            plan.strategy_name,
            len(plan.steps),
            len(plan.skips),
        )
        for skip in plan.skips:
            _LOGGER.info("Strategy plan skip %s: %s", skip.label, skip.reason)

    def _execute_strategy_plan(
        self,
        state: RuntimeLoopState,
        snapshot_signature: _SnapshotSignature,
        plan: StrategyExecutionPlan,
    ) -> None:
        self._battle_loot_tracker.reset()
        self._reset_battle_cleanup_guards()
        for step_index, step in enumerate(plan.steps, start=1):
            tapped = self._tap(
                state,
                step.point,
                snapshot_signature,
                signature=("strategy", plan.strategy_name, str(step_index), step.label),
                label=step.label,
                reason=step.reason,
            )
            if not tapped:
                _LOGGER.info(
                    "Strategy execution stopped after failed tap %s (%d/%d)",
                    step.label,
                    step_index,
                    len(plan.steps),
                )
                return
            self._strategy_started_for_current_candidate = True

    def _reset_strategy_execution_guard(self) -> None:
        self._strategy_started_for_current_candidate = False
        self._battle_loot_tracker.reset()
        self._reset_battle_cleanup_guards()

    def _reset_battle_cleanup_guards(self) -> None:
        self._surrender_requested_for_current_candidate = False
        self._surrender_confirmed_for_current_candidate = False
        self._completed_battle_cleanup_actions.clear()

    def _read_metadata(self, frame: FrameImage) -> OpponentBaseMetadata | None:
        try:
            return self._metadata_reader(frame)
        except Exception as exc:
            _LOGGER.warning("Battle search metadata read failed: %s", exc)
            return None

    def _read_active_battle_loot(self, frame: FrameImage) -> AvailableLoot | None:
        try:
            return self._battle_loot_reader(frame)
        except Exception as exc:
            _LOGGER.warning("Active battle loot read failed; stall tracker unchanged: %s", exc)
            return None

    def _log_battle_loot_unreadable(self, progress: BattleLootProgress) -> None:
        self._log_decision_once(
            (
                "battle_loot",
                "unreadable",
                str(self._current_search_number()),
                str(progress.total_remaining),
                str(progress.stalled),
            ),
            "Active battle loot unreadable; stall tracker unchanged",
        )

    def _log_battle_loot_progress(self, progress: BattleLootProgress) -> None:
        self._log_decision_once(
            (
                "battle_loot",
                str(self._current_search_number()),
                str(progress.total_remaining),
                str(progress.total_gained),
                str(progress.last_progress_at),
                str(progress.stalled),
            ),
            "Active battle loot tracker: remaining=%s gained=%s stalled=%s",
            progress.total_remaining,
            progress.total_gained,
            progress.stalled,
            level=logging.INFO,
        )

    def _current_search_number(self) -> int:
        return self._successful_next_taps + 1

    def _search_budget_remains(self) -> bool:
        if self._config is None:
            return False
        return self._current_search_number() < self._config.attack.search.max_searches

    def _reset_search_session(self) -> None:
        self._successful_next_taps = 0
        self._reset_strategy_execution_guard()

    def _tap_evidence_anchor(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
        *,
        subject: BaseScreen,
        anchor: HomeElement | ScreenElement,
        signature: _ActionSignature,
        label: str,
        reason: str,
    ) -> bool:
        evidence = _find_evidence(analysis, subject=subject, anchor=anchor)
        point = _tap_point_from_evidence(evidence, state.frame)
        if point is None:
            self._log_decision_once(
                ("idle", subject.value, anchor.value, "no_bounds"),
                "Automation idle: screen=%s anchor=%s has no evidence bounds",
                subject.value,
                anchor.value,
            )
            return False
        return self._tap(
            state,
            point,
            snapshot_signature,
            signature=signature,
            label=label,
            reason=reason,
        )

    def _tap_battle_cleanup_anchor(
        self,
        state: RuntimeLoopState,
        analysis: ScreenAnalysis,
        snapshot_signature: _SnapshotSignature,
        *,
        subject: BaseScreen,
        anchor: ScreenElement,
        signature: _ActionSignature,
        label: str,
        reason: str,
    ) -> bool:
        if signature in self._completed_battle_cleanup_actions:
            self._log_decision_once(
                ("battle_cleanup", *signature, "already_tapped"),
                "Automation idle: post-battle cleanup action %s already tapped",
                label,
            )
            return False

        tapped = self._tap_evidence_anchor(
            state,
            analysis,
            snapshot_signature,
            subject=subject,
            anchor=anchor,
            signature=signature,
            label=label,
            reason=reason,
        )
        if tapped:
            self._completed_battle_cleanup_actions.add(signature)
        return tapped

    def _tap(
        self,
        state: RuntimeLoopState,
        point: NormalizedPoint,
        snapshot_signature: _SnapshotSignature,
        *,
        signature: _ActionSignature,
        label: str,
        reason: str,
    ) -> bool:
        executor = state.action_executor
        if executor is None:
            self._log_decision_once(
                ("idle", *signature, "no_executor"),
                "Automation idle: no action executor for %s",
                label,
            )
            return False
        if state.frame is None:
            self._log_decision_once(
                ("idle", *signature, "no_frame"),
                "Automation idle: no frame available for %s",
                label,
            )
            return False
        if self._is_stale_snapshot_retry(signature, snapshot_signature):
            _LOGGER.debug("Automation skipping stale analysis retry for %s: %s", label, reason)
            return False
        if self._is_debounced(signature, state.now):
            _LOGGER.debug("Automation waiting before retrying %s: %s", label, reason)
            return False

        try:
            executor.tap(point, label=label, reason=reason)
        except RuntimeError as exc:
            _LOGGER.warning("Automation action failed for %s: %s", label, exc)
            return False

        self._last_action_signature = signature
        self._last_action_snapshot_signature = snapshot_signature
        self._last_action_at = state.now
        self._last_logged_decision_signature = None
        _LOGGER.info("Automation tapped %s: %s", label, reason)
        return True

    def _is_debounced(self, signature: _ActionSignature, now: float) -> bool:
        if self._last_action_signature != signature or self._last_action_at is None:
            return False
        return now - self._last_action_at < _ACTION_RETRY_COOLDOWN_SECONDS

    def _is_stale_snapshot_retry(
        self,
        signature: _ActionSignature,
        snapshot_signature: _SnapshotSignature,
    ) -> bool:
        return (
            self._last_action_signature == signature
            and self._last_action_snapshot_signature == snapshot_signature
        )

    def _log_decision_once(
        self,
        signature: _DecisionSignature,
        message: str,
        *args: object,
        level: int = logging.DEBUG,
    ) -> None:
        if self._last_logged_decision_signature == signature:
            return
        self._last_logged_decision_signature = signature
        _LOGGER.log(level, message, *args)


def _find_evidence(
    analysis: ScreenAnalysis,
    *,
    subject: BaseScreen | Overlay,
    anchor: HomeElement | PopupButton | ScreenElement,
) -> Evidence | None:
    for evidence in analysis.evidence:
        if evidence.subject == subject and evidence.anchor == anchor:
            return evidence
    return None


def _tap_point_from_matching_evidence(
    analysis: ScreenAnalysis,
    *,
    subject: BaseScreen | Overlay,
    anchor: HomeElement | PopupButton | ScreenElement,
    frame: FrameImage | None,
) -> NormalizedPoint | None:
    for evidence in analysis.evidence:
        if evidence.subject == subject and evidence.anchor == anchor:
            point = _tap_point_from_evidence(evidence, frame)
            if point is not None:
                return point
    return None


def _resolve_metadata_reader(
    metadata_reader: _OpponentMetadataReader | None,
    text_reader: BattleSearchTextReader | None,
) -> _OpponentMetadataReader:
    if metadata_reader is not None:
        if text_reader is not None:
            raise ValueError("metadata_reader and text_reader cannot both be provided")
        return metadata_reader
    if text_reader is None:
        return read_opponent_base_metadata

    def read_metadata(image: FrameImage) -> OpponentBaseMetadata | None:
        return read_opponent_base_metadata(image, read_text_fn=text_reader)

    return read_metadata


def _resolve_battle_loot_reader(
    battle_loot_reader: _BattleLootReader | None,
    text_reader: BattleSearchTextReader | None,
) -> _BattleLootReader:
    if battle_loot_reader is not None:
        return battle_loot_reader
    if text_reader is None:
        return read_active_battle_available_loot

    def read_battle_loot(image: FrameImage) -> AvailableLoot | None:
        return read_active_battle_available_loot(image, read_text_fn=text_reader)

    return read_battle_loot


def _ineligible_search_reason(eligibility: AttackEligibilityResult) -> str:
    failed_thresholds = ", ".join(
        f"{failure.resource}={failure.actual}<{failure.minimum}"
        for failure in eligibility.failed_thresholds
    )
    if not failed_thresholds:
        return "resources below configured thresholds; request next candidate"
    return f"resources below configured thresholds ({failed_thresholds}); request next candidate"


def _snapshot_signature(snapshot: RuntimeAnalysisSnapshot) -> _SnapshotSignature:
    return (snapshot.frame_id, snapshot.analyzed_at)


def _tap_point_from_evidence(
    evidence: Evidence | None,
    frame: FrameImage | None,
) -> NormalizedPoint | None:
    if evidence is None or frame is None:
        return None
    bounds = _rect_from_detail(evidence.details.get("bounds"))
    if bounds is None:
        return None
    return _normalized_center(bounds, frame.size)


def _rect_from_detail(value: object) -> Rect | None:
    if isinstance(value, Rect):
        return value
    if not isinstance(value, Mapping):
        return None
    try:
        return Rect(
            left=int(value["left"]),
            top=int(value["top"]),
            width=int(value["width"]),
            height=int(value["height"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _normalized_center(bounds: Rect, frame_size: Size) -> NormalizedPoint:
    center_x = bounds.left + bounds.width / 2.0
    center_y = bounds.top + bounds.height / 2.0
    return NormalizedPoint(
        x=_normalize_pixel_coordinate(center_x, frame_size.width),
        y=_normalize_pixel_coordinate(center_y, frame_size.height),
    )


def _normalize_pixel_coordinate(value: float, axis_size: int) -> float:
    if axis_size <= 1:
        return 0.0
    return min(max(value / (axis_size - 1), 0.0), 1.0)


__all__ = ["AutomationController"]
