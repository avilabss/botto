# Android Game Automator SDK examples

Use this SDK for Android device discovery/session lifecycle, scrcpy live frames,
ROI-first image helpers, template/feature matching, OCR, and debug artifacts.
ADB support is intentionally small: list devices, open sessions, inspect display
state, and launch/close apps. Live image data comes from scrcpy as `FrameImage`
objects.

## Common imports

Most scripts start with a small subset of these imports:

```python
from pathlib import Path

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.artifacts import ArtifactStore
from android_game_automator.image import FrameImage, get_color, probe_color
from android_game_automator.ocr import OcrPreprocessConfig, read_text, read_text_blocks
from android_game_automator.scrcpy import ScrcpyFrameSource
from android_game_automator.types import NormalizedPoint, NormalizedRect, Point, Rect, Viewport
from android_game_automator.vision import find_feature_match, find_template
```

## Quick mental model

- `AdbDeviceBackend` lists usable ADB devices and opens async sessions for
  display metadata and app lifecycle operations.
- `ScrcpyFrameSource` connects to a device serial and returns live frames as
  RGBA32 `FrameImage` objects.
- Image helpers read pixels, crop ROIs, and pass frames into template matching,
  ORB matching, and OCR.
- `ArtifactStore` writes images, JSON, text, and bytes into one run directory
  with a `manifest.jsonl`.
- Vision/OCR helpers accept regions of interest (ROIs) so scripts can search the
  smallest useful part of a frame.

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

Use `try`/`finally` when a script should close an app after inspection:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend


PACKAGE_NAME = "com.supercell.clashofclans"


async def main() -> None:
    backend = AdbDeviceBackend()
    async with await backend.open_session() as session:
        await session.launch_app(PACKAGE_NAME)
        try:
            display = await session.get_display_state()
            print(display.size.width, display.size.height)
        finally:
            await session.close_app(PACKAGE_NAME)


asyncio.run(main())
```

## Read a live frame with scrcpy

Use the resolved ADB serial when creating a scrcpy frame source:

```python
import asyncio

from android_game_automator.adb import AdbDeviceBackend
from android_game_automator.scrcpy import ScrcpyFrameSource


async def main() -> None:
    backend = AdbDeviceBackend()
    async with await backend.open_session() as session:
        serial = session.info.device.identity.device_id
        with ScrcpyFrameSource(serial=serial) as source:
            image = source.wait_for_frame(timeout=5.0)

        print(image.width, image.height, image.pixel_format)


asyncio.run(main())
```

The remaining examples assume `image` is a `FrameImage` returned by
`ScrcpyFrameSource`.

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

If you pass a `Viewport`, normalized coordinates map inside that viewport
instead of the full image:

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

## Artifacts

`ArtifactStore` creates one run directory per store instance. Save images, JSON,
text, or bytes under that run for later debugging:

```python
artifacts = ArtifactStore(".botto-artifacts")

image_path = artifacts.save_image(
    "home-screen",
    image,
    metadata={"frame_id": image.frame_id},
)
json_path = artifacts.save_json(
    "home-screen-size",
    {"width": image.width, "height": image.height},
)

print(f"saved image to {image_path}")
print(f"saved metadata to {json_path}")
print(f"run directory: {artifacts.run_dir}")
```

## Get and probe colors

scrcpy frames are converted to RGBA32, so colors look like
`(red, green, blue, alpha)`:

```python
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
match = find_template(
    image,
    Path("templates/settings-gear.png"),
    min_confidence=0.90,
    region=NormalizedRect(left=0.70, top=0.00, width=0.30, height=0.30),
    scales=(1.0, 1.5, 2.0),
)

if match is None:
    print("settings gear not found")
else:
    print(f"found at {match.bounds}; center={match.center}")
```

Returned `Match.bounds` and `Match.center` use absolute source-image pixels.

Transparent PNG templates are supported. When the template has an alpha channel,
`find_template(...)` ignores template pixels whose alpha is below
`alpha_threshold` (default `16`), which is useful for assets saved with
transparent padding. If the visible alpha mask is empty or too small to match
reliably, `find_template(...)` raises `ValueError`. Source-image alpha is not
used as a mask.

## ORB feature matching

Use `find_feature_match(...)` for textured or feature-rich targets. Keep
`find_template(...)` as the first choice for simple UI icons:

```python
match = find_feature_match(
    image,
    Path("templates/textured-building.png"),
    min_matches=8,
    min_confidence=0.25,
    region=NormalizedRect(left=0.10, top=0.20, width=0.80, height=0.60),
)

if match is None:
    print("object not found")
else:
    print(f"found {match.match_count} feature matches at {match.center}")
```

Transparent PNG templates are also supported for ORB matching. When the template
has an alpha channel, `find_feature_match(...)` passes pixels with alpha below
`alpha_threshold` (default `16`) as masked-out pixels for template keypoint and
descriptor detection. A fully transparent or otherwise unusable template returns
`None` instead of raising.

## OCR

Use `read_text(...)` when you want one string. Use `read_text_blocks(...)` when
you need recognized blocks, confidence values, or bounds:

```python
resource_bar = NormalizedRect(left=0.00, top=0.00, width=1.00, height=0.20)

text = read_text(
    image,
    region=resource_bar,
    preprocess=OcrPreprocessConfig(scale=2, threshold=180),
)
print(text)

for block in read_text_blocks(image, region=resource_bar):
    print(block.text, block.confidence, block.bounds)
```

OCR works best when the region is as small as practical.
