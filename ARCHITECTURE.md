# Architecture

Botto is split into a small reusable Android-game SDK and a scrcpy-first Clash
debug/detection app.

## Reusable SDK: `android_game_automator`

The SDK uses flat public modules:

- `android_game_automator.types` — frozen dataclass models for device/session
  identity, geometry, viewports, matches, OCR blocks, and pixel formats.
- `android_game_automator.image` — `FrameImage`, pixel reads, color probes, ROI
  resolution, crops, and PIL conversion.
- `android_game_automator.scrcpy` — read-only scrcpy frame source that converts
  py-scrcpy-sdk frames into RGBA32 `FrameImage` values.
- `android_game_automator.adb` — minimal ADB device discovery, async sessions,
  display state, and app launch/close lifecycle helpers.
- `android_game_automator.vision` — template and ORB feature matching.
- `android_game_automator.ocr` — OCR preprocessing and text/block readers.
- `android_game_automator.artifacts` — run-scoped image/JSON/text/binary
  artifact persistence with a manifest.

ADB is used for device/session/app lifecycle. scrcpy is the canonical live frame
path.

## Botto app packages

- `botto.cli` — stdlib `argparse` entrypoint for the current commands.
- `botto.detection` — read-only Clash detectors, models, and templates built on
  SDK image, vision, OCR, and template helpers.
- `botto.runtime` — read-only runtime loop: ADB session setup, optional app
  launch, scrcpy latest-frame polling, throttled background analysis, and
  `RuntimeLoopState` delivery to a sink.
- `botto.live` — debug preview/sink over `botto.runtime`: OpenCV preview,
  overlay rendering, save/exit hotkeys, and artifact persistence.

Current runtime flow:

1. `botto run` enters `botto.runtime.run_read_only_runtime` with a headless
   state-log sink; `botto run --debug` enters `botto.live` with a debug preview
   UI sink.
2. The selected sink consumes `RuntimeLoopState` snapshots from the runtime.
3. `botto.runtime` opens the ADB session, launches Clash unless
   `--skip-launch` is passed, starts `ScrcpyFrameSource`, and tracks the latest
   frame.
4. `botto.runtime` runs `botto.detection.analyze_screen` on throttled frames and
   delivers `RuntimeLoopState` snapshots to the sink.
5. `botto.live` renders debug preview annotations and handles save/exit hotkeys.

## Commands and checks

Supported CLI commands:

- `botto devices`
- `botto run [--serial/--device] [--skip-launch]`
- `botto run --debug [--serial/--device] [--skip-launch]`

Project checks:

- `just check` runs lint, type-checking, and tests.
- Individual commands are `uv run ruff check .`, `uv run mypy`, and
  `uv run pytest`.

Tests live under `tests/`, grouped by package (`tests/android_game_automator/`
and `tests/botto/`) with `tests/test_*.py` naming.

## Boundaries

Botto currently provides read-only debugging and detection. The runtime loop
emits frame and analysis state to sinks; it does not tap, swipe, perform
gameplay recovery, or run gameplay automation.
