"""CLI entrypoints for the Android Game Automator SDK."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from importlib import metadata

STATUS_MESSAGE = (
    "Android Game Automator SDK is ready. "
    "ADB-first foundation modules are available."
)


def _package_version() -> str:
    try:
        return metadata.version("android-game-automator")
    except metadata.PackageNotFoundError:
        return "0.0.0+local"


def build_parser() -> argparse.ArgumentParser:
    """Build the project CLI parser."""
    parser = argparse.ArgumentParser(
        prog="android-game-automator",
        description="Android Game Automator SDK CLI.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_package_version()}",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """Run the SDK CLI command."""
    parser = build_parser()
    parser.parse_args(argv)
    print(STATUS_MESSAGE)
    return 0


def main() -> int:
    """Process CLI args and return an exit code."""
    return run()
