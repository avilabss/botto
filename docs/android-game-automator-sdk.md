# Android Game Automator SDK Usage

This repository currently ships an ADB-first SDK foundation plus a tiny `botto` reference app.

## What is implemented

- Device discovery with `AdbDeviceBackend`
- Session metadata and current display inspection
- Screenshot capture as `CapturedFrame`
- ADB input command execution for tap, swipe, key press, and text entry
- Local artifact persistence with `LocalArtifactRecorder`
- ROI-first image utilities, template matching, and OCR helpers
- Small async runtime helpers for retry and polling loops

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

## Discover devices

```python
import asyncio

from android_game_automator.backends.adb import AdbDeviceBackend


async def main() -> None:
    backend = AdbDeviceBackend()
    devices = await backend.list_devices()
    for device in devices:
        print(device.identity.device_id, device.metadata.get("adb.target_kind"))


asyncio.run(main())
```

## Open a session and inspect it

```python
import asyncio

from android_game_automator.backends.adb import AdbDeviceBackend


async def main() -> None:
    backend = AdbDeviceBackend()
    session = await backend.open_session("emulator-5554")
    try:
        print(session.info.session_id)
        print(session.info.device.identity.display_name)

        display = await session.get_display_state()
        print(display.size.width, display.size.height, display.rotation_quadrants)
    finally:
        await session.close()


asyncio.run(main())
```

## Capture a frame and save an artifact

```python
import asyncio

from android_game_automator.artifacts.local import LocalArtifactRecorder
from android_game_automator.backends.adb import AdbDeviceBackend


async def main() -> None:
    backend = AdbDeviceBackend()
    recorder = LocalArtifactRecorder("run-output")
    session = await backend.open_session("emulator-5554")
    try:
        frame = await session.capture_frame()
        record = await recorder.save_frame_image_artifact(
            label="home-screen",
            frame=frame,
            metadata={"device_id": session.info.device.identity.device_id},
        )
        print(record.persisted_path)
    finally:
        await session.close()


asyncio.run(main())
```

## Execute input actions

```python
import asyncio

from android_game_automator.backends.adb import AdbDeviceBackend
from android_game_automator.core import NormalizedPoint, TapAction


async def main() -> None:
    backend = AdbDeviceBackend()
    session = await backend.open_session("emulator-5554")
    try:
        result = await session.execute_input(TapAction(point=NormalizedPoint(x=0.5, y=0.5)))
        print(result.status.value, result.message)
    finally:
        await session.close()


asyncio.run(main())
```

## Read ROI pixels or OCR text

```python
import asyncio

from android_game_automator.backends.adb import AdbDeviceBackend
from android_game_automator.core import NormalizedPoint, NormalizedRect
from android_game_automator.vision.image import FrameImage, probe_color
from android_game_automator.vision.ocr import OcrService, RapidOcrEngine


async def main() -> None:
    backend = AdbDeviceBackend()
    session = await backend.open_session("emulator-5554")
    try:
        frame = await session.capture_frame()
        frame_image = FrameImage.from_captured_frame(frame)

        is_green = probe_color(
            frame_image,
            NormalizedPoint(x=0.5, y=0.2),
            expected=(0, 255, 0, 255),
            tolerance=12,
        )

        ocr = OcrService(engine=RapidOcrEngine())
        result = ocr.read(
            frame_image,
            region=NormalizedRect(left=0.1, top=0.1, width=0.3, height=0.1),
        )
        print(is_green, result.text)
    finally:
        await session.close()


asyncio.run(main())
```

## Use runtime helpers for bot loops

```python
import asyncio

from android_game_automator.backends.adb import AdbDeviceBackend
from android_game_automator.runtime import RetryPolicy, run_with_retry, wait_for


async def main() -> None:
    backend = AdbDeviceBackend()
    session = await backend.open_session("emulator-5554")
    checks = {"count": 0}

    async def read_status() -> str:
        checks["count"] += 1
        return "ready" if checks["count"] >= 2 else "loading"

    try:
        ready_state = await wait_for(
            probe=read_status,
            timeout_seconds=5.0,
            interval_seconds=0.25,
            is_complete=lambda value: value == "ready",
        )
        frame = await run_with_retry(
            operation=session.capture_frame,
            policy=RetryPolicy(max_attempts=3, delay_seconds=0.2),
        )
        print(ready_state, frame.metadata.size)
    finally:
        await session.close()


asyncio.run(main())
```

## Reference app mapping

`botto` intentionally stays small and app-oriented:

- `botto devices` demonstrates backend discovery.
- `botto session` demonstrates session inspection.
- `botto capture` demonstrates capture plus artifact persistence.

That keeps `android_game_automator` as the reusable SDK boundary while still providing a real app entrypoint for future bot work.
