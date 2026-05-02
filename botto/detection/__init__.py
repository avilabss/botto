"""Botto screen detection package."""

from .actions import ActionKind, RecommendedAction
from .analysis import ScreenAnalysis
from .deployment import (
    BattleTargetDetection,
    BattleTargetKind,
    DeployableKind,
    DeployableSlotDetection,
    TemplateMatchEvidence,
    detect_air_defense_targets,
    detect_deployable_slots,
)
from .detector import analyze_screen
from .evidence import Evidence, EvidenceKind
from .overlays.models import Overlay, PopupButton
from .screens.models import BaseScreen, HomeElement, ScreenElement

__all__ = [
    "ActionKind",
    "BaseScreen",
    "BattleTargetDetection",
    "BattleTargetKind",
    "DeployableKind",
    "DeployableSlotDetection",
    "Evidence",
    "EvidenceKind",
    "HomeElement",
    "Overlay",
    "PopupButton",
    "RecommendedAction",
    "ScreenElement",
    "ScreenAnalysis",
    "TemplateMatchEvidence",
    "analyze_screen",
    "detect_air_defense_targets",
    "detect_deployable_slots",
]
