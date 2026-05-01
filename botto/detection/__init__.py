"""Botto screen detection package."""

from .actions import ActionKind, RecommendedAction
from .analysis import ScreenAnalysis
from .detector import analyze_screen
from .evidence import Evidence, EvidenceKind
from .overlays.models import Overlay, PopupButton
from .screens.models import BaseScreen, HomeElement, ScreenElement

__all__ = [
    "ActionKind",
    "BaseScreen",
    "Evidence",
    "EvidenceKind",
    "HomeElement",
    "Overlay",
    "PopupButton",
    "RecommendedAction",
    "ScreenElement",
    "ScreenAnalysis",
    "analyze_screen",
]
