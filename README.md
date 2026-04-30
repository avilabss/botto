# botto

This repository now separates the reusable SDK from the future game bot app:

- `android_game_automator` is the reusable Python SDK for Android game automation.
- `botto` is a small reference app/CLI built on that SDK.

## Current scope

- Milestone focus: **ADB-only foundation**.
- Implemented: shared data types plus ADB-backed device discovery,
  async sessions, screenshot capture, app lifecycle helpers, direct input
  execution with common `AndroidKey` enums, viewport-aware coordinate mapping,
  best-effort ADB multi-swipe/pinch helpers,
  ROI-first template and ORB feature matching, OCR-ready vision helpers, and
  run-organized artifact output.
- `botto` reference flows: list devices, inspect a live session, and capture a screenshot to a PNG file.
- Not implemented yet: actual Clash of Clans automation logic.

## Quickstart prerequisites

- Install Android Debug Bridge (`adb`) and make sure it is available on your `PATH`.
  The SDK uses `adbutils-async`, but it still depends on a working local ADB
  installation/server.
- Before using the SDK or `botto`, verify ADB and device discovery:

  ```sh
  adb version
  adb devices -l
  ```

- `adb devices -l` should list your emulator or USB device as `device`. If the
  command is missing or the device is not listed, finish ADB setup first.

## Quick SDK example

For one-off scripts, create an ADB backend and open an async session. When one
usable ADB device is connected, `open_session()` selects it automatically. This
launches Clash of Clans, captures a screenshot image, saves it locally, and
closes the app without tapping or swiping in-game:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.artifacts import ArtifactStore


CLASH_PACKAGE = "com.supercell.clashofclans"


async def main() -> None:
    artifacts = ArtifactStore(".botto-artifacts")

    backend = AdbDeviceBackend()
    async with await backend.open_session() as session:
        await session.launch_app(CLASH_PACKAGE)
        try:
            image = await session.screenshot()
            saved_path = artifacts.save_image("clash-of-clans", image)
            print(saved_path)
        finally:
            await session.close_app(CLASH_PACKAGE)


asyncio.run(main())
```

Each `ArtifactStore` instance writes all saves to one run directory, named like
`YYYYMMDD-HHMMSS-xxxxxxxx` by default, such as
`.botto-artifacts/<run>/images/clash-of-clans.png`. Construct a new store
without a `run_name` to start a new default run. The run-local `manifest.jsonl`
records artifact paths relative to the artifact root, including the run folder.
See `quick_run.py` for the same launch/capture/save/close flow as a local
learning harness, and `docs/android-game-automator-sdk.md` for template
matching, ORB feature matching, OCR, and advanced API examples.

## Module layout

- `android_game_automator.types` — shared device, geometry, pixel, match, and OCR block models.
- `android_game_automator.image` — frame images, ROI utilities, and pixel/color probes.
- `android_game_automator.vision` — template and ORB feature matching helpers.
- `android_game_automator.ocr` — OCR helpers.
- `android_game_automator.artifacts` — simple local artifact persistence.
- `android_game_automator.adb` — ADB discovery/session/input/capture layer.
- `botto` — reference CLI that exercises the SDK from an app boundary.

## Reference CLI

- `python -m botto` shows the reference CLI help.
- `python -m botto devices` lists adb devices through `AdbDeviceBackend`.
- `python -m botto session --device <serial>` inspects a live session and current display metadata.
- `python -m botto capture --device <serial>` captures a screenshot and saves it under `.botto-artifacts/<run>/images/device-capture.png` by default.

## ADB input note

`AdbDeviceSession.multi_swipe(...)`, `pinch_in(...)`, and `pinch_out(...)` issue
concurrent ADB `input swipe` commands as best-effort multi-touch. Plain ADB does
not guarantee true multi-touch on every device or game.

## Entrypoint

- `python -m botto` runs the Botto reference CLI.

## SDK usage docs

- Practical SDK examples: `docs/android-game-automator-sdk.md`

## Development checks

- `just check`
- `uv run ruff check .`
- `uv run mypy`
- `uv run pytest`
