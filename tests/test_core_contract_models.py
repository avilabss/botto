"""Tests for core contract models and invariants."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

import pytest
from android_game_automator.core import (
    ArtifactKind,
    ArtifactRecord,
    Capability,
    CapabilitySet,
    CapabilityUnavailableError,
    CapturedFrame,
    DebugRecord,
    Detection,
    DetectionRequest,
    DetectionResult,
    DeviceIdentity,
    DeviceInfo,
    FrameMetadata,
    InputActionKind,
    InputActionResult,
    InputStatus,
    KeyPressAction,
    LogLevel,
    LogRecord,
    NormalizedPoint,
    NormalizedRect,
    PixelFormat,
    Point,
    Rect,
    SessionInfo,
    Size,
    SwipeAction,
    TapAction,
    TextEntryAction,
    Viewport,
)


def test_capability_set_supports_and_requires() -> None:
    capabilities = CapabilitySet.from_iterable(
        [Capability.FRAME_CAPTURE, Capability.INPUT_TAP, Capability.INPUT_TAP]
    )

    assert capabilities.supports(Capability.FRAME_CAPTURE)
    assert Capability.INPUT_TAP in capabilities
    assert len(capabilities) == 2

    with pytest.raises(CapabilityUnavailableError):
        capabilities.require(Capability.INPUT_MULTI_TOUCH)


def test_collection_inputs_are_defensively_normalized() -> None:
    now = datetime.now(UTC)

    mutable_capabilities = {Capability.FRAME_CAPTURE}
    capability_set = CapabilitySet(values=mutable_capabilities)  # type: ignore[arg-type]
    mutable_capabilities.add(Capability.INPUT_TAP)

    mutable_labels = ["enemy"]
    request = DetectionRequest(labels=mutable_labels)  # type: ignore[arg-type]
    mutable_labels.append("coin")

    mutable_detections = [
        Detection(
            label="enemy",
            confidence=0.9,
            bounds=NormalizedRect(left=0.1, top=0.1, width=0.2, height=0.2),
        )
    ]
    result = DetectionResult(detections=mutable_detections, produced_at=now)  # type: ignore[arg-type]
    mutable_detections.append(
        Detection(
            label="coin",
            confidence=0.8,
            bounds=NormalizedRect(left=0.5, top=0.5, width=0.2, height=0.2),
        )
    )

    assert capability_set.values == frozenset({Capability.FRAME_CAPTURE})
    assert request.labels == ("enemy",)
    assert result.detections[0].label == "enemy"
    assert isinstance(request.labels, tuple)
    assert isinstance(result.detections, tuple)


def test_geometry_contracts_enforce_bounds() -> None:
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


def test_device_session_and_frame_models_have_value_semantics() -> None:
    now = datetime.now(UTC)
    source_metadata = {"model": "Pixel"}
    device = DeviceInfo(
        identity=DeviceIdentity(
            backend_name="adb",
            device_id="emulator-5554",
            display_name="Pixel",
        ),
        capabilities=CapabilitySet.from_iterable([Capability.FRAME_CAPTURE]),
        metadata=source_metadata,
    )
    session = SessionInfo(
        session_id="session-1",
        device=device,
        started_at=now,
        metadata={"run_id": "1"},
    )

    metadata = FrameMetadata(
        size=Size(width=1080, height=1920),
        captured_at=now,
        pixel_format=PixelFormat.RGBA32,
        frame_id="frame-1",
    )
    frame = CapturedFrame(data=b"\x89PNG", metadata=metadata)
    source_metadata["model"] = "Mutated"

    assert frame == CapturedFrame(data=b"\x89PNG", metadata=metadata)
    assert asdict(session)["device"]["identity"]["device_id"] == "emulator-5554"
    assert device.metadata["model"] == "Pixel"

    with pytest.raises(TypeError):
        device.metadata["model"] = "Override"  # type: ignore[index]

    with pytest.raises(ValueError):
        CapturedFrame(data=b"", metadata=metadata)


def test_input_actions_validate_and_expose_result_contract() -> None:
    now = datetime.now(UTC)
    tap = TapAction(point=NormalizedPoint(x=0.5, y=0.5), hold_ms=25)
    swipe = SwipeAction(start=Point(x=0, y=0), end=Point(x=10, y=10), duration_ms=150)
    key_press = KeyPressAction(key="BACK")
    text_entry = TextEntryAction(text="hello")
    result = InputActionResult(
        action_kind=InputActionKind.TAP,
        status=InputStatus.APPLIED,
        completed_at=now,
        message="ok",
    )

    assert tap.kind is InputActionKind.TAP
    assert swipe.kind is InputActionKind.SWIPE
    assert key_press.kind is InputActionKind.KEY_PRESS
    assert text_entry.kind is InputActionKind.TEXT_ENTRY
    assert result.status is InputStatus.APPLIED

    with pytest.raises(ValueError):
        SwipeAction(start=Point(x=0, y=0), end=Point(x=1, y=1), duration_ms=0)

    with pytest.raises(ValueError):
        KeyPressAction(key="")

    with pytest.raises(ValueError):
        TextEntryAction(text="")


def test_detection_artifact_and_log_records_validate_and_serialize() -> None:
    now = datetime.now(UTC)
    request = DetectionRequest(
        labels=("enemy", "coin"),
        min_confidence=0.5,
        max_results=5,
        region=Rect(left=10, top=20, width=30, height=40),
    )
    detection = Detection(
        label="enemy",
        confidence=0.92,
        bounds=NormalizedRect(left=0.1, top=0.1, width=0.2, height=0.2),
        attributes={"state": "alive"},
    )
    result = DetectionResult(
        detections=(detection,),
        produced_at=now,
        frame_id="frame-1",
        detector_name="template-matcher",
    )
    artifact = ArtifactRecord(
        artifact_id="artifact-1",
        kind=ArtifactKind.IMAGE,
        created_at=now,
        label="capture",
        metadata={"frame_id": "frame-1"},
    )
    log_record = LogRecord(timestamp=now, level=LogLevel.INFO, message="captured")
    debug_record = DebugRecord(
        timestamp=now,
        name="detection",
        fields={"attempt": 1, "threshold": 0.5},
    )

    assert request.max_results == 5
    assert request.region == Rect(left=10, top=20, width=30, height=40)
    assert asdict(result)["detections"][0]["label"] == "enemy"
    assert artifact.kind is ArtifactKind.IMAGE
    assert log_record.level is LogLevel.INFO
    assert debug_record.fields["attempt"] == 1

    with pytest.raises(TypeError):
        detection.attributes["state"] = "dead"  # type: ignore[index]

    with pytest.raises(TypeError):
        log_record.context["phase"] = "next"  # type: ignore[index]

    with pytest.raises(TypeError):
        debug_record.fields["attempt"] = 2  # type: ignore[index]

    with pytest.raises(TypeError):
        artifact.metadata["frame_id"] = "frame-2"  # type: ignore[index]

    with pytest.raises(ValueError):
        DetectionRequest(min_confidence=1.1)

    with pytest.raises(ValueError):
        Detection(label="enemy", confidence=-0.1)

    with pytest.raises(ValueError):
        ArtifactRecord(
            artifact_id="",
            kind=ArtifactKind.TEXT,
            created_at=now,
            label="invalid",
        )
