"""Tests for the conservative runtime automation controller."""

from __future__ import annotations

from collections.abc import Iterable

from android_game_automator.image import FrameImage
from android_game_automator.types import NormalizedPoint, Point, Rect, SessionInfo, Size
from botto.automation.actions import ActionExecutor
from botto.automation.config import (
    AttackBattleConfig,
    AttackConfig,
    AttackResourcesConfig,
    AttackSearchConfig,
    BottoConfig,
)
from botto.automation.controller import AutomationController
from botto.automation.planner import PlannedSkip, PlannedTapStep, StrategyExecutionPlan
from botto.automation.search import AvailableLoot, OpponentBaseMetadata
from botto.automation.strategy import AttackStrategy
from botto.detection import (
    ActionKind,
    BaseScreen,
    Evidence,
    EvidenceKind,
    HomeElement,
    Overlay,
    PopupButton,
    RecommendedAction,
    ScreenAnalysis,
    ScreenElement,
)
from botto.runtime import RuntimeAnalysisSnapshot, RuntimeLoopState

from tests.botto.fakes import make_device_info, make_frame


def test_controller_does_not_tap_overlay_target_without_button_evidence() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.CONNECTION_LOST,
        confidence=0.9,
        recommended_action=RecommendedAction(
            kind=ActionKind.TAP,
            target=PopupButton.TRY_AGAIN,
            reason=Overlay.CONNECTION_LOST,
            tap_target=NormalizedPoint(x=0.25, y=0.30),
        ),
    )

    assert controller(_state(analysis, backend=backend)) is True

    assert backend.taps == []


def test_controller_taps_overlay_recommended_action_from_button_evidence_bounds() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.CONNECTION_LOST,
        confidence=0.9,
        evidence=(
            _template_evidence(
                subject=Overlay.CONNECTION_LOST,
                anchor=PopupButton.TRY_AGAIN,
                bounds=Rect(left=80, top=50, width=40, height=20),
            ),
        ),
        recommended_action=RecommendedAction(
            kind=ActionKind.TAP,
            target=PopupButton.TRY_AGAIN,
            reason=Overlay.CONNECTION_LOST,
            tap_target=NormalizedPoint(x=0.25, y=0.30),
        ),
    )

    assert controller(_state(analysis, backend=backend)) is True

    assert backend.taps == [(Point(x=100, y=60), 0.05)]


def test_controller_uses_later_overlay_button_evidence_when_first_lacks_bounds() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.CONNECTION_LOST,
        confidence=0.9,
        evidence=(
            Evidence(
                kind=EvidenceKind.OCR,
                subject=Overlay.CONNECTION_LOST,
                anchor=PopupButton.TRY_AGAIN,
                confidence=0.9,
                text="Try Again",
            ),
            _template_evidence(
                subject=Overlay.CONNECTION_LOST,
                anchor=PopupButton.TRY_AGAIN,
                bounds=Rect(left=120, top=40, width=20, height=20),
            ),
        ),
        recommended_action=RecommendedAction(
            kind=ActionKind.TAP,
            target=PopupButton.TRY_AGAIN,
            reason=Overlay.CONNECTION_LOST,
            tap_target=NormalizedPoint(x=0.25, y=0.30),
        ),
    )

    assert controller(_state(analysis, backend=backend)) is True

    assert backend.taps == [(Point(x=130, y=50), 0.05)]


def test_controller_does_not_tap_ocr_only_overlay_without_target() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.UNKNOWN,
        overlay=Overlay.CONNECTION_LOST,
        confidence=0.9,
        recommended_action=RecommendedAction(
            kind=ActionKind.TAP,
            target=PopupButton.TRY_AGAIN,
            reason=Overlay.CONNECTION_LOST,
        ),
    )

    assert controller(_state(analysis, backend=backend)) is True

    assert backend.taps == []


def test_controller_uses_attached_snapshot_when_legacy_refresh_would_mismatch() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    attached_snapshot = RuntimeAnalysisSnapshot(
        analysis=ScreenAnalysis(
            base_screen=BaseScreen.UNKNOWN,
            overlay=Overlay.NONE,
            confidence=0.9,
        ),
        analyzed_at=0.0,
        frame_id="attached-frame",
    )
    refreshed_snapshot = RuntimeAnalysisSnapshot(
        analysis=ScreenAnalysis(
            base_screen=BaseScreen.HOME_VILLAGE,
            overlay=Overlay.NONE,
            confidence=0.9,
            evidence=(
                _template_evidence(
                    subject=BaseScreen.HOME_VILLAGE,
                    anchor=HomeElement.ATTACK_BUTTON,
                    bounds=Rect(left=20, top=70, width=40, height=20),
                ),
            ),
        ),
        analyzed_at=0.1,
        frame_id="refreshed-frame",
    )
    state = LegacyRefreshState(
        _state_from_snapshot(attached_snapshot, backend=backend, now=0.0),
        refreshed_snapshot,
    )

    assert controller(state) is True

    assert state.refresh_calls == 0
    assert backend.taps == []


def test_controller_taps_home_attack_from_evidence_bounds() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.HOME_VILLAGE,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=(
            _template_evidence(
                subject=BaseScreen.HOME_VILLAGE,
                anchor=HomeElement.ATTACK_BUTTON,
                bounds=Rect(left=20, top=70, width=40, height=20),
            ),
        ),
    )

    assert controller(_state(analysis, backend=backend)) is True

    assert backend.taps == [(Point(x=40, y=80), 0.05)]


def test_controller_takes_no_home_attack_action_without_evidence_bounds() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.HOME_VILLAGE,
        overlay=Overlay.NONE,
        confidence=0.9,
    )

    assert controller(_state(analysis, backend=backend)) is True

    assert backend.taps == []


