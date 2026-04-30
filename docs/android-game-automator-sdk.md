# Android Game Automator SDK Usage

This repository currently ships an ADB-first SDK foundation plus a tiny `botto`
reference app. The SDK talks to Android through ADB only: it can launch/close
apps, press keys, send input, and capture screenshots, but it does not read game
internals or include Clash of Clans strategy automation.

## What is implemented

- Device discovery and session opening with `AdbDeviceBackend`
- Async ADB sessions with `async with` cleanup
- Screenshot capture with `session.screenshot()`
- App lifecycle helpers: `session.launch_app(...)`, `session.close_app(...)`, and `session.key("HOME")`
- Direct ADB input methods for tap, swipe, key press, and text entry
- ROI-first image utilities, simple `find_template(...)` matching, function-first OCR helpers, and a local `ArtifactStore`

## ADB setup and verification

The SDK uses `adbutils-async`, but it still requires a working local Android Debug
Bridge (`adb`) installation and ADB server. Install ADB, make sure it is on your
`PATH`, enable USB debugging on the device, and approve the debugging prompt when
connecting over USB.

Common install options:

- Linux:
  - Arch/Manjaro: `sudo pacman -S android-tools`
  - Ubuntu/Debian: `sudo apt update && sudo apt install adb`
  - Fedora: `sudo dnf install android-tools`
- macOS with Homebrew: `brew install android-platform-tools`
- Windows: download the Android SDK Platform-Tools ZIP from Android Developers,
  extract it, add the extracted `platform-tools` directory to your `PATH`, and
  open a new terminal.

Before using the SDK or `botto`, run these baseline checks:

```sh
adb version
adb devices -l
```

In `adb devices -l` output, common device states are:

- `device` — ready for SDK/`botto` use.
- `unauthorized` — unlock the phone and accept the USB debugging prompt; if the
  prompt does not appear, reconnect the cable or revoke USB debugging
  authorizations and try again.
- `offline` — ADB has a stale or broken connection; reconnect the device, then
  try `adb kill-server` followed by `adb start-server`.

On Linux, if the phone is visible over USB but ADB cannot use it, the issue is
often USB permissions or missing udev rules. Install your distro's Android udev
rules (or add a vendor-ID rule), reload udev, and reconnect the phone.

## Quick start: launch, capture, save, close

Create an `AdbDeviceBackend`, list devices when you need to discover serials,
and open a session. The example below selects the only connected usable ADB
device through `backend.open_session()`. If you have more than one, use the
serial shown by `adb devices -l` when calling `backend.open_session("serial")`.

This example launches Clash of Clans, captures a screenshot, saves it, and closes
the app. It intentionally avoids taps/swipes and does not automate gameplay.

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.artifacts import ArtifactStore


CLASH_PACKAGE = "com.supercell.clashofclans"


async def main() -> None:
    artifacts = ArtifactStore("botto-output")

    backend = AdbDeviceBackend()
    async with await backend.open_session() as session:
        await session.launch_app(CLASH_PACKAGE)
        try:
            image = await session.screenshot()
            saved_path = artifacts.save_image("clash-of-clans", image)
            print(f"saved screenshot to {saved_path}")
        finally:
            await session.close_app(CLASH_PACKAGE)


asyncio.run(main())
```

`quick_run.py` contains this same flow as a local learning harness.

## App lifecycle helpers

Use the lifecycle helpers when a script needs to foreground, background, or close
an app through ADB:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend


async def main() -> None:
    backend = AdbDeviceBackend()
    async with await backend.open_session("emulator-5554") as session:
        await session.launch_app("com.example.game")
        await session.key("HOME")
        await session.close_app("com.example.game")


asyncio.run(main())
```

## Direct input methods

Use normalized display coordinates for taps and swipes. Methods complete
successfully or raise the underlying validation/ADB error:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend


async def main() -> None:
    async with await AdbDeviceBackend().open_session("emulator-5554") as session:
        await session.tap(0.5, 0.5)
        await session.swipe(0.2, 0.8, 0.8, 0.8, duration_ms=250)
        await session.key("BACK")
        await session.text("hello world")


asyncio.run(main())
```

## Find UI elements with template matching

Template matching compares a screenshot image against a small PNG you provide, such as
an icon cropped from your own capture. Start with `find_template(...)` for quick
scripts; source and template inputs may be `FrameImage` objects, PIL images, or paths.

```python
import asyncio
from pathlib import Path

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.types import NormalizedRect
from android_game_automator.vision import find_template


async def main() -> None:
    backend = AdbDeviceBackend()
    async with await backend.open_session("emulator-5554") as session:
        image = await session.screenshot()
        match = find_template(
            image,
            Path("templates/settings-gear.png"),
            min_confidence=0.90,
            region=NormalizedRect(left=0.70, top=0.00, width=0.30, height=0.30),
        )

        if match is None:
            print("template not found")
            return

        print(f"found settings gear at ({match.center.x}, {match.center.y})")


asyncio.run(main())
```

Useful knobs:

- `min_confidence` sets the acceptance threshold (`threshold` is accepted as an alias).
- `region=NormalizedRect(...)` narrows the search area for speed and fewer false
  positives.
- `scales=(...)` and `rotations=(...)` are available when the template may render
  at a few known sizes or orientations.
- Returned `Match.bounds` and `Match.center` use absolute source-image pixels.

## Simple OCR

OCR is available through `read_text(...)` and `read_text_blocks(...)` with
RapidOCR used internally. Keep OCR reads scoped to the smallest useful region
when you can, or omit `region` to read the full screenshot.

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.ocr import read_text
from android_game_automator.types import NormalizedRect


async def main() -> None:
    backend = AdbDeviceBackend()
    async with await backend.open_session("emulator-5554") as session:
        image = await session.screenshot()
        text = read_text(
            image,
            region=NormalizedRect(left=0.00, top=0.00, width=1.00, height=0.20),
        )
        print(text)


asyncio.run(main())
```

## Advanced APIs

The concrete module APIs are the practical starting point for scripts and
reusable SDK pieces:

- `AdbDeviceBackend` for explicit device listing and session opening.
- Direct `AdbDeviceSession` methods (`tap`, `swipe`, `key`, `text`) for input.
- `find_template(...)` for one-off template matching against a screenshot,
  optional ROI, and known scale/rotation variants.
- `ArtifactStore` for saving debug screenshots, JSON, text, and binary artifacts with a manifest.

## Reference app mapping

`botto` intentionally stays small and app-oriented:

- `botto devices` demonstrates backend discovery.
- `botto session` demonstrates session inspection.
- `botto capture` demonstrates capture plus `ArtifactStore` PNG persistence.

That keeps `android_game_automator` as the reusable SDK boundary while still providing a real app entrypoint for future bot work.
