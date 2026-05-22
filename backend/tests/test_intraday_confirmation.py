from __future__ import annotations

import unittest
from datetime import datetime

from backend.services.analysis_service.engine.intraday_confirmation import (
    confirm_recommendation,
    next_confirmation_target,
)


class IntradayConfirmationTests(unittest.TestCase):
    def test_next_confirmation_uses_first_pending_window(self) -> None:
        self.assertEqual(
            next_confirmation_target(datetime(2026, 5, 22, 9, 40)),
            datetime(2026, 5, 22, 9, 45),
        )

    def test_positive_supported_row_can_be_actionable(self) -> None:
        result = confirm_recommendation(
            {
                "symbol": "000001.SZ",
                "priority_score": 38,
                "observation_action": "回踩承接",
                "pool_optimizer": {"news": {"direction": "positive"}},
            },
            {
                "price": 10.2,
                "open": 10.0,
                "low": 9.95,
                "high": 10.3,
                "change": 0.2,
                "change_pct": 2.0,
                "data_quality": {"status": "ok", "is_fallback": False},
            },
            now=datetime(2026, 5, 22, 9, 45),
        )

        self.assertEqual(result["status"], "actionable")
        self.assertEqual(result["label"], "可关注")

    def test_negative_low_priority_row_stays_watch_only(self) -> None:
        result = confirm_recommendation(
            {
                "symbol": "000001.SZ",
                "priority_score": 12,
                "observation_action": "消息验证",
                "pool_optimizer": {"news": {"direction": "negative"}},
            },
            {
                "price": 10.2,
                "open": 10.0,
                "low": 9.95,
                "high": 10.3,
                "change": 0.2,
                "change_pct": 2.0,
                "data_quality": {"status": "ok", "is_fallback": False},
            },
            now=datetime(2026, 5, 22, 9, 45),
        )

        self.assertEqual(result["status"], "watch_only")
        self.assertEqual(result["risk_level"], "high")


if __name__ == "__main__":
    unittest.main()
