"""Tests for shared SDK data models and invariants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from android_game_automator.types import (
    DeviceIdentity,
    DeviceInfo,
    NormalizedPoint,
    NormalizedRect,
    Point,
    Rect,
    SessionInfo,
    Size,
    Viewport,
)


def test_geometry_models_enforce_bounds() -> None:
    rect = Rect(left=10, top=20, width=30, height=40)
    normalized_rect = NormalizedRect(left=0.25, top=0.2, width=0.5, height=0.7)

    assert rect.right == 40
    assert rect.bottom == 60
    assert normalized_rect.right == 0.75
    assert normalized_rect.bottom == pytest.approx(0.9)

    with pytest.raises(ValueError):
        NormalizedPoint(x=1.2, y=0.5)

    with pytest.raises(ValueError):
        NormalizedRect(left=0.8, top=0.0, width=0.3, height=0.1)


def test_viewport_maps_normalized_points_and_rects_deterministically() -> None:
    viewport = Viewport(surface_size=Size(width=1080, height=1920))

    assert viewport.map_point(NormalizedPoint(x=0.0, y=0.0)) == Point(x=0, y=0)
    assert viewport.map_point(NormalizedPoint(x=1.0, y=1.0)) == Point(x=1079, y=1919)
    assert viewport.map_rect(NormalizedRect(left=0.0, top=0.0, width=1.0, height=1.0)) == Rect(
        left=0,
        top=0,
        width=1080,
        height=1920,
    )


def test_viewport_mapping_avoids_binary_float_pixel_drift() -> None:
    point_viewport = Viewport(surface_size=Size(width=26, height=1))
    rect_viewport = Viewport(surface_size=Size(width=100, height=100))
    shifted_rect = NormalizedRect(left=0.29, top=0.29, width=0.1, height=0.1)
    clipped_rect = NormalizedRect(left=0.0, top=0.0, width=0.07, height=0.07)
    edge_rect = NormalizedRect(left=0.1, top=0.1, width=0.2, height=0.2)

    assert point_viewport.map_point(NormalizedPoint(x=0.58, y=0.0)) == Point(x=15, y=0)
    assert rect_viewport.map_rect(shifted_rect) == Rect(
        left=29,
        top=29,
        width=10,
        height=10,
    )
    assert rect_viewport.map_rect(clipped_rect) == Rect(
        left=0,
        top=0,
        width=7,
        height=7,
    )
    assert rect_viewport.map_rect(edge_rect) == Rect(
        left=10,
        top=10,
        width=20,
        height=20,
    )


def test_viewport_maps_landscape_and_region_restricted_coordinates() -> None:
    viewport = Viewport(
        surface_size=Size(width=1920, height=1080),
        region=Rect(left=100, top=50, width=400, height=200),
    )

    assert viewport.map_point(NormalizedPoint(x=0.5, y=0.5)) == Point(x=300, y=150)
    assert viewport.map_rect(NormalizedRect(left=0.25, top=0.25, width=0.5, height=0.5)) == Rect(
        left=200,
        top=100,
        width=200,
        height=100,
    )

    with pytest.raises(ValueError):
        Viewport(
            surface_size=Size(width=1920, height=1080),
            region=Rect(left=1800, top=0, width=200, height=100),
        )


def test_device_and_session_models_have_value_semantics() -> None:
    now = datetime.now(UTC)
    source_metadata = {"model": "Pixel"}
    session_metadata = {"run_id": "1"}
    device = DeviceInfo(
        identity=DeviceIdentity(
            backend_name="adb",
            device_id="emulator-5554",
            display_name="Pixel",
        ),
        metadata=source_metadata,
    )
    session = SessionInfo(
        session_id="session-1",
        device=device,
        started_at=now,
        metadata=session_metadata,
    )

    source_metadata["model"] = "Mutated"
    session_metadata["run_id"] = "mutated"

    assert session.device.identity.device_id == "emulator-5554"
    assert device.metadata["model"] == "Pixel"
    assert session.metadata["run_id"] == "1"

    with pytest.raises(TypeError):
        device.metadata["model"] = "Mutated"

    with pytest.raises(TypeError):
        session.metadata["run_id"] = "mutated"
