"""Lightweight async resilience primitives shared by backend services."""
from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import Any, Callable


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a circuit breaker rejects a call while open."""


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    name: str
    state: str
    failure_count: int
    failure_threshold: int
    recovery_timeout: float


class CircuitBreaker:
    """Small async circuit breaker with closed/open/half-open states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if recovery_timeout < 0:
            raise ValueError("recovery_timeout must be non-negative")

        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._clock = clock or time.monotonic
        self._state = self.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._state == self.OPEN and self._can_attempt_recovery():
            self._state = self.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def snapshot(self) -> CircuitBreakerSnapshot:
        return CircuitBreakerSnapshot(
            name=self.name,
            state=self.state,
            failure_count=self._failure_count,
            failure_threshold=self.failure_threshold,
            recovery_timeout=self.recovery_timeout,
        )

    def reset(self) -> None:
        self._state = self.CLOSED
        self._failure_count = 0
        self._opened_at = None

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self._state == self.OPEN:
            if self._can_attempt_recovery():
                self._state = self.HALF_OPEN
            else:
                raise CircuitBreakerOpenError(f"circuit breaker {self.name} is open")

        try:
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            self._record_failure()
            raise

        self._record_success()
        return result

    def _can_attempt_recovery(self) -> bool:
        return self._opened_at is not None and self._clock() - self._opened_at >= self.recovery_timeout

    def _record_success(self) -> None:
        self._state = self.CLOSED
        self._failure_count = 0
        self._opened_at = None

    def _record_failure(self) -> None:
        if self._state == self.HALF_OPEN:
            self._open()
            return

        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        self._state = self.OPEN
        self._opened_at = self._clock()
