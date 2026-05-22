from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.services.analysis_service.engine.observation_pool_optimizer import optimize_observation_pool


def base_rec(symbol: str, **overrides):
    payload = {
        "symbol": symbol,
        "name": symbol,
        "score": 82,
        "tier": "A",
        "priority_score": 60,
        "observation_action": "放量突破",
        "observation_bucket": "trend_strength",
        "industry_name": "电子",
        "evidence_chain": [],
    }
    payload.update(overrides)
    return payload


def news_item(direction: str, *, generated_at: datetime, relevance: str = "high", confidence: str = "high") -> dict:
    return {
        "factor": "news_impact_agent",
        "direction": direction,
        "confidence": confidence,
        "impact": 5 if direction == "positive" else -5,
        "generated_at": generated_at.isoformat(),
        "value": {
            "direction": direction,
            "relevance": relevance,
            "confidence": confidence,
            "summary": "unit news",
        },
    }


class ObservationPoolOptimizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 5, 21, 8, 0, tzinfo=timezone.utc)

    def test_strong_negative_news_cannot_remain_a_tier(self) -> None:
        recs = [
            base_rec(
                "000001.SZ",
                evidence_chain=[news_item("negative", generated_at=self.now - timedelta(hours=4))],
            )
        ]

        optimized, summary = optimize_observation_pool(
            recs,
            {"regime": "range_bound", "confidence": "medium"},
            now=self.now,
            mode="preopen",
        )

        self.assertEqual(optimized[0]["tier"], "B")
        self.assertEqual(optimized[0]["observation_action"], "消息验证")
        self.assertLess(optimized[0]["priority_score"], 60)
        self.assertEqual(summary["news_quality"]["negative"], 1)

    def test_stale_positive_news_loses_priority_instead_of_boosting(self) -> None:
        recs = [
            base_rec(
                "000002.SZ",
                evidence_chain=[news_item("positive", generated_at=self.now - timedelta(hours=80))],
                priority_score=50,
            )
        ]

        optimized, summary = optimize_observation_pool(
            recs,
            {"regime": "range_bound", "confidence": "medium"},
            now=self.now,
            mode="preopen",
        )

        self.assertLess(optimized[0]["priority_score"], 50)
        self.assertEqual(optimized[0]["observation_action"], "消息验证")
        self.assertEqual(summary["news_quality"]["stale"], 1)

    def test_weak_market_downgrades_breakout_chase_style(self) -> None:
        recs = [
            base_rec("000003.SZ", change_pct=6.2, priority_score=70),
        ]

        optimized, _ = optimize_observation_pool(
            recs,
            {"regime": "weak_market", "confidence": "high"},
            now=self.now,
            mode="base",
        )

        self.assertEqual(optimized[0]["tier"], "B")
        self.assertEqual(optimized[0]["observation_action"], "只看不追")
        self.assertLess(optimized[0]["priority_score"], 70)

    def test_industry_concentration_applies_penalty_after_cap(self) -> None:
        recs = [
            base_rec(f"00000{i}.SZ", industry_name="半导体", priority_score=80 - i)
            for i in range(6)
        ]

        with patch.dict(os.environ, {"OBS_POOL_MAX_PER_INDUSTRY": "2"}):
            optimized, summary = optimize_observation_pool(
                recs,
                {"regime": "range_bound", "confidence": "medium"},
                now=self.now,
                mode="base",
            )

        penalized = [rec for rec in optimized if rec.get("diversification_penalty")]
        self.assertGreaterEqual(len(penalized), 4)
        self.assertEqual(summary["diversification"]["industry_cap"], 2)
        self.assertGreaterEqual(summary["diversification"]["penalties_applied"], 4)

    def test_empty_input_returns_stable_summary(self) -> None:
        optimized, summary = optimize_observation_pool([], {"regime": "range_bound"}, now=self.now)

        self.assertEqual(optimized, [])
        self.assertEqual(summary["status"], "empty")
        self.assertEqual(summary["processed"], 0)


if __name__ == "__main__":
    unittest.main()