def test_controller_taps_attack_menu_find_a_match() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.ATTACK_MENU,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=(
            _template_evidence(
                subject=BaseScreen.ATTACK_MENU,
                anchor=ScreenElement.ATTACK_MENU_FIND_A_MATCH_BUTTON,
                bounds=Rect(left=10, top=62, width=30, height=20),
            ),
        ),
    )

    assert controller(_state(analysis, backend=backend)) is True

    assert backend.taps == [(Point(x=25, y=72), 0.05)]


def test_controller_taps_my_army_attack() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.MY_ARMY,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=(
            _template_evidence(
                subject=BaseScreen.MY_ARMY,
                anchor=ScreenElement.MY_ARMY_ATTACK_BUTTON,
                bounds=Rect(left=150, top=80, width=20, height=10),
            ),
        ),
    )

    assert controller(_state(analysis, backend=backend)) is True

    assert backend.taps == [(Point(x=160, y=85), 0.05)]


def test_controller_takes_no_deployment_action_when_no_strategy_is_loaded() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    deployable_detector = RaisingDetector()
    controller = AutomationController(
        _config(max_searches=5),
        metadata_reader=_metadata_reader(gold=500000, elixir=500000, dark_elixir=5000),
        deployable_slot_detector=deployable_detector,
        air_defense_target_detector=RaisingDetector(),
        strategy_planner=RaisingStrategyPlanner(),
    )

    assert controller(_state(_battle_preparation_analysis(), backend=backend)) is True

    assert backend.taps == []
    assert deployable_detector.calls == 0


def test_controller_executes_strategy_plan_for_eligible_battle_search_in_order() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    strategy = AttackStrategy(name="mass-super-minion", actions=())
    deployable_detector = FakeDetector(result=("slot",))
    air_defense_detector = FakeDetector(result=("target",))
    planner = FakeStrategyPlanner(
        _strategy_plan(
            PlannedTapStep(
                point=NormalizedPoint(x=0.10, y=0.20),
                label="spell.lightning.select",
                reason="select lightning",
            ),
            PlannedTapStep(
                point=NormalizedPoint(x=0.40, y=0.50),
                label="spell.lightning.air_defense.cast_1",
                reason="cast lightning",
            ),
        )
    )
    controller = AutomationController(
        _config(max_searches=5),
        strategy=strategy,
        metadata_reader=_metadata_reader(gold=500000, elixir=500000, dark_elixir=5000),
        deployable_slot_detector=deployable_detector,
        air_defense_target_detector=air_defense_detector,
        strategy_planner=planner,
    )
    state = _state(_battle_preparation_analysis(), backend=backend)

    assert controller(state) is True

    assert backend.taps == [
        (Point(x=20, y=20), 0.05),
        (Point(x=80, y=50), 0.05),
    ]
    assert deployable_detector.frames == [state.frame]
    assert air_defense_detector.frames == [state.frame]
    assert planner.calls == [(strategy, ("slot",), ("target",))]


def test_controller_takes_no_action_for_empty_strategy_plan() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    strategy = AttackStrategy(name="mass-super-minion", actions=())
    planner = FakeStrategyPlanner(
        StrategyExecutionPlan(
            strategy_name=strategy.name,
            steps=(),
            skips=(
                PlannedSkip(
                    label="unit.super_minion.slot",
                    reason="missing detected super_minion slot",
                ),
            ),
        )
    )
    controller = AutomationController(
        _config(max_searches=5),
        strategy=strategy,
        metadata_reader=_metadata_reader(gold=500000, elixir=500000, dark_elixir=5000),
        deployable_slot_detector=FakeDetector(result=()),
        air_defense_target_detector=FakeDetector(result=()),
        strategy_planner=planner,
    )

    assert controller(_state(_battle_preparation_analysis(), backend=backend)) is True

    assert backend.taps == []
    assert len(planner.calls) == 1


def test_controller_does_not_replay_strategy_for_same_candidate() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    strategy = AttackStrategy(name="mass-super-minion", actions=())
    planner = FakeStrategyPlanner(
        _strategy_plan(
            PlannedTapStep(
                point=NormalizedPoint(x=0.10, y=0.20),
                label="unit.super_minion.select",
                reason="select super minions",
            )
        )
    )
    controller = AutomationController(
        _config(max_searches=5),
        strategy=strategy,
        metadata_reader=_metadata_reader(gold=500000, elixir=500000, dark_elixir=5000),
        deployable_slot_detector=FakeDetector(result=()),
        air_defense_target_detector=FakeDetector(result=()),
        strategy_planner=planner,
    )
    first_snapshot = RuntimeAnalysisSnapshot(
        analysis=_battle_preparation_analysis(),
        analyzed_at=0.0,
        frame_id="candidate-1-frame-1",
    )
    later_snapshot = RuntimeAnalysisSnapshot(
        analysis=_battle_preparation_analysis(),
        analyzed_at=2.0,
        frame_id="candidate-1-frame-2",
    )

    assert controller(_state_from_snapshot(first_snapshot, backend=backend, now=0.0)) is True
    assert controller(_state_from_snapshot(later_snapshot, backend=backend, now=2.0)) is True

    assert backend.taps == [(Point(x=20, y=20), 0.05)]
    assert len(planner.calls) == 1


