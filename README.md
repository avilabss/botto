# botto

This repository now separates the reusable SDK from the future game bot app:

- `android_game_automator` is the reusable Python SDK for Android game automation.
- `botto` is a small reference app/CLI built on that SDK.

## Current scope

- Milestone focus: **ADB-only foundation**.
- Implemented: async-first core contracts plus ADB-backed device discovery, session metadata, screenshot capture, input execution, viewport-aware coordinate mapping, ROI-first template matching, OCR-ready vision services, local artifact recording, and small runtime helpers.
- `botto` reference flows: list devices, inspect a live session, and capture a frame into a local artifact directory.
- Not implemented yet: actual Clash of Clans automation logic.

## Quickstart prerequisites

- Install Android Debug Bridge (`adb`) and make sure it is available on your `PATH`.
  The SDK uses `adbutils-async`, but it still depends on a working local ADB
  installation/server.
- Before running the SDK or `botto`, verify ADB and device discovery:

  ```sh
  adb version
  adb devices -l
  ```

- `adb devices -l` should list your emulator or USB device as `device`. If the
  command is missing or the device is not listed, finish ADB setup first.

## Module layout

- `android_game_automator.core` — shared contracts/models for device, capture, input, detection, and artifacts.
- `android_game_automator.backends` — backend adapters (ADB discovery/session/input/capture layer now available).
- `android_game_automator.vision` — ROI utilities, pixel/color probes, template matching, and OCR helpers.
- `android_game_automator.runtime` — runtime orchestration and loop wiring.
- `android_game_automator.artifacts` — run outputs and generated artifacts.
- `botto` — reference CLI that exercises the SDK from an app boundary.

## Reference CLI

- `python -m botto` shows the reference CLI help.
- `python -m botto devices` lists adb devices through `AdbDeviceBackend`.
- `python -m botto session --device <serial>` inspects a live session and current display metadata.
- `python -m botto capture --device <serial>` captures a screenshot and writes it through `LocalArtifactRecorder` into `.botto-output/` by default.

## Entrypoints

- `python -m android_game_automator` runs the reusable SDK CLI.
- `python -m botto` runs the Botto reference CLI.

## SDK usage docs

- Practical SDK examples: `docs/android-game-automator-sdk.md`

## Development checks

- `uv run ruff check .`
- `uv run mypy android_game_automator botto`
- `uv run pytest`
