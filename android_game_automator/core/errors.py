"""Framework-level exceptions shared by core contracts."""

from __future__ import annotations


class AndroidGameAutomatorCoreError(Exception):
    """Base exception for all core-layer framework errors."""


class CapabilityUnavailableError(AndroidGameAutomatorCoreError):
    """Raised when a requested capability is not declared."""
