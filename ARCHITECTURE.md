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
- `botto.detection` — read-only Clash screen and overlay analysis built on SDK
  image, vision, OCR, and template helpers.
- `botto.live` — live debug orchestration: ADB session setup, scrcpy frame
  source wiring, throttled analysis, OpenCV preview, overlay rendering, and
  artifact hotkeys.

Current live-debug flow:

1. `botto debug` resolves an ADB device and launches Clash unless
   `--skip-launch` is passed.
2. `ScrcpyFrameSource` streams live frames for that device serial.
3. `botto.detection.analyze_screen` runs periodically on recent frames.
4. `botto.live` renders annotations and handles save/exit hotkeys.

## Commands and checks

Supported CLI commands:

- `botto devices`
- `botto debug [--serial/--device] [--skip-launch]`

Project checks:

- `just check` runs lint, type-checking, and tests.
- Individual commands are `uv run ruff check .`, `uv run mypy`, and
  `uv run pytest`.

Tests live under `tests/`, grouped by package (`tests/android_game_automator/`
and `tests/botto/`) with `tests/test_*.py` naming.

## Boundaries

Botto currently provides read-only debugging and detection. It does not include a
gameplay bot loop.