def test_controller_blocks_next_after_started_strategy_with_ineligible_metadata() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    strategy = AttackStrategy(name="mass-super-minion", actions=())
    metadata_reader = FakeSequentialMetadataReader(
        _metadata(gold=500000, elixir=500000, dark_elixir=5000),
        _metadata(gold=499999, elixir=500000, dark_elixir=5000),
    )
    planner = FakeStrategyPlanner(
        _strategy_plan(
            PlannedTapStep(
                point=NormalizedPoint(x=0.10, y=0.20),
                label="unit.super_minion.select",
                reason="select super minions",
            )
        )
    )
    controller = AutomationController(
        _config(max_searches=5),
        strategy=strategy,
        metadata_reader=metadata_reader,
        deployable_slot_detector=FakeDetector(result=()),
        air_defense_target_detector=FakeDetector(result=()),
        strategy_planner=planner,
    )
    first_snapshot = RuntimeAnalysisSnapshot(
        analysis=_battle_preparation_analysis(),
        analyzed_at=0.0,
        frame_id="candidate-1-frame-1",
    )
    later_snapshot = RuntimeAnalysisSnapshot(
        analysis=_battle_preparation_analysis(),
        analyzed_at=2.0,
        frame_id="candidate-1-frame-2",
    )
    first_state = _state_from_snapshot(first_snapshot, backend=backend, now=0.0)
    later_state = _state_from_snapshot(later_snapshot, backend=backend, now=2.0)

    assert controller(first_state) is True
    assert controller(later_state) is True

    assert backend.taps == [(Point(x=20, y=20), 0.05)]
    assert metadata_reader.frames == [first_state.frame]
    assert len(planner.calls) == 1


def test_controller_does_not_replay_after_partial_strategy_failure() -> None:
    backend = FakeActionBackend(Size(width=200, height=100), fail_tap_calls={2})
    strategy = AttackStrategy(name="mass-super-minion", actions=())
    planner = FakeStrategyPlanner(
        _strategy_plan(
            PlannedTapStep(
                point=NormalizedPoint(x=0.10, y=0.20),
                label="unit.super_minion.select",
                reason="select super minions",
            ),
            PlannedTapStep(
                point=NormalizedPoint(x=0.20, y=0.30),
                label="unit.super_minion.perimeter.bottom.wave_1.point_1",
                reason="deploy super minion",
            ),
            PlannedTapStep(
                point=NormalizedPoint(x=0.30, y=0.40),
                label="unit.super_minion.perimeter.bottom.wave_1.point_2",
                reason="deploy another super minion",
            ),
        )
    )
    controller = AutomationController(
        _config(max_searches=5),
        strategy=strategy,
        metadata_reader=_metadata_reader(gold=500000, elixir=500000, dark_elixir=5000),
        deployable_slot_detector=FakeDetector(result=()),
        air_defense_target_detector=FakeDetector(result=()),
        strategy_planner=planner,
    )
    first_snapshot = RuntimeAnalysisSnapshot(
        analysis=_battle_preparation_analysis(),
        analyzed_at=0.0,
        frame_id="candidate-1-frame-1",
    )
    later_snapshot = RuntimeAnalysisSnapshot(
        analysis=_battle_preparation_analysis(),
        analyzed_at=2.0,
        frame_id="candidate-1-frame-2",
    )

    assert controller(_state_from_snapshot(first_snapshot, backend=backend, now=0.0)) is True
    assert controller(_state_from_snapshot(later_snapshot, backend=backend, now=2.0)) is True

    assert backend.tap_attempts == [
        (Point(x=20, y=20), 0.05),
        (Point(x=40, y=30), 0.05),
    ]
    assert backend.taps == [(Point(x=20, y=20), 0.05)]
    assert len(planner.calls) == 1


def test_controller_updates_battle_loot_read_only_after_strategy_start() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    strategy = AttackStrategy(name="mass-super-minion", actions=())
    planner = FakeStrategyPlanner(
        _strategy_plan(
            PlannedTapStep(
                point=NormalizedPoint(x=0.10, y=0.20),
                label="unit.super_minion.select",
                reason="select super minions",
            )
        )
    )
    battle_loot_reader = FakeBattleLootReader(
        AvailableLoot(gold=100_000, elixir=50_000, dark_elixir=1_000)
    )
    controller = AutomationController(
        _config(max_searches=5),
        strategy=strategy,
        metadata_reader=_metadata_reader(gold=500000, elixir=500000, dark_elixir=5000),
        battle_loot_reader=battle_loot_reader,
        deployable_slot_detector=FakeDetector(result=()),
        air_defense_target_detector=FakeDetector(result=()),
        strategy_planner=planner,
    )
    preparation_snapshot = RuntimeAnalysisSnapshot(
        analysis=_battle_preparation_analysis(),
        analyzed_at=0.0,
        frame_id="candidate-1-frame-1",
    )
    battle_snapshot = RuntimeAnalysisSnapshot(
        analysis=_battle_in_progress_analysis(),
        analyzed_at=2.0,
        frame_id="battle-1-frame-1",
    )
    preparation_state = _state_from_snapshot(preparation_snapshot, backend=backend, now=0.0)
    battle_state = _state_from_snapshot(battle_snapshot, backend=backend, now=2.0)

    assert controller(preparation_state) is True
    assert controller(battle_state) is True

    assert backend.taps == [(Point(x=20, y=20), 0.05)]
    assert battle_loot_reader.frames == [battle_state.frame]


def test_controller_does_not_surrender_before_strategy_start() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(
        _config(max_searches=5),
        battle_loot_reader=RaisingBattleLootReader(),
    )

    assert (
        controller(
            _state(
                _battle_in_progress_analysis(
                    surrender_bounds=Rect(left=10, top=70, width=20, height=10),
                ),
                backend=backend,
            )
        )
        is True
    )

    assert backend.taps == []


