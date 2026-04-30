"""Small async runtime helpers for scenario orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any, TypeVar

T = TypeVar("T")

AsyncCallable = Callable[[], T | Awaitable[T]]
AsyncVerifier = Callable[[T], bool | Awaitable[bool]]
AsyncRecovery = Callable[["AttemptContext[T]"], Any | Awaitable[Any]]
Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class RuntimeScenarioError(Exception):
    """Base exception for runtime scenario helpers."""


class WaitTimeoutError(RuntimeScenarioError):
    """Raised when a polling wait does not complete before the timeout."""


class RetryExhaustedError(RuntimeScenarioError):
    """Raised when a retry policy cannot produce a verified result."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry configuration for a generic async operation."""

    max_attempts: int = 1
    delay_seconds: float = 0.0
    retry_exceptions: tuple[type[Exception], ...] = (Exception,)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.delay_seconds < 0:
            raise ValueError("delay_seconds must be non-negative")
        if not self.retry_exceptions:
            raise ValueError("retry_exceptions must not be empty")


@dataclass(frozen=True, slots=True)
class AttemptContext[T]:
    """State captured for a failed or unverified attempt."""

    attempt_number: int
    max_attempts: int
    result: T | None = None
    exception: Exception | None = None


class CooldownTracker:
    """Track named cooldown windows for scenario actions."""

    def __init__(self, *, now: Clock = monotonic, sleep: Sleep = asyncio.sleep) -> None:
        self._now = now
        self._sleep = sleep
        self._deadlines: dict[str, float] = {}

    def trigger(self, key: str, cooldown_seconds: float) -> None:
        """Start or refresh a cooldown window for a named action."""

        if not key.strip():
            raise ValueError("key must be non-empty")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        self._deadlines[key] = self._now() + cooldown_seconds

    def is_ready(self, key: str) -> bool:
        """Return whether the named action can run immediately."""

        return self.remaining(key) == 0.0

    def remaining(self, key: str) -> float:
        """Return remaining cooldown time in seconds."""

        deadline = self._deadlines.get(key)
        if deadline is None:
            return 0.0
        return max(0.0, deadline - self._now())

    async def wait(self, key: str) -> float:
        """Sleep until a named cooldown completes and return the waited time."""

        waited = 0.0
        while True:
            remaining = self.remaining(key)
            if remaining == 0:
                return waited
            await self._sleep(remaining)
            waited += remaining


async def wait_for[T](
    probe: AsyncCallable[T],
    *,
    timeout_seconds: float,
    interval_seconds: float = 0.1,
    is_complete: AsyncVerifier[T] | None = None,
    now: Clock = monotonic,
    sleep: Sleep = asyncio.sleep,
) -> T:
    """Poll until a result satisfies completion or the timeout expires."""

    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be non-negative")

    verifier = is_complete or _default_is_complete
    deadline = now() + timeout_seconds
    attempts = 0

    while True:
        attempts += 1
        result = await _maybe_await(probe())
        if await _maybe_await(verifier(result)):
            return result
        remaining = deadline - now()
        if remaining <= 0:
            raise WaitTimeoutError(
                f"wait timed out after {attempts} attempts and {timeout_seconds:.3f}s"
            )
        await sleep(min(interval_seconds, remaining))


async def run_with_retry[T](
    operation: AsyncCallable[T],
    *,
    policy: RetryPolicy | None = None,
    verify: AsyncVerifier[T] | None = None,
    recovery: AsyncRecovery[T] | None = None,
    sleep: Sleep = asyncio.sleep,
) -> T:
    """Run an operation until it succeeds, verifies, or exhausts retries."""

    retry_policy = policy or RetryPolicy()

    for attempt_number in range(1, retry_policy.max_attempts + 1):
        try:
            result = await _maybe_await(operation())
        except retry_policy.retry_exceptions as exc:
            context = AttemptContext[T](
                attempt_number=attempt_number,
                max_attempts=retry_policy.max_attempts,
                exception=exc,
            )
            if attempt_number >= retry_policy.max_attempts:
                raise RetryExhaustedError(
                    f"operation failed after {attempt_number} attempts"
                ) from exc
            await _run_recovery(recovery, context)
            await sleep(retry_policy.delay_seconds)
            continue

        if verify is None or await _maybe_await(verify(result)):
            return result

        context = AttemptContext[T](
            attempt_number=attempt_number,
            max_attempts=retry_policy.max_attempts,
            result=result,
        )
        if attempt_number >= retry_policy.max_attempts:
            raise RetryExhaustedError(
                f"verification failed after {attempt_number} attempts"
            )
        await _run_recovery(recovery, context)
        await sleep(retry_policy.delay_seconds)

    raise AssertionError("unreachable")


async def _run_recovery[T](
    recovery: AsyncRecovery[T] | None,
    context: AttemptContext[T],
) -> None:
    if recovery is None:
        return None
    await _maybe_await(recovery(context))


async def _maybe_await[T](value: T | Awaitable[T]) -> T:
    if isinstance(value, Awaitable):
        return await value
    return value


def _default_is_complete(value: object) -> bool:
    return bool(value)


__all__ = [
    "AttemptContext",
    "CooldownTracker",
    "RetryExhaustedError",
    "RetryPolicy",
    "RuntimeScenarioError",
    "WaitTimeoutError",
    "run_with_retry",
    "wait_for",
]
