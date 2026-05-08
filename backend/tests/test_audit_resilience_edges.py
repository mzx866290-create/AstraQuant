from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from backend.shared import audit
from backend.shared.resilience import CircuitBreaker, CircuitBreakerOpenError


class AuditEdgeTests(unittest.TestCase):
    def test_client_ip_handles_missing_request_client_and_truncated_forwarded_chain(self) -> None:
        self.assertIsNone(audit.client_ip(None))
        self.assertIsNone(audit.client_ip(SimpleNamespace(headers={}, client=None)))

        first_hop = "2001:db8:" + "abcd:" * 12
        request = SimpleNamespace(
            headers={"x-forwarded-for": f" {first_hop}, 198.51.100.2, 203.0.113.8"},
            client=SimpleNamespace(host="127.0.0.1"),
        )

        self.assertEqual(audit.client_ip(request), first_hop[:45])
        self.assertEqual(len(audit.client_ip(request)), 45)

    def test_user_agent_handles_missing_request_header_and_truncates_long_values(self) -> None:
        self.assertIsNone(audit.user_agent(None))
        self.assertIsNone(audit.user_agent(SimpleNamespace(headers={}, client=None)))

        request = SimpleNamespace(headers={"user-agent": "A" * 1201}, client=None)

        self.assertEqual(audit.user_agent(request), "A" * 1000)

    def test_audit_log_infers_actor_user_id_and_records_request_metadata(self) -> None:
        db = SimpleNamespace(add=Mock())
        request = SimpleNamespace(
            headers={
                "x-forwarded-for": " 203.0.113.44, 198.51.100.7",
                "user-agent": "unit-agent",
            },
            client=SimpleNamespace(host="10.0.0.5"),
        )

        audit.audit_log(
            db,
            action="admin.updated.security.policy." * 3,
            actor=SimpleNamespace(id=321),
            request=request,
            target="stock:" + "600519" * 30,
        )

        row = db.add.call_args.args[0]
        self.assertEqual(row.user_id, 321)
        self.assertEqual(row.action, ("admin.updated.security.policy." * 3)[:50])
        self.assertEqual(row.target, ("stock:" + "600519" * 30)[:100])
        self.assertEqual(row.ip_address, "203.0.113.44")
        self.assertEqual(row.user_agent, "unit-agent")

    def test_audit_log_logs_anonymous_actions_without_adding_rows(self) -> None:
        db = SimpleNamespace(add=Mock())

        with self.assertLogs(audit.logger, level="INFO") as captured:
            audit.audit_log(db, action="anonymous-view", target="settings")

        db.add.assert_not_called()
        self.assertIn("anonymous audit action=anonymous-view", captured.output[0])

    def test_audit_log_swallows_db_add_errors(self) -> None:
        db = SimpleNamespace(add=Mock(side_effect=RuntimeError("db unavailable")))

        with self.assertLogs(audit.logger, level="WARNING") as captured:
            audit.audit_log(db, action="write-failure", user_id=99, target="admin-panel")

        db.add.assert_called_once()
        self.assertIn("audit log write failed", captured.output[0])
        self.assertIn("db unavailable", captured.output[0])


class CircuitBreakerEdgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_property_and_snapshot_refresh_open_breakers_after_timeout(self) -> None:
        now = 10.0
        breaker = CircuitBreaker(
            "refresh-state",
            failure_threshold=1,
            recovery_timeout=2.5,
            clock=lambda: now,
        )

        with self.assertRaisesRegex(RuntimeError, "down"):
            await breaker.call(Mock(side_effect=RuntimeError("down")))

        now = 12.49
        self.assertEqual(breaker.state, CircuitBreaker.OPEN)

        now = 12.5
        self.assertEqual(breaker.state, CircuitBreaker.HALF_OPEN)

        snapshot_breaker = CircuitBreaker(
            "refresh-snapshot",
            failure_threshold=1,
            recovery_timeout=1.0,
            clock=lambda: now,
        )
        with self.assertRaises(RuntimeError):
            await snapshot_breaker.call(Mock(side_effect=RuntimeError("down")))

        now = 13.5
        snapshot = snapshot_breaker.snapshot()

        self.assertEqual(snapshot.state, CircuitBreaker.HALF_OPEN)
        self.assertEqual(snapshot.failure_count, 1)

    async def test_open_breaker_rejects_before_recovery_window_without_calling_function(self) -> None:
        now = 100.0
        breaker = CircuitBreaker(
            "blocked",
            failure_threshold=1,
            recovery_timeout=10.0,
            clock=lambda: now,
        )

        with self.assertRaises(RuntimeError):
            await breaker.call(Mock(side_effect=RuntimeError("initial failure")))

        now = 109.99
        blocked = Mock(return_value="should not be called")

        with self.assertRaisesRegex(CircuitBreakerOpenError, "circuit breaker blocked is open"):
            await breaker.call(blocked)

        blocked.assert_not_called()
        self.assertEqual(breaker.state, CircuitBreaker.OPEN)

    async def test_sync_success_after_failures_resets_closed_and_half_open_breakers(self) -> None:
        closed_breaker = CircuitBreaker("closed-sync-reset", failure_threshold=3)

        with self.assertRaises(RuntimeError):
            await closed_breaker.call(Mock(side_effect=RuntimeError("soft failure")))

        self.assertEqual(closed_breaker.failure_count, 1)
        self.assertEqual(await closed_breaker.call(Mock(return_value="ok")), "ok")
        self.assertEqual(closed_breaker.state, CircuitBreaker.CLOSED)
        self.assertEqual(closed_breaker.failure_count, 0)

        now = 50.0
        half_open_breaker = CircuitBreaker(
            "half-open-sync-reset",
            failure_threshold=1,
            recovery_timeout=5.0,
            clock=lambda: now,
        )
        with self.assertRaises(RuntimeError):
            await half_open_breaker.call(Mock(side_effect=RuntimeError("down")))

        now = 55.0
        self.assertEqual(half_open_breaker.state, CircuitBreaker.HALF_OPEN)
        self.assertEqual(await half_open_breaker.call(Mock(return_value="recovered")), "recovered")
        self.assertEqual(half_open_breaker.state, CircuitBreaker.CLOSED)
        self.assertEqual(half_open_breaker.failure_count, 0)

    async def test_async_success_after_failures_resets_closed_and_half_open_breakers(self) -> None:
        closed_breaker = CircuitBreaker("closed-async-reset", failure_threshold=3)

        with self.assertRaises(RuntimeError):
            await closed_breaker.call(AsyncMock(side_effect=RuntimeError("soft failure")))

        self.assertEqual(closed_breaker.failure_count, 1)
        async_success = AsyncMock(return_value="async-ok")
        self.assertEqual(await closed_breaker.call(async_success), "async-ok")
        self.assertEqual(closed_breaker.state, CircuitBreaker.CLOSED)
        self.assertEqual(closed_breaker.failure_count, 0)
        async_success.assert_awaited_once_with()

        now = 70.0
        half_open_breaker = CircuitBreaker(
            "half-open-async-reset",
            failure_threshold=1,
            recovery_timeout=3.0,
            clock=lambda: now,
        )
        with self.assertRaises(RuntimeError):
            await half_open_breaker.call(AsyncMock(side_effect=RuntimeError("down")))

        now = 73.0
        self.assertEqual(half_open_breaker.state, CircuitBreaker.HALF_OPEN)
        half_open_success = AsyncMock(return_value="recovered")
        self.assertEqual(await half_open_breaker.call(half_open_success), "recovered")
        self.assertEqual(half_open_breaker.state, CircuitBreaker.CLOSED)
        self.assertEqual(half_open_breaker.failure_count, 0)
        half_open_success.assert_awaited_once_with()

    async def test_half_open_failure_reopens_and_starts_a_new_recovery_window(self) -> None:
        now = 200.0
        breaker = CircuitBreaker(
            "half-open-retry",
            failure_threshold=1,
            recovery_timeout=4.0,
            clock=lambda: now,
        )

        with self.assertRaises(RuntimeError):
            await breaker.call(Mock(side_effect=RuntimeError("down")))

        now = 204.0
        self.assertEqual(breaker.state, CircuitBreaker.HALF_OPEN)

        with self.assertRaisesRegex(RuntimeError, "still down"):
            await breaker.call(Mock(side_effect=RuntimeError("still down")))

        self.assertEqual(breaker.state, CircuitBreaker.OPEN)

        now = 207.99
        self.assertEqual(breaker.state, CircuitBreaker.OPEN)

        now = 208.0
        self.assertEqual(breaker.state, CircuitBreaker.HALF_OPEN)


if __name__ == "__main__":
    unittest.main()