def test_controller_does_not_surrender_before_resource_stall_duration() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    battle_loot_reader = FakeBattleLootReader(_active_loot(), _active_loot())
    controller = _controller_with_one_tap_strategy(battle_loot_reader=battle_loot_reader)
    battle_analysis = _battle_in_progress_analysis(
        surrender_bounds=Rect(left=10, top=70, width=20, height=10),
    )

    _start_strategy(controller, backend)
    assert (
        controller(
            _state_from_snapshot(
                RuntimeAnalysisSnapshot(
                    analysis=battle_analysis,
                    analyzed_at=1.0,
                    frame_id="battle-1-frame-1",
                ),
                backend=backend,
                now=1.0,
            )
        )
        is True
    )
    assert (
        controller(
            _state_from_snapshot(
                RuntimeAnalysisSnapshot(
                    analysis=battle_analysis,
                    analyzed_at=20.9,
                    frame_id="battle-1-frame-2",
                ),
                backend=backend,
                now=20.9,
            )
        )
        is True
    )

    assert backend.taps == [(Point(x=20, y=20), 0.05)]


def test_controller_taps_surrender_from_evidence_after_resource_stall() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    battle_loot_reader = FakeBattleLootReader(_active_loot(), _active_loot())
    controller = _controller_with_one_tap_strategy(battle_loot_reader=battle_loot_reader)
    battle_analysis = _battle_in_progress_analysis(
        surrender_bounds=Rect(left=10, top=70, width=20, height=10),
    )

    _start_strategy(controller, backend)
    assert (
        controller(
            _state_from_snapshot(
                RuntimeAnalysisSnapshot(
                    analysis=battle_analysis,
                    analyzed_at=1.0,
                    frame_id="battle-1-frame-1",
                ),
                backend=backend,
                now=1.0,
            )
        )
        is True
    )
    assert (
        controller(
            _state_from_snapshot(
                RuntimeAnalysisSnapshot(
                    analysis=battle_analysis,
                    analyzed_at=21.0,
                    frame_id="battle-1-frame-2",
                ),
                backend=backend,
                now=21.0,
            )
        )
        is True
    )

    assert backend.taps == [
        (Point(x=20, y=20), 0.05),
        (Point(x=20, y=75), 0.05),
    ]


def test_controller_falls_back_to_end_battle_when_surrender_evidence_is_missing() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    battle_loot_reader = FakeBattleLootReader(_active_loot(), _active_loot())
    controller = _controller_with_one_tap_strategy(battle_loot_reader=battle_loot_reader)
    battle_analysis = _battle_in_progress_analysis(
        end_battle_bounds=Rect(left=4, top=70, width=20, height=10),
    )

    _start_strategy(controller, backend)
    assert (
        controller(
            _state_from_snapshot(
                RuntimeAnalysisSnapshot(
                    analysis=battle_analysis,
                    analyzed_at=1.0,
                    frame_id="battle-1-frame-1",
                ),
                backend=backend,
                now=1.0,
            )
        )
        is True
    )
    assert (
        controller(
            _state_from_snapshot(
                RuntimeAnalysisSnapshot(
                    analysis=battle_analysis,
                    analyzed_at=21.0,
                    frame_id="battle-1-frame-2",
                ),
                backend=backend,
                now=21.0,
            )
        )
        is True
    )

    assert backend.taps == [
        (Point(x=20, y=20), 0.05),
        (Point(x=14, y=75), 0.05),
    ]


def test_controller_does_not_spam_surrender_after_requesting_it_once() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    battle_loot_reader = FakeBattleLootReader(_active_loot(), _active_loot(), _active_loot())
    controller = _controller_with_one_tap_strategy(battle_loot_reader=battle_loot_reader)
    battle_analysis = _battle_in_progress_analysis(
        surrender_bounds=Rect(left=10, top=70, width=20, height=10),
    )

    _start_strategy(controller, backend)
    for now, frame_id in (
        (1.0, "battle-1-frame-1"),
        (21.0, "battle-1-frame-2"),
        (22.0, "battle-1-frame-3"),
    ):
        assert (
            controller(
                _state_from_snapshot(
                    RuntimeAnalysisSnapshot(
                        analysis=battle_analysis,
                        analyzed_at=now,
                        frame_id=frame_id,
                    ),
                    backend=backend,
                    now=now,
                )
            )
            is True
        )

    assert backend.taps == [
        (Point(x=20, y=20), 0.05),
        (Point(x=20, y=75), 0.05),
    ]


def test_controller_taps_surrender_confirmation_okay_only_after_request() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    battle_loot_reader = FakeBattleLootReader(_active_loot(), _active_loot())
    controller = _controller_with_one_tap_strategy(battle_loot_reader=battle_loot_reader)
    battle_analysis = _battle_in_progress_analysis(
        surrender_bounds=Rect(left=10, top=70, width=20, height=10),
    )
    confirmation_analysis = _surrender_confirmation_analysis(
        okay_bounds=Rect(left=80, top=60, width=40, height=20),
    )

    _start_strategy(controller, backend)
    for now, frame_id, analysis in (
        (1.0, "battle-1-frame-1", battle_analysis),
        (21.0, "battle-1-frame-2", battle_analysis),
        (22.0, "battle-1-frame-3", confirmation_analysis),
        (23.0, "battle-1-frame-4", confirmation_analysis),
    ):
        assert (
            controller(
                _state_from_snapshot(
                    RuntimeAnalysisSnapshot(
                        analysis=analysis,
                        analyzed_at=now,
                        frame_id=frame_id,
                    ),
                    backend=backend,
                    now=now,
                )
            )
            is True
        )

    assert backend.taps == [
        (Point(x=20, y=20), 0.05),
        (Point(x=20, y=75), 0.05),
        (Point(x=100, y=70), 0.05),
    ]


def test_controller_ignores_surrender_confirmation_before_requesting_surrender() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(_config(max_searches=5))

    assert (
        controller(
            _state(
                _surrender_confirmation_analysis(
                    okay_bounds=Rect(left=80, top=60, width=40, height=20),
                ),
                backend=backend,
            )
        )
        is True
    )

    assert backend.taps == []


