"""Known base-screen detection package."""

from .detect import detect_base_screen
from .models import BaseScreen, HomeElement, ScreenElement

__all__ = ["BaseScreen", "HomeElement", "ScreenElement", "detect_base_screen"]
