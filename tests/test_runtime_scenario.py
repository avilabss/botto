"""Tests for runtime scenario orchestration helpers."""

from __future__ import annotations

import asyncio

import pytest
from android_game_automator.runtime import (
    AttemptContext,
    CooldownTracker,
    RetryExhaustedError,
    RetryPolicy,
    WaitTimeoutError,
    run_with_retry,
    wait_for,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    async def sleep(self, delay: float) -> None:
        self.value += delay


def test_wait_for_raises_timeout_when_probe_never_completes() -> None:
    clock = FakeClock()
    attempts = 0

    async def probe() -> bool:
        nonlocal attempts
        attempts += 1
        return False

    with pytest.raises(WaitTimeoutError):
        asyncio.run(
            wait_for(
                probe,
                timeout_seconds=0.2,
                interval_seconds=0.1,
                now=clock.now,
                sleep=clock.sleep,
            )
        )

    assert attempts == 3


def test_wait_for_does_not_sleep_past_timeout_deadline() -> None:
    clock = FakeClock()
    attempts = 0

    async def probe() -> bool:
        nonlocal attempts
        attempts += 1
        return False

    with pytest.raises(WaitTimeoutError):
        asyncio.run(
            wait_for(
                probe,
                timeout_seconds=0.2,
                interval_seconds=1.0,
                now=clock.now,
                sleep=clock.sleep,
            )
        )

    assert attempts == 2
    assert clock.value == pytest.approx(0.2)


def test_run_with_retry_returns_after_transient_failures() -> None:
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("temporary")
        return "ok"

    result = asyncio.run(
        run_with_retry(operation, policy=RetryPolicy(max_attempts=3, delay_seconds=0.0))
    )

    assert result == "ok"
    assert attempts == 3


def test_run_with_retry_raises_when_attempts_are_exhausted() -> None:
    async def operation() -> str:
        raise RuntimeError("still broken")

    with pytest.raises(RetryExhaustedError) as exc_info:
        asyncio.run(
            run_with_retry(operation, policy=RetryPolicy(max_attempts=2, delay_seconds=0.0))
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_run_with_retry_retries_until_result_verifies() -> None:
    values = iter(["bad", "good"])

    async def operation() -> str:
        return next(values)

    async def verify(result: str) -> bool:
        return result == "good"

    result = asyncio.run(
        run_with_retry(
            operation,
            policy=RetryPolicy(max_attempts=2, delay_seconds=0.0),
            verify=verify,
        )
    )

    assert result == "good"


def test_cooldown_tracker_enforces_wait_until_ready() -> None:
    clock = FakeClock()
    tracker = CooldownTracker(now=clock.now, sleep=clock.sleep)

    tracker.trigger("tap", 1.5)

    assert not tracker.is_ready("tap")
    assert tracker.remaining("tap") == pytest.approx(1.5)

    waited = asyncio.run(tracker.wait("tap"))

    assert waited == pytest.approx(1.5)
    assert tracker.is_ready("tap")
    assert tracker.remaining("tap") == pytest.approx(0.0)


def test_cooldown_tracker_wait_rechecks_when_cooldown_is_retriggered() -> None:
    clock = FakeClock()
    sleep_calls = 0
    tracker: CooldownTracker | None = None

    async def sleep(delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        clock.value += delay
        if sleep_calls == 1:
            assert tracker is not None
            tracker.trigger("tap", 0.5)

    tracker = CooldownTracker(now=clock.now, sleep=sleep)
    tracker.trigger("tap", 1.0)

    waited = asyncio.run(tracker.wait("tap"))

    assert waited == pytest.approx(1.5)
    assert sleep_calls == 2
    assert tracker.is_ready("tap")
    assert tracker.remaining("tap") == pytest.approx(0.0)


def test_run_with_retry_invokes_recovery_for_unverified_attempts() -> None:
    values = iter(["bad", "good"])
    recoveries: list[AttemptContext[str]] = []

    async def operation() -> str:
        return next(values)

    async def verify(result: str) -> bool:
        return result == "good"

    async def recovery(context: AttemptContext[str]) -> None:
        recoveries.append(context)

    result = asyncio.run(
        run_with_retry(
            operation,
            policy=RetryPolicy(max_attempts=2, delay_seconds=0.0),
            verify=verify,
            recovery=recovery,
        )
    )

    assert result == "good"
    assert len(recoveries) == 1
    assert recoveries[0].attempt_number == 1
    assert recoveries[0].result == "bad"
    assert recoveries[0].exception is None