def test_controller_claims_post_battle_reward_before_returning_home() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(_config(max_searches=5))

    assert (
        controller(
            _state(
                _battle_result_analysis(
                    return_home_bounds=Rect(left=20, top=70, width=30, height=10),
                    claim_reward_bounds=Rect(left=80, top=80, width=40, height=10),
                ),
                backend=backend,
            )
        )
        is True
    )

    assert backend.taps == [(Point(x=100, y=85), 0.05)]


def test_controller_returns_home_from_battle_result_without_claim_reward() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(_config(max_searches=5))

    assert (
        controller(
            _state(
                _battle_result_analysis(
                    return_home_bounds=Rect(left=80, top=80, width=40, height=10),
                    claim_reward_bounds=None,
                ),
                backend=backend,
            )
        )
        is True
    )

    assert backend.taps == [(Point(x=100, y=85), 0.05)]


def test_controller_opens_closed_reward_chest_before_continue() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(_config(max_searches=5))

    assert (
        controller(
            _state(
                _reward_chest_analysis(
                    open_chest_bounds=Rect(left=80, top=40, width=40, height=40),
                    continue_bounds=Rect(left=10, top=80, width=40, height=10),
                ),
                backend=backend,
            )
        )
        is True
    )

    assert backend.taps == [(Point(x=100, y=60), 0.05)]


def test_controller_continues_after_reward_chest_is_opened() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(_config(max_searches=5))

    assert (
        controller(
            _state(
                _reward_chest_analysis(
                    open_chest_bounds=None,
                    continue_bounds=Rect(left=80, top=80, width=40, height=10),
                ),
                backend=backend,
            )
        )
        is True
    )

    assert backend.taps == [(Point(x=100, y=85), 0.05)]


def test_controller_acknowledges_star_bonus() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(_config(max_searches=5))

    assert controller(_state(_star_bonus_analysis(), backend=backend)) is True

    assert backend.taps == [(Point(x=100, y=85), 0.05)]


def test_controller_takes_no_cleanup_action_without_evidence_bounds() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(_config(max_searches=5))
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.REWARD_CHEST,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=(
            Evidence(
                kind=EvidenceKind.TEMPLATE,
                subject=BaseScreen.REWARD_CHEST,
                anchor=ScreenElement.REWARD_CHEST_OPEN_CHEST,
                confidence=0.9,
            ),
        ),
    )

    assert controller(_state(analysis, backend=backend)) is True

    assert backend.taps == []


def test_controller_does_not_repeat_same_cleanup_action_but_allows_next_screen() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(_config(max_searches=5))
    battle_result = _battle_result_analysis(
        return_home_bounds=None,
        claim_reward_bounds=Rect(left=80, top=80, width=40, height=10),
    )
    reward_chest = _reward_chest_analysis(
        open_chest_bounds=Rect(left=80, top=40, width=40, height=40),
        continue_bounds=None,
    )

    for snapshot in (
        RuntimeAnalysisSnapshot(analysis=battle_result, analyzed_at=0.0, frame_id="result-1"),
        RuntimeAnalysisSnapshot(analysis=battle_result, analyzed_at=2.0, frame_id="result-2"),
        RuntimeAnalysisSnapshot(analysis=reward_chest, analyzed_at=3.0, frame_id="chest-1"),
    ):
        assert controller(_state_from_snapshot(snapshot, backend=backend, now=snapshot.analyzed_at))

    assert backend.taps == [
        (Point(x=100, y=85), 0.05),
        (Point(x=100, y=60), 0.05),
    ]


def test_controller_resets_cleanup_guards_after_home_for_next_attack_cycle() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(_config(max_searches=5))
    battle_result = _battle_result_analysis(
        return_home_bounds=Rect(left=80, top=80, width=40, height=10),
        claim_reward_bounds=None,
    )
    home = ScreenAnalysis(
        base_screen=BaseScreen.HOME_VILLAGE,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=(
            _template_evidence(
                subject=BaseScreen.HOME_VILLAGE,
                anchor=HomeElement.ATTACK_BUTTON,
                bounds=Rect(left=20, top=70, width=40, height=20),
            ),
        ),
    )

    for snapshot in (
        RuntimeAnalysisSnapshot(analysis=battle_result, analyzed_at=0.0, frame_id="result-1"),
        RuntimeAnalysisSnapshot(analysis=battle_result, analyzed_at=2.0, frame_id="result-2"),
        RuntimeAnalysisSnapshot(analysis=home, analyzed_at=3.0, frame_id="home-1"),
        RuntimeAnalysisSnapshot(analysis=battle_result, analyzed_at=4.0, frame_id="result-3"),
    ):
        assert controller(_state_from_snapshot(snapshot, backend=backend, now=snapshot.analyzed_at))

    assert backend.taps == [
        (Point(x=100, y=85), 0.05),
        (Point(x=40, y=80), 0.05),
        (Point(x=100, y=85), 0.05),
    ]


def test_controller_does_not_read_battle_loot_before_strategy_start() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(
        _config(max_searches=5),
        battle_loot_reader=RaisingBattleLootReader(),
    )

    assert controller(_state(_battle_in_progress_analysis(), backend=backend)) is True

    assert backend.taps == []


def test_controller_taps_next_from_evidence_for_ineligible_battle_search_under_budget() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(
        _config(max_searches=2),
        metadata_reader=_metadata_reader(gold=499999, elixir=500000, dark_elixir=5000),
    )

    assert controller(_state(_battle_preparation_analysis(), backend=backend)) is True

    assert backend.taps == [(Point(x=170, y=65), 0.05)]


