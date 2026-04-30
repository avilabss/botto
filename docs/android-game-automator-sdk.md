# Android Game Automator SDK examples

Use this SDK when you want a Python script such as `quick_run.py` to discover an
Android device over ADB, open an async session, capture screenshots, inspect
pixels/text/UI images, and send input.

## Common imports

Most scripts start with a small subset of these imports:

```python
from pathlib import Path

from android_game_automator.adb import AdbDeviceBackend, AndroidKey
from android_game_automator.artifacts import ArtifactStore
from android_game_automator.image import get_color, probe_color
from android_game_automator.ocr import OcrPreprocessConfig, read_text, read_text_blocks
from android_game_automator.types import NormalizedPoint, NormalizedRect, Point, Rect, Viewport
from android_game_automator.vision import find_feature_match, find_template
```

## Quick mental model

- `AdbDeviceBackend` lists ADB devices and opens an `AdbDeviceSession`.
- `AdbDeviceSession` is async; use `async with await backend.open_session(...)` so
  cleanup happens even when the script fails.
- `session.screenshot()` returns a `FrameImage`. Image helpers read pixels,
  crop regions, and pass frames into template matching, ORB matching, and OCR.
- `ArtifactStore` writes screenshots and other debugging files into one run
  directory with a `manifest.jsonl`.
- Vision/OCR helpers accept regions of interest (ROIs) so scripts can search the
  smallest useful part of a screenshot.

## Coordinates: `Point` vs `NormalizedPoint`

Use absolute coordinates when you already know the exact pixel in the current
image:

```python
color = get_color(image, Point(x=320, y=180))
```

Use normalized coordinates when the location is relative to the screen or ROI:

```python
color = get_color(image, NormalizedPoint(x=0.50, y=0.50))  # center of image
```

Normalized coordinates are floats from `0.0` to `1.0`:

- `NormalizedPoint(x=0.0, y=0.0)` maps to the top-left pixel.
- `NormalizedPoint(x=1.0, y=1.0)` maps to the bottom-right pixel.
- `NormalizedRect(left=0.70, top=0.00, width=0.30, height=0.30)` means “the top
  right 30% of the image.”

This is useful across devices and resolutions. A button near the center is still
near `(0.5, 0.5)` on a 1080p phone, a 1440p phone, or an emulator. If you pass a
`Viewport`, normalized coordinates map inside that viewport instead of the full
image:

```python
bottom_panel = Viewport(
    surface_size=image.size,
    region=Rect(left=0, top=image.height - 240, width=image.width, height=240),
)
panel_center_color = get_color(
    image,
    NormalizedPoint(x=0.50, y=0.50),
    viewport=bottom_panel,
)
```

ADB input methods accept the same point objects. Use `Point` for absolute
display pixels or `NormalizedPoint` for coordinates that should map through the
current display viewport:

```python
await session.tap(NormalizedPoint(x=0.50, y=0.50))  # tap the display center
```

## ADB setup check

Install Android Debug Bridge (`adb`), enable USB debugging, connect a device or
start an emulator, then verify:

```sh
adb version
adb devices -l
```

In `adb devices -l`, the SDK uses entries in the `device` state. `unauthorized`
means the Android device has not approved USB debugging yet; `offline` usually
means reconnect the device or restart the ADB server.

## List devices and inspect metadata

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend


async def main() -> None:
    backend = AdbDeviceBackend()
    devices = await backend.list_devices()

    if not devices:
        print("No usable ADB devices found")
        return

    for device in devices:
        identity = device.identity
        print(identity.device_id, identity.display_name or "(no display name)")
        for key, value in sorted(device.metadata.items()):
            print(f"  {key}: {value}")


asyncio.run(main())
```

Useful metadata keys include `adb.target_kind`, `adb.manufacturer`, `adb.model`,
`adb.android_release`, and `adb.android_sdk` when ADB can read them.

## Open a session dynamically

When exactly one device is connected, `open_session()` can select it for you. If
your script can see multiple devices, list them first and pass the chosen
`device_id` explicitly:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend


async def main() -> None:
    backend = AdbDeviceBackend()
    devices = await backend.list_devices()
    if not devices:
        raise RuntimeError("Connect an emulator or USB device first")

    selected = next(
        (device for device in devices if device.metadata.get("adb.target_kind") == "emulator"),
        devices[0],
    )

    async with await backend.open_session(selected.identity.device_id) as session:
        display = await session.get_display_state()
        print(session.info.session_id)
        print(display.size.width, display.size.height, display.rotation_quadrants)


asyncio.run(main())
```

## Launch and close an app

Use `try`/`finally` when a script should close the app after a capture or test:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend


PACKAGE_NAME = "com.supercell.clashofclans"


async def main() -> None:
    backend = AdbDeviceBackend()
    async with await backend.open_session() as session:
        await session.launch_app(PACKAGE_NAME)
        try:
            image = await session.screenshot()
            print(image.width, image.height)
        finally:
            await session.close_app(PACKAGE_NAME)


asyncio.run(main())
```

## Screenshot and artifacts

`ArtifactStore` creates one run directory per store instance. Save screenshots,
JSON, text, or bytes under that run for later debugging:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.artifacts import ArtifactStore


async def main() -> None:
    artifacts = ArtifactStore(".botto-artifacts")
    backend = AdbDeviceBackend()

    async with await backend.open_session() as session:
        image = await session.screenshot()
        screenshot_path = artifacts.save_image(
            "home-screen",
            image,
            metadata={"device_id": session.info.device.identity.device_id},
        )
        artifacts.save_json(
            "home-screen-size",
            {"width": image.width, "height": image.height},
        )

    print(f"saved screenshot to {screenshot_path}")
    print(f"run directory: {artifacts.run_dir}")


asyncio.run(main())
```

