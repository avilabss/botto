"""Blocking overlay and popup-button detection models."""

from __future__ import annotations

from enum import StrEnum


class Overlay(StrEnum):
    """Blocking overlays Botto can currently identify."""

    NONE = "none"
    CONNECTION_LOST = "connection_lost"
    ANOTHER_DEVICE_CONNECTED = "another_device_connected"
    ANYONE_THERE = "anyone_there"
    UNKNOWN_MODAL = "unknown_modal"


class PopupButton(StrEnum):
    """Popup buttons Botto may recommend as read-only action targets."""

    TRY_AGAIN = "try_again"
    RELOAD = "reload"
    RELOAD_GAME = "reload_game"


__all__ = ["Overlay", "PopupButton"]