def test_controller_taps_next_for_ineligible_battle_search_even_with_strategy() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    strategy = AttackStrategy(name="mass-super-minion", actions=())
    deployable_detector = RaisingDetector()
    controller = AutomationController(
        _config(max_searches=2),
        strategy=strategy,
        metadata_reader=_metadata_reader(gold=499999, elixir=500000, dark_elixir=5000),
        deployable_slot_detector=deployable_detector,
        air_defense_target_detector=RaisingDetector(),
        strategy_planner=RaisingStrategyPlanner(),
    )

    assert controller(_state(_battle_preparation_analysis(), backend=backend)) is True

    assert backend.taps == [(Point(x=170, y=65), 0.05)]
    assert deployable_detector.calls == 0


def test_controller_does_not_tap_next_for_ineligible_battle_search_at_budget() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(
        _config(max_searches=1),
        metadata_reader=_metadata_reader(gold=499999, elixir=500000, dark_elixir=5000),
    )

    assert controller(_state(_battle_preparation_analysis(), backend=backend)) is True

    assert backend.taps == []


def test_controller_does_not_tap_next_when_battle_search_metadata_is_unreadable() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(_config(max_searches=2), metadata_reader=lambda image: None)

    assert controller(_state(_battle_preparation_analysis(), backend=backend)) is True

    assert backend.taps == []


def test_controller_does_not_repeat_next_for_same_stale_battle_search_snapshot() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(
        _config(max_searches=3),
        metadata_reader=_metadata_reader(gold=499999, elixir=500000, dark_elixir=5000),
    )
    snapshot = RuntimeAnalysisSnapshot(
        analysis=_battle_preparation_analysis(),
        analyzed_at=0.0,
        frame_id="frame-1",
    )

    assert controller(_state_from_snapshot(snapshot, backend=backend, now=0.0)) is True
    assert controller(_state_from_snapshot(snapshot, backend=backend, now=1.1)) is True

    assert backend.taps == [(Point(x=170, y=65), 0.05)]


def test_controller_counts_successful_next_taps_toward_battle_search_budget() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController(
        _config(max_searches=2),
        metadata_reader=_metadata_reader(gold=499999, elixir=500000, dark_elixir=5000),
    )
    first_candidate = RuntimeAnalysisSnapshot(
        analysis=_battle_preparation_analysis(),
        analyzed_at=0.0,
        frame_id="frame-1",
    )
    second_candidate = RuntimeAnalysisSnapshot(
        analysis=_battle_preparation_analysis(),
        analyzed_at=1.1,
        frame_id="frame-2",
    )

    assert controller(_state_from_snapshot(first_candidate, backend=backend, now=0.0)) is True
    assert controller(_state_from_snapshot(second_candidate, backend=backend, now=1.1)) is True

    assert backend.taps == [(Point(x=170, y=65), 0.05)]


def test_controller_does_not_retry_same_action_from_stale_snapshot_after_cooldown() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.HOME_VILLAGE,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=(
            _template_evidence(
                subject=BaseScreen.HOME_VILLAGE,
                anchor=HomeElement.ATTACK_BUTTON,
                bounds=Rect(left=20, top=70, width=40, height=20),
            ),
        ),
    )
    snapshot = RuntimeAnalysisSnapshot(analysis=analysis, analyzed_at=0.0, frame_id="frame-1")

    assert controller(_state_from_snapshot(snapshot, backend=backend, now=0.0)) is True
    assert controller(_state_from_snapshot(snapshot, backend=backend, now=0.1)) is True
    assert controller(_state_from_snapshot(snapshot, backend=backend, now=1.1)) is True

    assert backend.taps == [(Point(x=40, y=80), 0.05)]


def test_controller_allows_retry_after_cooldown_with_fresh_snapshot() -> None:
    backend = FakeActionBackend(Size(width=200, height=100))
    controller = AutomationController()
    analysis = ScreenAnalysis(
        base_screen=BaseScreen.HOME_VILLAGE,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=(
            _template_evidence(
                subject=BaseScreen.HOME_VILLAGE,
                anchor=HomeElement.ATTACK_BUTTON,
                bounds=Rect(left=20, top=70, width=40, height=20),
            ),
        ),
    )
    stale_snapshot = RuntimeAnalysisSnapshot(analysis=analysis, analyzed_at=0.0, frame_id="frame-1")
    fresh_snapshot = RuntimeAnalysisSnapshot(analysis=analysis, analyzed_at=1.1, frame_id="frame-2")

    assert controller(_state_from_snapshot(stale_snapshot, backend=backend, now=0.0)) is True
    assert controller(_state_from_snapshot(fresh_snapshot, backend=backend, now=1.1)) is True

    assert backend.taps == [
        (Point(x=40, y=80), 0.05),
        (Point(x=40, y=80), 0.05),
    ]


def test_controller_exposes_loaded_strategy_for_future_automation_steps() -> None:
    strategy = AttackStrategy(name="mass-super-minion", actions=())
    controller = AutomationController(_config(max_searches=2), strategy=strategy)

    assert controller.strategy is strategy


def _template_evidence(
    *,
    subject: BaseScreen | Overlay,
    anchor: HomeElement | PopupButton | ScreenElement,
    bounds: Rect,
) -> Evidence:
    return Evidence(
        kind=EvidenceKind.TEMPLATE,
        subject=subject,
        anchor=anchor,
        confidence=0.9,
        details={"bounds": bounds},
    )


def _battle_preparation_analysis() -> ScreenAnalysis:
    return ScreenAnalysis(
        base_screen=BaseScreen.BATTLE_PREPARATION,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=(
            _template_evidence(
                subject=BaseScreen.BATTLE_PREPARATION,
                anchor=ScreenElement.BATTLE_NEXT_BUTTON,
                bounds=Rect(left=160, top=55, width=20, height=20),
            ),
        ),
    )


