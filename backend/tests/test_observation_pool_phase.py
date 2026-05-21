from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace


def row_with_chain(chain=None):
    return SimpleNamespace(evidence_chain_json=chain or [])


def recovery_row_with_chain(chain=None):
    return SimpleNamespace(strategy_id="snapshot_fast_recovery", evidence_chain_json=chain or [])


def bucket_row(bucket: str, score: float = 90):
    return SimpleNamespace(score=score, factor_snapshot_json={"observation_bucket": bucket})


class ObservationPoolPhaseTests(unittest.TestCase):
    def test_weekend_between_data_and_target_reports_weekend_base(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        result = scoring._pool_phase_metadata(
            data_date="2026-05-15",
            target_date="2026-05-18",
            pipeline_status="ok",
            rows=[row_with_chain()],
            now=datetime(2026, 5, 16, 10, 0),
        )

        self.assertEqual(result["pool_phase"], "weekend_base")
        self.assertIn("周末休市", result["pool_phase_message"])

    def test_target_day_with_news_impact_reports_final(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        result = scoring._pool_phase_metadata(
            data_date="2026-05-18",
            target_date="2026-05-19",
            pipeline_status="ok",
            rows=[row_with_chain([{"factor": "news_impact_agent"}])],
            now=datetime(2026, 5, 19, 7, 50),
        )

        self.assertEqual(result["pool_phase"], "final")
        self.assertEqual(result["news_enriched_count"], 1)

    def test_target_day_without_news_impact_reports_base_pending_news(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        result = scoring._pool_phase_metadata(
            data_date="2026-05-18",
            target_date="2026-05-19",
            pipeline_status="ok",
            rows=[row_with_chain()],
            now=datetime(2026, 5, 19, 8, 1),
        )

        self.assertEqual(result["pool_phase"], "base_pending_news")

    def test_recovery_pool_is_marked_for_review(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        result = scoring._pool_phase_metadata(
            data_date="2026-05-18",
            target_date="2026-05-19",
            pipeline_status="ok",
            rows=[recovery_row_with_chain([{"factor": "news_impact_agent"}])],
            now=datetime(2026, 5, 18, 20, 0),
        )

        self.assertEqual(result["pool_phase"], "recovery_enriched")
        self.assertTrue(result["pool_recovery"])
        self.assertEqual(result["pool_recovery_reason"], "snapshot_fast_recovery")
        self.assertEqual(result["news_enriched_count"], 1)

    def test_api_row_rebalance_keeps_non_trend_buckets_visible(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        rows = [bucket_row("trend_strength", 100 - i) for i in range(20)]
        rows += [bucket_row("pullback_support", 70 - i) for i in range(6)]
        rows += [bucket_row("oversold_reversal", 60 - i) for i in range(4)]

        result = scoring._rebalance_rows_by_observation_bucket(rows, 20)
        buckets = [row.factor_snapshot_json["observation_bucket"] for row in result]

        self.assertLessEqual(buckets.count("trend_strength"), 13)
        self.assertGreaterEqual(buckets.count("pullback_support"), 1)
        self.assertGreaterEqual(buckets.count("oversold_reversal"), 1)


if __name__ == "__main__":
    unittest.main()
