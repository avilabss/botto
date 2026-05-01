"""Botto screen detection package."""

from .detector import analyze_screen
from .models import BaseScreen, Evidence, Overlay, RecommendedAction, ScreenAnalysis

__all__ = [
    "BaseScreen",
    "Evidence",
    "Overlay",
    "RecommendedAction",
    "ScreenAnalysis",
    "analyze_screen",
]