## Get and probe colors

Use `get_color(...)` when you need the actual color tuple. A screenshot from ADB
uses RGBA channels, so colors look like `(red, green, blue, alpha)`:

```python
image = await session.screenshot()

absolute_color = get_color(image, Point(x=100, y=200))
center_color = get_color(image, NormalizedPoint(x=0.50, y=0.50))

print(absolute_color)
print(center_color)
```

Use `probe_color(...)` when you only need to know whether a pixel matches an
expected color. `tolerance` allows each channel to differ by a small amount:

```python
is_close_enough = probe_color(
    image,
    NormalizedPoint(x=0.50, y=0.50),
    expected=(255, 255, 255, 255),
    tolerance=8,
)

if is_close_enough:
    print("center is approximately white")
```

Both helpers accept `Point` or `NormalizedPoint`, and both accept an optional
`viewport` when you want normalized coordinates to map inside a smaller region.

## Template matching

Use `find_template(...)` for flat UI icons and buttons. Source and template can
be `FrameImage` objects, PIL images, or filesystem paths:

```python
import asyncio
from pathlib import Path

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.types import NormalizedRect
from android_game_automator.vision import find_template


async def main() -> None:
    backend = AdbDeviceBackend()
    async with await backend.open_session() as session:
        image = await session.screenshot()
        match = find_template(
            image,
            Path("templates/settings-gear.png"),
            min_confidence=0.90,
            region=NormalizedRect(left=0.70, top=0.00, width=0.30, height=0.30),
            scales=(1.0, 1.5, 2.0),
        )

        if match is None:
            print("settings gear not found")
            return

        print(f"found at {match.bounds}; center={match.center}")


asyncio.run(main())
```

Returned `Match.bounds` and `Match.center` use absolute source-image pixels.

## ORB feature matching

Use `find_feature_match(...)` for textured or feature-rich targets. Keep
`find_template(...)` as the first choice for simple UI icons:

```python
import asyncio
from pathlib import Path

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.types import NormalizedRect
from android_game_automator.vision import find_feature_match


async def main() -> None:
    backend = AdbDeviceBackend()
    async with await backend.open_session() as session:
        image = await session.screenshot()
        match = find_feature_match(
            image,
            Path("templates/textured-building.png"),
            min_matches=8,
            min_confidence=0.25,
            region=NormalizedRect(left=0.10, top=0.20, width=0.80, height=0.60),
        )

        if match is None:
            print("object not found")
            return

        print(f"found {match.match_count} feature matches at {match.center}")

        await session.tap(match.center)


asyncio.run(main())
```

`match.center` is an absolute pixel `Point` in the source image, so it can be
passed directly to `session.tap(...)`.

## OCR

Use `read_text(...)` when you want one string. Use `read_text_blocks(...)` when
you need recognized blocks, confidence values, or bounds:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.ocr import OcrPreprocessConfig, read_text, read_text_blocks
from android_game_automator.types import NormalizedRect


async def main() -> None:
    backend = AdbDeviceBackend()
    async with await backend.open_session() as session:
        image = await session.screenshot()
        resource_bar = NormalizedRect(left=0.00, top=0.00, width=1.00, height=0.20)

        text = read_text(
            image,
            region=resource_bar,
            preprocess=OcrPreprocessConfig(scale=2, threshold=180),
        )
        print(text)

        for block in read_text_blocks(image, region=resource_bar):
            print(block.text, block.confidence, block.bounds)


asyncio.run(main())
```

OCR works best when the region is as small as practical.

## Input and `AndroidKey` enum usage

`tap`, `swipe`, and `multi_swipe` take `Point` or `NormalizedPoint` inputs.
`multi_swipe`, `pinch_in`, and `pinch_out` are best-effort ADB multi-touch APIs:
they issue concurrent `input swipe` commands, but plain ADB does not guarantee
true multi-touch on every device, Android version, or game. `key` accepts an
`AndroidKey` enum member or a safe raw key string:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend, AndroidKey
from android_game_automator.types import NormalizedPoint


async def main() -> None:
    backend = AdbDeviceBackend()
    async with await backend.open_session("emulator-5554") as session:
        await session.tap(NormalizedPoint(x=0.50, y=0.50))
        await session.swipe(
            NormalizedPoint(x=0.20, y=0.80),
            NormalizedPoint(x=0.80, y=0.80),
            duration_ms=250,
        )
        await session.multi_swipe(
            (
                (NormalizedPoint(x=0.20, y=0.70), NormalizedPoint(x=0.45, y=0.70)),
                (NormalizedPoint(x=0.80, y=0.70), NormalizedPoint(x=0.55, y=0.70)),
            ),
            duration_ms=300,
        )
        await session.pinch_in(duration_ms=300)
        await session.pinch_out(center=NormalizedPoint(x=0.50, y=0.50), duration_ms=300)
        await session.key(AndroidKey.BACK)
        await session.key(AndroidKey.HOME)
        await session.text("hello world")


asyncio.run(main())
```

Prefer `AndroidKey` for common keys so scripts avoid hardcoded keyevent strings.
Pinch spans default to sensible normalized distances around the display center;
custom spans are normalized against the smaller display dimension.