def _battle_in_progress_analysis(
    *,
    surrender_bounds: Rect | None = None,
    end_battle_bounds: Rect | None = None,
) -> ScreenAnalysis:
    evidence: list[Evidence] = []
    if end_battle_bounds is not None:
        evidence.append(
            _template_evidence(
                subject=BaseScreen.BATTLE_IN_PROGRESS,
                anchor=ScreenElement.BATTLE_END_BATTLE_BUTTON,
                bounds=end_battle_bounds,
            )
        )
    if surrender_bounds is not None:
        evidence.append(
            _template_evidence(
                subject=BaseScreen.BATTLE_IN_PROGRESS,
                anchor=ScreenElement.BATTLE_SURRENDER_BUTTON,
                bounds=surrender_bounds,
            )
        )
    return ScreenAnalysis(
        base_screen=BaseScreen.BATTLE_IN_PROGRESS,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=tuple(evidence),
    )


def _surrender_confirmation_analysis(*, okay_bounds: Rect) -> ScreenAnalysis:
    return ScreenAnalysis(
        base_screen=BaseScreen.BATTLE_SURRENDER_CONFIRMATION,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=(
            _template_evidence(
                subject=BaseScreen.BATTLE_SURRENDER_CONFIRMATION,
                anchor=ScreenElement.BATTLE_SURRENDER_OKAY_BUTTON,
                bounds=okay_bounds,
            ),
        ),
    )


def _battle_result_analysis(
    *,
    return_home_bounds: Rect | None,
    claim_reward_bounds: Rect | None,
) -> ScreenAnalysis:
    evidence: list[Evidence] = []
    if return_home_bounds is not None:
        evidence.append(
            _template_evidence(
                subject=BaseScreen.BATTLE_RESULT,
                anchor=ScreenElement.BATTLE_RETURN_HOME_BUTTON,
                bounds=return_home_bounds,
            )
        )
    if claim_reward_bounds is not None:
        evidence.append(
            _template_evidence(
                subject=BaseScreen.BATTLE_RESULT,
                anchor=ScreenElement.BATTLE_CLAIM_REWARD_BUTTON,
                bounds=claim_reward_bounds,
            )
        )
    return ScreenAnalysis(
        base_screen=BaseScreen.BATTLE_RESULT,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=tuple(evidence),
    )


def _reward_chest_analysis(
    *,
    open_chest_bounds: Rect | None,
    continue_bounds: Rect | None,
) -> ScreenAnalysis:
    evidence: list[Evidence] = []
    if open_chest_bounds is not None:
        evidence.append(
            _template_evidence(
                subject=BaseScreen.REWARD_CHEST,
                anchor=ScreenElement.REWARD_CHEST_OPEN_CHEST,
                bounds=open_chest_bounds,
            )
        )
    if continue_bounds is not None:
        evidence.append(
            _template_evidence(
                subject=BaseScreen.REWARD_CHEST,
                anchor=ScreenElement.REWARD_CHEST_CONTINUE_BUTTON,
                bounds=continue_bounds,
            )
        )
    return ScreenAnalysis(
        base_screen=BaseScreen.REWARD_CHEST,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=tuple(evidence),
    )


def _star_bonus_analysis() -> ScreenAnalysis:
    return ScreenAnalysis(
        base_screen=BaseScreen.STAR_BONUS,
        overlay=Overlay.NONE,
        confidence=0.9,
        evidence=(
            _template_evidence(
                subject=BaseScreen.STAR_BONUS,
                anchor=ScreenElement.STAR_BONUS_OKAY_BUTTON,
                bounds=Rect(left=80, top=80, width=40, height=10),
            ),
        ),
    )


def _metadata_reader(
    *,
    gold: int,
    elixir: int,
    dark_elixir: int,
) -> FakeMetadataReader:
    return FakeMetadataReader(_metadata(gold=gold, elixir=elixir, dark_elixir=dark_elixir))


def _metadata(
    *,
    gold: int,
    elixir: int,
    dark_elixir: int,
) -> OpponentBaseMetadata:
    return OpponentBaseMetadata(
        name=None,
        clan=None,
        available_loot=AvailableLoot(
            gold=gold,
            elixir=elixir,
            dark_elixir=dark_elixir,
        ),
    )


def _config(*, max_searches: int) -> BottoConfig:
    return BottoConfig(
        attack=AttackConfig(
            strategy="mass-super-minion",
            resources=AttackResourcesConfig(
                min_gold=500000,
                min_elixir=500000,
                min_dark_elixir=5000,
            ),
            search=AttackSearchConfig(max_searches=max_searches),
            battle=AttackBattleConfig(resource_stall_seconds=20),
        )
    )


def _active_loot() -> AvailableLoot:
    return AvailableLoot(gold=100_000, elixir=50_000, dark_elixir=1_000)


def _controller_with_one_tap_strategy(
    *,
    battle_loot_reader: FakeBattleLootReader,
) -> AutomationController:
    strategy = AttackStrategy(name="mass-super-minion", actions=())
    planner = FakeStrategyPlanner(
        _strategy_plan(
            PlannedTapStep(
                point=NormalizedPoint(x=0.10, y=0.20),
                label="unit.super_minion.select",
                reason="select super minions",
            )
        )
    )
    return AutomationController(
        _config(max_searches=5),
        strategy=strategy,
        metadata_reader=_metadata_reader(gold=500000, elixir=500000, dark_elixir=5000),
        battle_loot_reader=battle_loot_reader,
        deployable_slot_detector=FakeDetector(result=()),
        air_defense_target_detector=FakeDetector(result=()),
        strategy_planner=planner,
    )


