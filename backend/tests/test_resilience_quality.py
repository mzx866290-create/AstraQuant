from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock

from backend.shared.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerSnapshot,
)


class CircuitBreakerQualityTests(unittest.IsolatedAsyncioTestCase):
    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "failure_threshold must be positive"):
            CircuitBreaker("bad-threshold", failure_threshold=0)

        with self.assertRaisesRegex(ValueError, "failure_threshold must be positive"):
            CircuitBreaker("bad-threshold", failure_threshold=-1)

        with self.assertRaisesRegex(ValueError, "recovery_timeout must be non-negative"):
            CircuitBreaker("bad-timeout", recovery_timeout=-0.01)

    async def test_snapshot_reports_current_state_and_configuration(self) -> None:
        now = 10.0
        breaker = CircuitBreaker(
            "quotes",
            failure_threshold=2,
            recovery_timeout=3.5,
            clock=lambda: now,
        )

        with self.assertRaises(RuntimeError):
            await breaker.call(Mock(side_effect=RuntimeError("first failure")))

        self.assertEqual(
            breaker.snapshot(),
            CircuitBreakerSnapshot(
                name="quotes",
                state=CircuitBreaker.CLOSED,
                failure_count=1,
                failure_threshold=2,
                recovery_timeout=3.5,
            ),
        )

        with self.assertRaises(RuntimeError):
            await breaker.call(Mock(side_effect=RuntimeError("second failure")))

        now = 13.5
        self.assertEqual(
            breaker.snapshot(),
            CircuitBreakerSnapshot(
                name="quotes",
                state=CircuitBreaker.HALF_OPEN,
                failure_count=2,
                failure_threshold=2,
                recovery_timeout=3.5,
            ),
        )

    async def test_reset_clears_open_state_and_allows_calls_again(self) -> None:
        breaker = CircuitBreaker("resettable", failure_threshold=1, recovery_timeout=60)

        with self.assertRaises(RuntimeError):
            await breaker.call(Mock(side_effect=RuntimeError("down")))

        self.assertEqual(breaker.state, CircuitBreaker.OPEN)
        breaker.reset()

        self.assertEqual(breaker.state, CircuitBreaker.CLOSED)
        self.assertEqual(breaker.failure_count, 0)
        self.assertEqual(await breaker.call(Mock(return_value="recovered")), "recovered")

    async def test_state_moves_open_to_half_open_only_after_timeout(self) -> None:
        now = 100.0
        breaker = CircuitBreaker(
            "timer",
            failure_threshold=1,
            recovery_timeout=5,
            clock=lambda: now,
        )

        with self.assertRaises(RuntimeError):
            await breaker.call(Mock(side_effect=RuntimeError("down")))

        self.assertEqual(breaker.state, CircuitBreaker.OPEN)

        now = 104.99
        self.assertEqual(breaker.state, CircuitBreaker.OPEN)

        now = 105.0
        self.assertEqual(breaker.state, CircuitBreaker.HALF_OPEN)

    async def test_call_accepts_successful_sync_functions(self) -> None:
        sync_func = Mock(return_value={"ok": True})
        breaker = CircuitBreaker("sync-success")

        result = await breaker.call(sync_func, "600519", market="SH")

        self.assertEqual(result, {"ok": True})
        sync_func.assert_called_once_with("600519", market="SH")
        self.assertEqual(breaker.state, CircuitBreaker.CLOSED)
        self.assertEqual(breaker.failure_count, 0)

    async def test_call_records_sync_function_failures(self) -> None:
        sync_func = Mock(side_effect=RuntimeError("sync down"))
        breaker = CircuitBreaker("sync-failure", failure_threshold=2)

        with self.assertRaisesRegex(RuntimeError, "sync down"):
            await breaker.call(sync_func)

        self.assertEqual(breaker.state, CircuitBreaker.CLOSED)
        self.assertEqual(breaker.failure_count, 1)

        with self.assertRaisesRegex(RuntimeError, "sync down"):
            await breaker.call(sync_func)

        self.assertEqual(breaker.state, CircuitBreaker.OPEN)
        self.assertEqual(breaker.failure_count, 2)

    async def test_call_accepts_successful_async_functions(self) -> None:
        async_func = AsyncMock(return_value="async-ok")
        breaker = CircuitBreaker("async-success")

        result = await breaker.call(async_func, 1, mode="fast")

        self.assertEqual(result, "async-ok")
        async_func.assert_awaited_once_with(1, mode="fast")
        self.assertEqual(breaker.state, CircuitBreaker.CLOSED)
        self.assertEqual(breaker.failure_count, 0)

    async def test_call_records_async_function_failures(self) -> None:
        async_func = AsyncMock(side_effect=RuntimeError("async down"))
        breaker = CircuitBreaker("async-failure", failure_threshold=1)

        with self.assertRaisesRegex(RuntimeError, "async down"):
            await breaker.call(async_func)

        async_func.assert_awaited_once_with()
        self.assertEqual(breaker.state, CircuitBreaker.OPEN)
        self.assertEqual(breaker.failure_count, 1)

    async def test_call_rejects_without_invoking_function_while_open(self) -> None:
        now = 20.0
        breaker = CircuitBreaker(
            "open-reject",
            failure_threshold=1,
            recovery_timeout=10,
            clock=lambda: now,
        )

        with self.assertRaises(RuntimeError):
            await breaker.call(Mock(side_effect=RuntimeError("down")))

        blocked = Mock(return_value="should not run")
        with self.assertRaisesRegex(CircuitBreakerOpenError, "circuit breaker open-reject is open"):
            await breaker.call(blocked)

        blocked.assert_not_called()
        self.assertEqual(breaker.state, CircuitBreaker.OPEN)

    async def test_half_open_failure_reopens_breaker(self) -> None:
        now = 50.0
        breaker = CircuitBreaker(
            "half-open",
            failure_threshold=1,
            recovery_timeout=2,
            clock=lambda: now,
        )

        with self.assertRaises(RuntimeError):
            await breaker.call(Mock(side_effect=RuntimeError("down")))

        now = 52.0
        self.assertEqual(breaker.state, CircuitBreaker.HALF_OPEN)

        with self.assertRaisesRegex(RuntimeError, "still down"):
            await breaker.call(Mock(side_effect=RuntimeError("still down")))

        self.assertEqual(breaker.state, CircuitBreaker.OPEN)
        self.assertEqual(breaker.failure_count, 1)

    async def test_call_awaits_awaitable_returned_by_sync_function(self) -> None:
        breaker = CircuitBreaker("awaitable-result")

        async def compute() -> str:
            return "awaited"

        producer = Mock(side_effect=lambda: compute())

        result = await breaker.call(producer)

        self.assertEqual(result, "awaited")
        producer.assert_called_once_with()
        self.assertEqual(breaker.state, CircuitBreaker.CLOSED)
        self.assertEqual(breaker.failure_count, 0)


if __name__ == "__main__":
    unittest.main()
