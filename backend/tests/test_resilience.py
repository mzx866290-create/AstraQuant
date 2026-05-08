from __future__ import annotations

import asyncio
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.shared.resilience import CircuitBreaker, CircuitBreakerOpenError


class CircuitBreakerTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_transitions_from_closed_to_open_to_half_open_to_closed(self) -> None:
        now = 100.0
        breaker = CircuitBreaker(
            "test",
            failure_threshold=2,
            recovery_timeout=5,
            clock=lambda: now,
        )

        async def fail() -> None:
            raise RuntimeError("down")

        with self.assertRaises(RuntimeError):
            await breaker.call(fail)
        self.assertEqual(breaker.state, CircuitBreaker.CLOSED)

        with self.assertRaises(RuntimeError):
            await breaker.call(fail)
        self.assertEqual(breaker.state, CircuitBreaker.OPEN)

        with self.assertRaises(CircuitBreakerOpenError):
            await breaker.call(AsyncMock())

        now = 106.0
        self.assertEqual(breaker.state, CircuitBreaker.HALF_OPEN)
        result = await breaker.call(AsyncMock(return_value="ok"))

        self.assertEqual(result, "ok")
        self.assertEqual(breaker.state, CircuitBreaker.CLOSED)
        self.assertEqual(breaker.failure_count, 0)

    async def test_half_open_failure_reopens(self) -> None:
        now = 100.0
        breaker = CircuitBreaker(
            "test",
            failure_threshold=1,
            recovery_timeout=5,
            clock=lambda: now,
        )

        with self.assertRaises(RuntimeError):
            await breaker.call(AsyncMock(side_effect=RuntimeError("down")))

        now = 106.0
        self.assertEqual(breaker.state, CircuitBreaker.HALF_OPEN)
        with self.assertRaises(RuntimeError):
            await breaker.call(AsyncMock(side_effect=RuntimeError("still down")))

        self.assertEqual(breaker.state, CircuitBreaker.OPEN)


class AlertsCircuitBreakerTests(unittest.TestCase):
    def test_check_one_alert_stops_calling_quote_after_circuit_opens(self) -> None:
        from backend.services.market_service.app.api.v1 import alerts

        alerts.quote_circuit_breaker.reset()
        alert = SimpleNamespace(id=1, alert_type="price_above", threshold=10)
        stock = SimpleNamespace(symbol="600519", market="SH", name="Test Stock")
        quote = AsyncMock(side_effect=RuntimeError("quote down"))

        with patch.object(alerts, "get_quote", quote):
            results = [asyncio.run(alerts._check_one_alert(alert, stock)) for _ in range(4)]

        self.assertEqual(quote.await_count, 3)
        self.assertEqual(results[-1]["status"], "degraded")
        self.assertEqual(results[-1]["reason"], "quote_circuit_open")
        alerts.quote_circuit_breaker.reset()


class ScoringCircuitBreakerTests(unittest.TestCase):
    def test_money_flow_circuit_open_does_not_instantiate_source(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        class BrokenMoneyFlowSource:
            instances = 0

            def __init__(self) -> None:
                self.__class__.instances += 1

            async def fetch_money_flow(self, symbol: str, limit: int = 20):
                raise RuntimeError("money flow down")

            async def close(self) -> None:
                pass

        fake_module = types.SimpleNamespace(EastMoneySource=BrokenMoneyFlowSource)
        scoring._money_flow_breaker.reset()

        with patch.dict(
            sys.modules,
            {"backend.services.data_crawler.sources.eastmoney_source": fake_module},
        ):
            results = [asyncio.run(scoring._fetch_money_flow("600519", 20)) for _ in range(4)]

        self.assertEqual(BrokenMoneyFlowSource.instances, 3)
        self.assertEqual(results[-1]["status"], "unavailable")
        self.assertIn("money_flow_circuit_open", results[-1]["warnings"])
        scoring._money_flow_breaker.reset()


if __name__ == "__main__":
    unittest.main()