def _start_strategy(controller: AutomationController, backend: FakeActionBackend) -> None:
    assert (
        controller(
            _state_from_snapshot(
                RuntimeAnalysisSnapshot(
                    analysis=_battle_preparation_analysis(),
                    analyzed_at=0.0,
                    frame_id="candidate-1-frame-1",
                ),
                backend=backend,
                now=0.0,
            )
        )
        is True
    )


def _state(
    analysis: ScreenAnalysis,
    *,
    backend: FakeActionBackend,
    now: float = 0.0,
) -> RuntimeLoopState:
    return _state_from_snapshot(
        RuntimeAnalysisSnapshot(analysis=analysis, analyzed_at=now),
        backend=backend,
        now=now,
    )


def _state_from_snapshot(
    snapshot: RuntimeAnalysisSnapshot,
    *,
    backend: FakeActionBackend,
    now: float,
) -> RuntimeLoopState:
    return RuntimeLoopState(
        frame=make_frame(width=200, height=100),
        analysis_snapshot=snapshot,
        now=now,
        analysis_running=False,
        session_info=make_session_info(),
        action_executor=ActionExecutor(backend),
    )


def make_session_info() -> SessionInfo:
    from datetime import UTC, datetime

    return SessionInfo(
        session_id="test-session",
        device=make_device_info("emulator-5554"),
        started_at=datetime.now(UTC),
    )


def _strategy_plan(*steps: PlannedTapStep) -> StrategyExecutionPlan:
    return StrategyExecutionPlan(strategy_name="mass-super-minion", steps=steps, skips=())


class LegacyRefreshState:
    def __init__(
        self,
        state: RuntimeLoopState,
        refreshed_snapshot: RuntimeAnalysisSnapshot,
    ) -> None:
        self.frame = state.frame
        self.analysis_snapshot = state.analysis_snapshot
        self.now = state.now
        self.analysis_running = state.analysis_running
        self.session_info = state.session_info
        self.action_executor = state.action_executor
        self._refreshed_snapshot = refreshed_snapshot
        self.refresh_calls = 0

    def refresh_analysis_snapshot(self) -> RuntimeAnalysisSnapshot:
        self.refresh_calls += 1
        return self._refreshed_snapshot


class FakeDetector:
    def __init__(self, *, result: Iterable[object]) -> None:
        self._result = tuple(result)
        self.frames: list[FrameImage] = []

    def __call__(self, image: FrameImage) -> tuple[object, ...]:
        self.frames.append(image)
        return self._result


class RaisingDetector:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, image: FrameImage) -> tuple[object, ...]:
        _ = image
        self.calls += 1
        raise AssertionError("deployment detectors must not run")


class FakeStrategyPlanner:
    def __init__(self, plan: StrategyExecutionPlan) -> None:
        self._plan = plan
        self.calls: list[tuple[AttackStrategy, tuple[object, ...], tuple[object, ...]]] = []

    def __call__(
        self,
        strategy: AttackStrategy,
        *,
        deployable_slots: Iterable[object],
        battle_targets: Iterable[object],
    ) -> StrategyExecutionPlan:
        self.calls.append((strategy, tuple(deployable_slots), tuple(battle_targets)))
        return self._plan


class RaisingStrategyPlanner:
    def __call__(
        self,
        strategy: AttackStrategy,
        *,
        deployable_slots: Iterable[object],
        battle_targets: Iterable[object],
    ) -> StrategyExecutionPlan:
        _ = strategy, deployable_slots, battle_targets
        raise AssertionError("strategy planner must not run")


class FakeActionBackend:
    def __init__(self, size: Size, *, fail_tap_calls: set[int] | None = None) -> None:
        self._size = size
        self._fail_tap_calls = fail_tap_calls if fail_tap_calls is not None else set()
        self.tap_attempts: list[tuple[Point, float]] = []
        self.taps: list[tuple[Point, float]] = []

    @property
    def action_surface_size(self) -> Size:
        return self._size

    def tap_pixels(self, point: Point, *, hold_seconds: float = 0.05) -> None:
        self.tap_attempts.append((point, hold_seconds))
        if len(self.tap_attempts) in self._fail_tap_calls:
            raise RuntimeError("configured tap failure")
        self.taps.append((point, hold_seconds))

    def swipe_pixels(
        self,
        start: Point,
        end: Point,
        *,
        duration_ms: int = 300,
        steps: int = 12,
    ) -> None:
        _ = start, end, duration_ms, steps


class FakeMetadataReader:
    def __init__(self, metadata: OpponentBaseMetadata | None) -> None:
        self._metadata = metadata
        self.frames: list[FrameImage] = []

    def __call__(self, image: FrameImage) -> OpponentBaseMetadata | None:
        self.frames.append(image)
        return self._metadata


class FakeSequentialMetadataReader:
    def __init__(self, *metadata: OpponentBaseMetadata | None) -> None:
        if not metadata:
            raise ValueError("metadata sequence cannot be empty")
        self._metadata = metadata
        self.frames: list[FrameImage] = []

    def __call__(self, image: FrameImage) -> OpponentBaseMetadata | None:
        self.frames.append(image)
        index = min(len(self.frames) - 1, len(self._metadata) - 1)
        return self._metadata[index]


class FakeBattleLootReader:
    def __init__(self, *available_loot: AvailableLoot | None) -> None:
        if not available_loot:
            raise ValueError("battle loot sequence cannot be empty")
        self._available_loot = available_loot
        self.frames: list[FrameImage] = []

    def __call__(self, image: FrameImage) -> AvailableLoot | None:
        self.frames.append(image)
        index = min(len(self.frames) - 1, len(self._available_loot) - 1)
        return self._available_loot[index]


class RaisingBattleLootReader:
    def __call__(self, image: FrameImage) -> AvailableLoot | None:
        _ = image
        raise AssertionError("battle loot reader must not run")
