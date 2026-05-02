"""Tests for Botto detection package public exports."""

from __future__ import annotations

import botto.detection as detection
from botto.detection.actions import ActionKind, RecommendedAction
from botto.detection.analysis import ScreenAnalysis
from botto.detection.deployment import (
    BattleTargetDetection,
    BattleTargetKind,
    DeployableKind,
    DeployableSlotDetection,
    TemplateMatchEvidence,
    detect_air_defense_targets,
    detect_deployable_slots,
)
from botto.detection.detector import analyze_screen
from botto.detection.evidence import Evidence, EvidenceKind
from botto.detection.overlays import detect_overlay
from botto.detection.overlays.detect import detect_overlay as detect_overlay_implementation
from botto.detection.overlays.models import Overlay, PopupButton
from botto.detection.screens import detect_base_screen
from botto.detection.screens.detect import detect_base_screen as detect_base_screen_implementation
from botto.detection.screens.models import BaseScreen, HomeElement, ScreenElement


def test_common_detection_model_exports_remain_ergonomic() -> None:
    expected_exports = {
        "ActionKind": ActionKind,
        "BaseScreen": BaseScreen,
        "BattleTargetDetection": BattleTargetDetection,
        "BattleTargetKind": BattleTargetKind,
        "DeployableKind": DeployableKind,
        "DeployableSlotDetection": DeployableSlotDetection,
        "Evidence": Evidence,
        "EvidenceKind": EvidenceKind,
        "HomeElement": HomeElement,
        "Overlay": Overlay,
        "PopupButton": PopupButton,
        "RecommendedAction": RecommendedAction,
        "ScreenAnalysis": ScreenAnalysis,
        "ScreenElement": ScreenElement,
        "TemplateMatchEvidence": TemplateMatchEvidence,
        "analyze_screen": analyze_screen,
        "detect_air_defense_targets": detect_air_defense_targets,
        "detect_deployable_slots": detect_deployable_slots,
    }

    assert expected_exports.keys() <= set(detection.__all__)
    for name, exported_object in expected_exports.items():
        assert getattr(detection, name) is exported_object


def test_detection_orchestration_package_exports_remain_available() -> None:
    assert detect_base_screen is detect_base_screen_implementation
    assert detect_overlay is detect_overlay_implementation
