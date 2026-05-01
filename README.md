# botto

Botto is a scrcpy-first Clash of Clans debug/detection app plus a small reusable
Python SDK for Android device sessions, live frames, image analysis, OCR, and
debug artifacts.

- `botto` lists connected ADB devices and runs a read-only live debug view for
  Clash of Clans.
- `android_game_automator` provides reusable SDK primitives: typed geometry and
  device models, `FrameImage`, scrcpy frame streaming, ROI-first vision/OCR
  helpers, artifact storage, and minimal ADB session/app lifecycle helpers.

## Current scope

Implemented today:

- ADB-backed device discovery, async sessions, display state, and app
  launch/close lifecycle helpers.
- scrcpy-backed live frame capture as `FrameImage` objects.
- Read-only Clash screen and overlay analysis in `botto.detection`.
- Read-only latest-frame runtime loop in `botto.runtime` with throttled
  analysis.
- Live debug UI in `botto.live` as a viewer/sink over runtime, with overlays
  and artifact hotkeys.

Botto does not currently implement gameplay automation.

## Prerequisites

- Install Android Debug Bridge (`adb`) and make sure it is available on your
  `PATH`. The project uses ADB to discover devices and let scrcpy connect to
  them.
- Verify your emulator or USB device is visible and in the `device` state:

  ```sh
  adb version
  adb devices -l
  ```

## Quick SDK example

This launches Clash, reads one live scrcpy frame, saves it as an artifact, and
closes the app:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.artifacts import ArtifactStore
from android_game_automator.scrcpy import ScrcpyFrameSource


CLASH_PACKAGE = "com.supercell.clashofclans"


async def main() -> None:
    artifacts = ArtifactStore(".botto-artifacts")
    backend = AdbDeviceBackend()

    async with await backend.open_session() as session:
        await session.launch_app(CLASH_PACKAGE)
        try:
            serial = session.info.device.identity.device_id
            with ScrcpyFrameSource(serial=serial) as source:
                image = source.wait_for_frame(timeout=5.0)

            saved_path = artifacts.save_image("clash-live-frame", image)
            print(saved_path)
        finally:
            await session.close_app(CLASH_PACKAGE)


asyncio.run(main())
```

Each `ArtifactStore` writes to one run directory, named like
`YYYYMMDD-HHMMSS-xxxxxxxx` by default, such as
`.botto-artifacts/<run>/images/clash-live-frame.png`. The run-local
`manifest.jsonl` records saved artifact paths relative to the artifact root.

## Module layout

- `android_game_automator.types` — shared device, geometry, pixel, match, and
  OCR block models.
- `android_game_automator.image` — `FrameImage`, ROI utilities, and pixel/color
  probes.
- `android_game_automator.scrcpy` — scrcpy live frame source and frame
  conversion helpers.
- `android_game_automator.vision` — template and ORB feature matching helpers.
- `android_game_automator.ocr` — OCR helpers.
- `android_game_automator.artifacts` — local artifact persistence.
- `android_game_automator.adb` — minimal ADB device discovery, sessions,
  display state, and app lifecycle helpers.
- `botto.detection` — read-only Clash detectors, models, and templates.
- `botto.runtime` — read-only latest-frame loop with throttled screen analysis.
- `botto.live` — debug UI/sink over `botto.runtime`: overlay rendering,
  preview window, and artifact hotkeys.
- `botto.cli` — CLI parser and command dispatch.

## CLI

- `botto devices` — list usable ADB devices.
- `botto debug [--serial SERIAL|--device SERIAL] [--skip-launch]` — open the
  live debug viewer over the read-only runtime loop. By default it launches
  Clash first; `--skip-launch` debugs the current screen.

Live debug hotkeys:

- `s` — save the current raw frame and latest analysis JSON when available.
- `d` — save the current debug/annotated frame and latest analysis JSON when
  available.
- `q` or Esc — exit.

## SDK usage docs

- Practical SDK examples: `docs/android-game-automator-sdk.md`

## Development checks

- `just check`
- `uv run ruff check .`
- `uv run mypy`
- `uv run pytest`
