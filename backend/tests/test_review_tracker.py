from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.analysis_service.engine import review_tracker


class _FakeQuery:
    def __init__(self, session, model) -> None:
        self.session = session
        self.model = model
        self.filters = []
        self.limit_value = None

    def filter(self, *clauses):
        self.filters.extend(clauses)
        return self

    def first(self):
        if self.model.__name__ == "WeightSuggestionAudit":
            return self.session.audit_by_id
        if self.model.__name__ == "StrategyWeightPatchProposal":
            return self.session.proposal_by_id
        if self.model.__name__ == "StrategyWeightVersion":
            return self.session.version_by_id
        if self.model.__name__ == "ResearchObservation":
            if any("id" in str(clause) for clause in self.filters):
                return self.session.observation_by_id
        if self.model.__name__ == "DailySnapshot":
            return self.session.snapshot_first
        return None

    def order_by(self, *_clauses):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        if self.model.__name__ == "WeightSuggestionAudit":
            rows = list(self.session.audit_rows)
            if self.limit_value is not None:
                return rows[: self.limit_value]
            return rows
        if self.model.__name__ == "StrategyWeightPatchProposal":
            rows = list(self.session.proposal_rows)
            if self.limit_value is not None:
                return rows[: self.limit_value]
            return rows
        if self.model.__name__ == "StrategyWeightVersion":
            rows = list(self.session.version_rows)
            if self.limit_value is not None:
                return rows[: self.limit_value]
            return rows
        if self.model.__name__ == "ObservationReview":
            return list(self.session.review_rows)
        if self.model.__name__ == "DailySnapshot":
            return list(self.session.snapshot_rows)
        if self.model.__name__ == "PipelineRunLog":
            return list(self.session.run_log_rows)
        if self.model.__name__ == "ResearchObservation":
            return list(self.session.rows)
        return list(self.session.rows)


class _FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.rows = []
        self.review_rows = []
        self.snapshot_rows = []
        self.run_log_rows = []
        self.audit_rows = []
        self.proposal_rows = []
        self.version_rows = []
        self.observation_by_id = None
        self.snapshot_first = None
        self.audit_by_id = None
        self.proposal_by_id = None
        self.version_by_id = None
        self.committed = False
        self.closed = False

    def query(self, model):
        return _FakeQuery(self, model)

    def add(self, item):
        if getattr(item, "id", None) is None:
            item.id = 101
        self.added.append(item)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class ReviewTrackerTests(unittest.TestCase):
    def test_build_factor_snapshot_merges_existing_factor_sources(self) -> None:
        snapshot = review_tracker.build_factor_snapshot(
            {
                "score_breakdown": [
                    {"key": "base", "label": "Base", "delta": 50},
                    {"key": "valuation", "label": "Valuation", "delta": 4},
                ],
                "evidence_chain": [
                    {
                        "factor": "valuation",
                        "dimension": "valuation",
                        "label": "Valuation",
                        "impact": 1.5,
                        "direction": "positive",
                        "confidence": "medium",
                    }
                ],
                "strategy_weighted_factors": [
                    {
                        "factor": "valuation",
                        "dimension": "valuation",
                        "label": "Valuation",
                        "weighted_delta": 2.0,
                        "weight": 0.25,
                    }
                ],
            }
        )

        self.assertEqual(len(snapshot), 1)
        row = snapshot[0]
        self.assertEqual(row["factor"], "valuation")
        self.assertEqual(row["sources"], ["evidence_chain", "score_breakdown", "strategy_weighted"])
        self.assertEqual(row["score_delta"], 4.0)
        self.assertEqual(row["evidence_impact"], 1.5)
        self.assertEqual(row["weighted_delta"], 2.0)
        self.assertEqual(row["weight"], 0.25)
        self.assertEqual(row["direction"], "positive")

    def test_save_observation_snapshots_persists_recommendation_research_fields(self) -> None:
        session = _FakeSession()
        recommendations = [
            {
                "symbol": "000001.SZ",
                "strategy_id": "retail_small",
                "score": 72,
                "price": 18.5,
                "score_breakdown": [{"key": "valuation", "delta": 2}],
                "evidence_chain": [{"factor": "valuation", "impact": 1}],
                "strategy_weighted_factors": [{"factor": "valuation", "dimension": "valuation", "weighted_delta": 1.5, "weight": 0.2}],
                "bull_case": [{"argument": "估值合理"}],
                "bear_case": [{"argument": "现金流偏弱"}],
                "key_disagreement": [{"topic": "成长"}],
                "falsification": [{"condition": "利润转负"}],
                "veto_result": {"passed": True},
            }
        ]

        with patch.object(review_tracker, "SessionLocal", return_value=session), patch.object(
            review_tracker, "_has_table", return_value=True
        ):
            saved = review_tracker.save_observation_snapshots(date(2026, 5, 9), "range_bound", recommendations)

        self.assertEqual(saved, 1)
        self.assertTrue(session.committed)
        self.assertEqual(len(session.added), 1)
        row = session.added[0]
        self.assertEqual(row.symbol, "000001.SZ")
        self.assertEqual(row.strategy_id, "retail_small")
        self.assertEqual(row.regime, "range_bound")
        self.assertEqual(row.evidence_chain_json, [{"factor": "valuation", "impact": 1}])
        self.assertIsInstance(row.factor_snapshot_json, dict)
        factors = row.factor_snapshot_json["factors"]
        self.assertEqual(factors[0]["factor"], "valuation")
        self.assertEqual(factors[0]["weighted_delta"], 1.5)

    def test_run_pending_reviews_creates_review_rows_from_pending_observations(self) -> None:
        session = _FakeSession()
        observation = type(
            "Observation",
            (),
            {
                "id": 7,
                "symbol": "000001.SZ",
                "strategy_id": "retail_small",
                "snapshot_date": datetime(2026, 5, 9, tzinfo=timezone.utc),
                "close_price": 10.0,
                "veto_result_json": {"warnings": [{"detail": "soft risk"}]},
            },
        )()
        session.observation_by_id = observation
        # Reproducible path: review price comes from the review-day DailySnapshot close.
        session.snapshot_first = type("DailySnapshot", (), {"trade_date": "2026-05-10", "symbol": "000001.SZ", "close": 9.0})()
        session.snapshot_rows = [
            type("DailySnapshot", (), {"trade_date": "2026-05-09", "symbol": "000001.SZ", "low": 9.7, "close": 10.0})(),
            type("DailySnapshot", (), {"trade_date": "2026-05-10", "symbol": "000001.SZ", "low": 8.8, "close": 9.0})(),
        ]

        # fetch_quote returns a different price to prove the historical close wins.
        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "list_pending_reviews", return_value=[{"observation_id": 7, "symbol": "000001.SZ", "review_offset": "T+1"}]
        ), patch.object(review_tracker, "SessionLocal", return_value=session), patch.object(
            review_tracker, "fetch_quote", AsyncMock(return_value={"price": 99.0, "source": "unit-quote"})
        ):
            result = asyncio.run(review_tracker.run_pending_reviews(date(2026, 5, 10), offsets=("T+1",)))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["items"][0]["price_source"], "daily_snapshot")
        self.assertEqual(len(session.added), 1)
        review = session.added[0]
        self.assertEqual(review.observation_id, 7)
        self.assertEqual(review.close_price, 9.0)
        self.assertEqual(review.return_pct, -10.0)
        self.assertEqual(review.max_drawdown_pct, -12.0)
        self.assertTrue(review.falsification_triggered)
        self.assertTrue(review.risk_signal_valid)
        self.assertIn("price_source=daily_snapshot", review.notes)

    def test_run_pending_reviews_falls_back_to_realtime_quote_when_no_bar(self) -> None:
        session = _FakeSession()
        observation = type(
            "Observation",
            (),
            {
                "id": 7,
                "symbol": "000001.SZ",
                "strategy_id": "retail_small",
                "snapshot_date": datetime(2026, 5, 9, tzinfo=timezone.utc),
                "close_price": 10.0,
                "veto_result_json": {},
            },
        )()
        session.observation_by_id = observation
        # No DailySnapshot bar for the review day -> snapshot_first stays None.
        session.snapshot_first = None
        session.snapshot_rows = []

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "list_pending_reviews", return_value=[{"observation_id": 7, "symbol": "000001.SZ", "review_offset": "T+1"}]
        ), patch.object(review_tracker, "SessionLocal", return_value=session), patch.object(
            review_tracker, "fetch_quote", AsyncMock(return_value={"price": 11.0, "source": "unit-quote"})
        ):
            result = asyncio.run(review_tracker.run_pending_reviews(date(2026, 5, 10), offsets=("T+1",)))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["items"][0]["price_source"], "realtime_quote_fallback")
        review = session.added[0]
        self.assertEqual(review.close_price, 11.0)
        self.assertEqual(review.return_pct, 10.0)
        self.assertIn("price_source=realtime_quote_fallback", review.notes)
        self.assertIn("unit-quote", review.notes)

    def test_build_review_report_groups_by_strategy(self) -> None:
        session = _FakeSession()
        observation = type(
            "Observation",
            (),
            {
                "id": 7,
                "symbol": "000001.SZ",
                "strategy_id": "retail_small",
                "snapshot_date": datetime(2026, 5, 9, tzinfo=timezone.utc),
            },
        )()
        review = type(
            "Review",
            (),
            {
                "observation_id": 7,
                "review_offset": "T+1",
                "return_pct": 5.0,
                "falsification_triggered": False,
                "risk_signal_valid": False,
            },
        )()
        session.rows = [observation]
        session.review_rows = [review]

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            report = review_tracker.build_review_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["reviews"], 1)
        self.assertEqual(report["summary"]["evaluated_reviews"], 1)
        self.assertEqual(report["summary"]["positive_reviews"], 1)
        self.assertEqual(report["summary"]["win_rate"], 1.0)
        self.assertEqual(report["by_strategy"][0]["strategy_id"], "retail_small")
        self.assertEqual(report["by_strategy"][0]["win_rate"], 1.0)
        self.assertEqual(report["by_offset"][0]["review_offset"], "T+1")
        self.assertEqual(report["by_offset"][0]["win_rate"], 1.0)

    def test_build_review_report_breaks_down_by_tier_with_evaluated_denominator(self) -> None:
        session = _FakeSession()
        observation_a = type(
            "Observation",
            (),
            {
                "id": 1,
                "symbol": "000001.SZ",
                "strategy_id": "trend_momentum",
                "snapshot_date": datetime(2026, 5, 9, tzinfo=timezone.utc),
                "factor_snapshot_json": {"tier": "A"},
            },
        )()
        observation_a2 = type(
            "Observation",
            (),
            {
                "id": 2,
                "symbol": "000002.SZ",
                "strategy_id": "trend_momentum",
                "snapshot_date": datetime(2026, 5, 9, tzinfo=timezone.utc),
                "factor_snapshot_json": {"tier": "A"},
            },
        )()
        observation_c = type(
            "Observation",
            (),
            {
                "id": 3,
                "symbol": "000003.SZ",
                "strategy_id": "trend_momentum",
                "snapshot_date": datetime(2026, 5, 9, tzinfo=timezone.utc),
                "factor_snapshot_json": None,
            },
        )()
        # A: one positive, one with no return_pct (must be excluded from denominator)
        review_a = type("Review", (), {"observation_id": 1, "review_offset": "T+5", "return_pct": 6.0, "falsification_triggered": False, "risk_signal_valid": False})()
        review_a2 = type("Review", (), {"observation_id": 2, "review_offset": "T+5", "return_pct": None, "falsification_triggered": False, "risk_signal_valid": False})()
        # C: one negative
        review_c = type("Review", (), {"observation_id": 3, "review_offset": "T+5", "return_pct": -4.0, "falsification_triggered": True, "risk_signal_valid": False})()
        session.rows = [observation_a, observation_a2, observation_c]
        session.review_rows = [review_a, review_a2, review_c]

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            report = review_tracker.build_review_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["tiers"], 2)
        by_tier = {row["tier"]: row for row in report["by_tier"]}
        # Tier A appears first (ordering), defaults applied for missing snapshot -> C
        self.assertEqual([row["tier"] for row in report["by_tier"]], ["A", "C"])
        # A tier: 2 reviews but only 1 evaluated -> win_rate divides by evaluated, not reviews
        self.assertEqual(by_tier["A"]["reviews"], 2)
        self.assertEqual(by_tier["A"]["evaluated_reviews"], 1)
        self.assertEqual(by_tier["A"]["win_rate"], 1.0)
        self.assertEqual(by_tier["A"]["avg_return_pct"], 6.0)
        # C tier: missing factor_snapshot defaults to C
        self.assertEqual(by_tier["C"]["reviews"], 1)
        self.assertEqual(by_tier["C"]["win_rate"], 0.0)
        self.assertEqual(by_tier["C"]["avg_return_pct"], -4.0)
        self.assertEqual(by_tier["C"]["falsification_triggered"], 1)

    def test_build_data_foundation_health_reports_gaps_and_price_sources(self) -> None:
        session = _FakeSession()
        # 2026-05-29 is a Friday; window covers a few weekdays before it.
        session.run_log_rows = [
            type("PipelineRunLog", (), {"run_date": "2026-05-26", "status": "success"})(),
            type("PipelineRunLog", (), {"run_date": "2026-05-27", "status": "success"})(),
            # 2026-05-28 missing entirely
            type("PipelineRunLog", (), {"run_date": "2026-05-29", "status": "failed"})(),
        ]
        session.rows = [
            type("Observation", (), {"snapshot_date": datetime(2026, 5, 26, tzinfo=timezone.utc)})(),
            type("Observation", (), {"snapshot_date": datetime(2026, 5, 26, tzinfo=timezone.utc)})(),
            type("Observation", (), {"snapshot_date": datetime(2026, 5, 27, tzinfo=timezone.utc)})(),
        ]
        session.review_rows = [
            type("Review", (), {"notes": "price_source=daily_snapshot source=daily_snapshot"})(),
            type("Review", (), {"notes": "price_source=daily_snapshot source=daily_snapshot"})(),
            type("Review", (), {"notes": "price_source=realtime_quote_fallback source=realtime_quote:em"})(),
            type("Review", (), {"notes": "source=tencent"})(),  # legacy row
        ]

        class _FixedDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 5, 29)

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ), patch.object(review_tracker, "date", _FixedDate):
            health = review_tracker.build_data_foundation_health(lookback_days=10)

        self.assertEqual(health["status"], "degraded")
        cont = health["run_continuity"]
        self.assertIn("2026-05-28", cont["missing_days"])
        self.assertEqual(cont["failed_day_count"], 1)
        self.assertEqual(cont["successful_runs"], 2)
        obs = health["observation_accumulation"]
        self.assertEqual(obs["observations"], 3)
        self.assertEqual(obs["observation_days"], 2)
        price = health["price_source_quality"]
        self.assertEqual(price["reviews"], 4)
        self.assertEqual(price["by_source"]["daily_snapshot"], 2)
        self.assertEqual(price["by_source"]["realtime_quote_fallback"], 1)
        self.assertEqual(price["by_source"]["legacy_unknown"], 1)
        self.assertEqual(price["reproducible_rate"], 0.5)
        self.assertTrue(health["issues"])

    def test_build_data_foundation_health_reports_missing_tables(self) -> None:
        with patch.object(review_tracker, "_has_table", return_value=False):
            health = review_tracker.build_data_foundation_health()
        self.assertEqual(health["status"], "tables_missing")
        self.assertFalse(health["tables"]["pipeline_run_logs"])

    def test_build_review_readiness_reports_pending_state(self) -> None:
        session = _FakeSession()
        observation = type(
            "Observation",
            (),
            {
                "id": 7,
                "symbol": "000001.SZ",
                "strategy_id": "retail_small",
                "snapshot_date": datetime(2026, 5, 10, tzinfo=timezone.utc),
                "close_price": 10.0,
            },
        )()
        session.rows = [observation]
        session.review_rows = []

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            readiness = review_tracker.build_review_readiness(date(2026, 5, 11), offsets=("T+1",))

        self.assertEqual(readiness["status"], "pending_reviews")
        self.assertEqual(readiness["summary"]["observations"], 1)
        self.assertEqual(readiness["summary"]["pending_reviews"], 1)
        self.assertEqual(readiness["latest_snapshot_date"], "2026-05-10")
        self.assertEqual(readiness["pending_reviews"][0]["symbol"], "000001.SZ")

    def test_build_review_readiness_reports_missing_tables(self) -> None:
        with patch.object(review_tracker, "_has_table", return_value=False):
            readiness = review_tracker.build_review_readiness(date(2026, 5, 11), offsets=("T+1",))

        self.assertEqual(readiness["status"], "tables_missing")
        self.assertFalse(readiness["tables"]["research_observations"])
        self.assertEqual(readiness["summary"]["observations"], 0)

    def test_build_factor_review_report_aggregates_evidence_factor_attribution(self) -> None:
        session = _FakeSession()
        observation_a = type(
            "Observation",
            (),
            {
                "id": 7,
                "symbol": "000001.SZ",
                "strategy_id": "retail_small",
                "snapshot_date": datetime(2026, 5, 9, tzinfo=timezone.utc),
                "regime": "range_bound",
                "evidence_chain_json": [
                    {"factor": "valuation", "label": "Valuation", "impact": "1.5"},
                    {"dimension": "risk", "label": "Risk", "impact": "-0.5"},
                ],
            },
        )()
        observation_b = type(
            "Observation",
            (),
            {
                "id": 8,
                "symbol": "000002.SZ",
                "strategy_id": "retail_small",
                "snapshot_date": datetime(2026, 5, 10, tzinfo=timezone.utc),
                "regime": "weak_market",
                "evidence_chain_json": [
                    {"factor": "valuation", "label": "Valuation", "impact": "bad"},
                ],
            },
        )()
        observation_c = type(
            "Observation",
            (),
            {
                "id": 9,
                "symbol": "000003.SZ",
                "strategy_id": "retail_small",
                "snapshot_date": datetime(2026, 5, 11, tzinfo=timezone.utc),
                "regime": "strong_trend",
                "evidence_chain_json": [{"factor": "valuation", "label": "Valuation", "impact": 9}],
            },
        )()
        review_a = type(
            "Review",
            (),
            {
                "observation_id": 7,
                "return_pct": 10.0,
                "max_drawdown_pct": -3.0,
                "falsification_triggered": False,
                "risk_signal_valid": True,
            },
        )()
        review_b = type(
            "Review",
            (),
            {
                "observation_id": 8,
                "return_pct": -5.0,
                "max_drawdown_pct": -8.0,
                "falsification_triggered": True,
                "risk_signal_valid": False,
            },
        )()
        review_c = type(
            "Review",
            (),
            {
                "observation_id": 9,
                "return_pct": 20.0,
                "max_drawdown_pct": -1.0,
                "falsification_triggered": False,
                "risk_signal_valid": False,
            },
        )()
        session.rows = [observation_a, observation_b, observation_c]
        session.review_rows = [review_a, review_b, review_c]

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            report = review_tracker.build_factor_review_report(
                snapshot_from=date(2026, 5, 9),
                snapshot_to=date(2026, 5, 10),
            )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"], {"factors": 2, "reviews": 2, "regime_factors": 3, "baseline_win_rate": 0.5, "baseline_evaluated_reviews": 2})
        valuation = report["by_factor"][0]
        self.assertEqual(valuation["factor"], "valuation")
        self.assertEqual(valuation["label"], "Valuation")
        self.assertEqual(valuation["reviews"], 2)
        self.assertEqual(valuation["positive_reviews"], 1)
        self.assertEqual(valuation["win_rate"], 0.5)
        self.assertEqual(valuation["avg_return_pct"], 2.5)
        self.assertEqual(valuation["max_drawdown_pct"], -8.0)
        self.assertEqual(valuation["worst_return_pct"], -5.0)
        self.assertEqual(valuation["coverage_rate"], 1.0)
        # baseline win rate is 0.5; valuation also 0.5 -> zero lift + full coverage = confounded
        self.assertEqual(valuation["baseline_win_rate"], 0.5)
        self.assertEqual(valuation["win_rate_lift"], 0.0)
        self.assertTrue(valuation["confounded"])
        self.assertEqual(valuation["avg_impact"], 0.75)
        self.assertEqual(valuation["positive_impact_reviews"], 1)
        self.assertEqual(valuation["negative_impact_reviews"], 0)
        self.assertEqual(valuation["falsification_triggered"], 1)
        self.assertEqual(valuation["risk_signal_valid"], 1)
        risk = report["by_factor"][1]
        self.assertEqual(risk["factor"], "risk")
        self.assertEqual(risk["reviews"], 1)
        self.assertEqual(risk["avg_return_pct"], 10.0)
        self.assertEqual(risk["max_drawdown_pct"], -3.0)
        self.assertEqual(risk["worst_return_pct"], 10.0)
        self.assertEqual(risk["coverage_rate"], 0.5)
        self.assertEqual(risk["avg_impact"], -0.5)
        self.assertEqual(risk["negative_impact_reviews"], 1)
        range_valuation = next(item for item in report["by_regime_factor"] if item["regime"] == "range_bound" and item["factor"] == "valuation")
        weak_valuation = next(item for item in report["by_regime_factor"] if item["regime"] == "weak_market" and item["factor"] == "valuation")
        self.assertEqual(range_valuation["avg_return_pct"], 10.0)
        self.assertEqual(range_valuation["max_drawdown_pct"], -3.0)
        self.assertEqual(weak_valuation["avg_return_pct"], -5.0)
        self.assertEqual(weak_valuation["max_drawdown_pct"], -8.0)

    def test_build_single_factor_validation_report_groups_offsets_and_samples(self) -> None:
        session = _FakeSession()
        observation_a = type(
            "Observation",
            (),
            {
                "id": 7,
                "symbol": "000001.SZ",
                "strategy_id": "retail_small",
                "snapshot_date": datetime(2026, 5, 9, tzinfo=timezone.utc),
                "factor_snapshot_json": [
                    {"factor": "valuation", "dimension": "valuation", "label": "Valuation", "weighted_delta": 1.2, "sources": ["strategy_weighted"]}
                ],
            },
        )()
        observation_b = type(
            "Observation",
            (),
            {
                "id": 8,
                "symbol": "000002.SZ",
                "strategy_id": "retail_small",
                "snapshot_date": datetime(2026, 5, 10, tzinfo=timezone.utc),
                "factor_snapshot_json": [
                    {"factor": "quality", "dimension": "valuation", "label": "Valuation", "evidence_impact": -0.5, "sources": ["evidence_chain"]}
                ],
            },
        )()
        review_a = type(
            "Review",
            (),
            {
                "observation_id": 7,
                "review_offset": "T+1",
                "return_pct": 3.0,
                "max_drawdown_pct": -1.0,
                "falsification_triggered": False,
                "risk_signal_valid": False,
            },
        )()
        review_b = type(
            "Review",
            (),
            {
                "observation_id": 8,
                "review_offset": "T+5",
                "return_pct": -2.0,
                "max_drawdown_pct": -5.0,
                "falsification_triggered": True,
                "risk_signal_valid": True,
            },
        )()
        session.rows = [observation_a, observation_b]
        session.review_rows = [review_a, review_b]

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            report = review_tracker.build_single_factor_validation_report("valuation", min_reviews=2)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["reviews"], 2)
        self.assertEqual(report["summary"]["win_rate"], 0.5)
        self.assertEqual(report["summary"]["avg_return_pct"], 0.5)
        self.assertEqual(report["summary"]["validation_state"], "needs_more_review")
        self.assertEqual([item["review_offset"] for item in report["by_offset"]], ["T+1", "T+5"])
        self.assertEqual(len(report["samples"]), 2)
        self.assertEqual(report["samples"][0]["symbol"], "000002.SZ")

    def test_build_single_factor_validation_report_reports_invalid_and_missing_tables(self) -> None:
        self.assertEqual(review_tracker.build_single_factor_validation_report(" ")["status"], "invalid_factor")
        with patch.object(review_tracker, "_has_table", return_value=False):
            result = review_tracker.build_single_factor_validation_report("valuation")
        self.assertEqual(result["status"], "tables_missing")

    def test_build_weight_adjustment_suggestions_classifies_factor_actions(self) -> None:
        factor_report = {
            "status": "ok",
            "summary": {"factors": 4, "reviews": 18},
            "by_factor": [
                {
                    "factor": "valuation",
                    "label": "Valuation",
                    "reviews": 10,
                    "win_rate": 0.8,
                    "avg_return_pct": 4.5,
                    "avg_impact": 0.9,
                    "falsification_triggered": 0,
                    "risk_signal_valid": 1,
                },
                {
                    "factor": "risk",
                    "label": "Risk",
                    "reviews": 6,
                    "win_rate": 0.35,
                    "avg_return_pct": 0.5,
                    "avg_impact": 0.2,
                    "falsification_triggered": 0,
                    "risk_signal_valid": 2,
                },
                {
                    "factor": "momentum",
                    "label": "Momentum",
                    "reviews": 4,
                    "win_rate": 0.5,
                    "avg_return_pct": 0.5,
                    "avg_impact": 0.1,
                    "falsification_triggered": 0,
                    "risk_signal_valid": 0,
                },
                {
                    "factor": "thin",
                    "label": "Thin",
                    "reviews": 2,
                    "win_rate": 1.0,
                    "avg_return_pct": 10.0,
                    "avg_impact": 1.0,
                    "falsification_triggered": 0,
                    "risk_signal_valid": 0,
                },
            ],
        }

        with patch.object(review_tracker, "build_factor_review_report", return_value=factor_report) as report:
            result = review_tracker.build_weight_adjustment_suggestions(
                min_reviews=3,
                snapshot_from=date(2026, 5, 1),
                snapshot_to=date(2026, 5, 10),
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"], {"suggestions": 3, "eligible_factors": 3, "confounded_held": 0, "baseline_win_rate": None, "min_reviews": 3})
        self.assertEqual(
            [(item["factor"], item["action"]) for item in result["suggestions"]],
            [("valuation", "increase"), ("risk", "decrease"), ("momentum", "hold")],
        )
        self.assertEqual(result["suggestions"][0]["confidence"], "high")
        self.assertEqual(result["suggestions"][1]["confidence"], "medium")
        self.assertEqual(result["suggestions"][2]["confidence"], "low")
        self.assertEqual(result["suggestions"][0]["metrics"]["reviews"], 10)
        kwargs = report.call_args.kwargs
        self.assertEqual(kwargs["snapshot_from"], date(2026, 5, 1))
        self.assertEqual(kwargs["snapshot_to"], date(2026, 5, 10))

    def test_build_weight_adjustment_suggestions_holds_confounded_factors(self) -> None:
        # A factor with strong raw win_rate that would normally trigger "increase",
        # but it is high-coverage and flagged confounded -> must be held.
        factor_report = {
            "status": "ok",
            "summary": {"factors": 2, "reviews": 20, "baseline_win_rate": 0.78},
            "by_factor": [
                {
                    "factor": "trend",
                    "label": "Trend",
                    "reviews": 18,
                    "win_rate": 0.8,
                    "baseline_win_rate": 0.78,
                    "win_rate_lift": 0.02,
                    "coverage_rate": 0.95,
                    "avg_return_pct": 4.0,
                    "avg_impact": 0.9,
                    "falsification_triggered": 0,
                    "risk_signal_valid": 0,
                    "confounded": True,
                },
                {
                    "factor": "valuation",
                    "label": "Valuation",
                    "reviews": 10,
                    "win_rate": 0.8,
                    "baseline_win_rate": 0.5,
                    "win_rate_lift": 0.3,
                    "coverage_rate": 0.4,
                    "avg_return_pct": 4.0,
                    "avg_impact": 0.9,
                    "falsification_triggered": 0,
                    "risk_signal_valid": 0,
                    "confounded": False,
                },
            ],
        }

        with patch.object(review_tracker, "build_factor_review_report", return_value=factor_report):
            result = review_tracker.build_weight_adjustment_suggestions(min_reviews=3)

        by_factor = {item["factor"]: item for item in result["suggestions"]}
        # confounded trend held despite a win_rate that alone would say "increase"
        self.assertEqual(by_factor["trend"]["action"], "hold")
        self.assertTrue(by_factor["trend"]["confounded"])
        self.assertIn("confounded", by_factor["trend"]["reason"])
        # genuine high-lift factor still gets increase
        self.assertEqual(by_factor["valuation"]["action"], "increase")
        self.assertFalse(by_factor["valuation"]["confounded"])
        self.assertEqual(result["summary"]["confounded_held"], 1)
        self.assertEqual(result["summary"]["baseline_win_rate"], 0.78)

    def test_build_weight_adjustment_suggestions_reports_missing_tables(self) -> None:
        with patch.object(
            review_tracker,
            "build_factor_review_report",
            return_value={"status": "tables_missing", "summary": {}, "by_factor": []},
        ):
            result = review_tracker.build_weight_adjustment_suggestions(min_reviews=5)

        self.assertEqual(
            result,
            {
                "status": "tables_missing",
                "summary": {"suggestions": 0, "eligible_factors": 0, "min_reviews": 5},
                "suggestions": [],
            },
        )

    def test_save_weight_suggestion_audit_returns_none_when_table_missing(self) -> None:
        with patch.object(review_tracker, "_has_table", return_value=False):
            audit_id = review_tracker.save_weight_suggestion_audit({"status": "ok"}, min_reviews=3)

        self.assertIsNone(audit_id)

    def test_save_weight_suggestion_audit_persists_result_snapshot(self) -> None:
        session = _FakeSession()
        result = {
            "status": "ok",
            "summary": {"suggestions": 1},
            "suggestions": [{"factor": "valuation", "action": "increase"}],
        }

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            audit_id = review_tracker.save_weight_suggestion_audit(
                result,
                min_reviews=5,
                snapshot_from=date(2026, 5, 1),
                snapshot_to=date(2026, 5, 10),
            )

        self.assertEqual(audit_id, 101)
        self.assertTrue(session.committed)
        row = session.added[0]
        self.assertEqual(row.min_reviews, 5)
        self.assertEqual(row.status, "ok")
        self.assertEqual(row.summary_json, {"suggestions": 1})
        self.assertEqual(row.suggestions_json, [{"factor": "valuation", "action": "increase"}])
        self.assertEqual(row.snapshot_from.date(), date(2026, 5, 1))
        self.assertEqual(row.snapshot_to.date(), date(2026, 5, 10))

    def test_list_weight_suggestion_audits_serializes_recent_rows(self) -> None:
        session = _FakeSession()
        session.audit_rows = [
            type(
                "Audit",
                (),
                {
                    "id": 7,
                    "generated_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
                    "snapshot_from": datetime(2026, 5, 1, tzinfo=timezone.utc),
                    "snapshot_to": None,
                    "min_reviews": 3,
                    "status": "ok",
                    "suggestions_json": [{"factor": "valuation"}],
                    "summary_json": {"suggestions": 1},
                    "accepted": None,
                    "accepted_by": None,
                    "accepted_at": None,
                    "notes": None,
                    "created_at": datetime(2026, 5, 10, 12, 1, tzinfo=timezone.utc),
                },
            )()
        ]

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            rows = review_tracker.list_weight_suggestion_audits(limit=20)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 7)
        self.assertEqual(rows[0]["suggestions"], [{"factor": "valuation"}])
        self.assertEqual(rows[0]["summary"], {"suggestions": 1})
        self.assertEqual(rows[0]["generated_at"], "2026-05-10T12:00:00+00:00")
        self.assertTrue(session.closed)

    def test_update_weight_suggestion_audit_sets_decision_fields(self) -> None:
        session = _FakeSession()
        row = type(
            "Audit",
            (),
            {
                "id": 7,
                "generated_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
                "snapshot_from": None,
                "snapshot_to": None,
                "min_reviews": 3,
                "status": "ok",
                "suggestions_json": [],
                "summary_json": {},
                "accepted": None,
                "accepted_by": None,
                "accepted_at": None,
                "notes": None,
                "created_at": datetime(2026, 5, 10, 12, 1, tzinfo=timezone.utc),
            },
        )()
        session.audit_by_id = row

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            updated = review_tracker.update_weight_suggestion_audit(7, accepted=True, notes="approved", accepted_by=99)

        self.assertTrue(session.committed)
        self.assertEqual(updated["accepted"], True)
        self.assertEqual(updated["accepted_by"], 99)
        self.assertEqual(updated["notes"], "approved")
        self.assertIsNotNone(updated["accepted_at"])

    def test_update_weight_suggestion_audit_can_clear_decision(self) -> None:
        session = _FakeSession()
        row = type(
            "Audit",
            (),
            {
                "id": 7,
                "generated_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
                "snapshot_from": None,
                "snapshot_to": None,
                "min_reviews": 3,
                "status": "ok",
                "suggestions_json": [],
                "summary_json": {},
                "accepted": True,
                "accepted_by": 99,
                "accepted_at": datetime(2026, 5, 10, 13, 0, tzinfo=timezone.utc),
                "notes": "approved",
                "created_at": datetime(2026, 5, 10, 12, 1, tzinfo=timezone.utc),
            },
        )()
        session.audit_by_id = row

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            updated = review_tracker.update_weight_suggestion_audit(7, accepted=None, accepted_provided=True)

        self.assertTrue(session.committed)
        self.assertIsNone(updated["accepted"])
        self.assertIsNone(updated["accepted_by"])
        self.assertIsNone(updated["accepted_at"])

    def test_build_weight_strategy_patch_preview_requires_accepted_audit(self) -> None:
        for accepted in (False, None):
            with self.subTest(accepted=accepted):
                session = _FakeSession()
                session.audit_by_id = type(
                    "Audit",
                    (),
                    {
                        "id": 7,
                        "accepted": accepted,
                        "suggestions_json": [{"factor": "valuation", "action": "increase", "confidence": "high"}],
                    },
                )()

                with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
                    review_tracker, "SessionLocal", return_value=session
                ):
                    result = review_tracker.build_weight_strategy_patch_preview(7)

                self.assertEqual(result["status"], "audit_not_accepted")
                self.assertEqual(result["accepted"], accepted)
                self.assertEqual(result["items"], [])

    def test_build_weight_strategy_patch_preview_generates_normalized_patch(self) -> None:
        session = _FakeSession()
        session.audit_by_id = type(
            "Audit",
            (),
            {
                "id": 7,
                "accepted": True,
                "suggestions_json": [
                    {"factor": "valuation", "action": "increase", "confidence": "high"},
                    {"factor": "risk", "action": "decrease", "confidence": "medium"},
                    {"factor": "momentum", "action": "hold", "confidence": "high"},
                    {"factor": "unknown", "action": "increase", "confidence": "high"},
                ],
            },
        )()

        with tempfile.TemporaryDirectory() as tmpdir:
            strategy_dir = Path(tmpdir)
            (strategy_dir / "unit_strategy.json").write_text(
                '{"id":"unit_strategy","weights":{"valuation":0.4,"risk":0.3,"momentum":0.3}}',
                encoding="utf-8",
            )
            with patch.object(review_tracker, "_STRATEGY_CONFIG_DIR", strategy_dir), patch.object(
                review_tracker, "_has_table", return_value=True
            ), patch.object(review_tracker, "SessionLocal", return_value=session):
                result = review_tracker.build_weight_strategy_patch_preview(
                    7,
                    strategy_id="unit_strategy",
                    step=0.03,
                    max_delta=0.08,
                )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["before"], {"valuation": 0.4, "risk": 0.3, "momentum": 0.3})
        self.assertAlmostEqual(sum(result["after"].values()), 1.0, places=5)
        self.assertGreater(result["after"]["valuation"], result["before"]["valuation"])
        self.assertLess(result["after"]["risk"], result["before"]["risk"])
        self.assertAlmostEqual(result["items"][0]["requested_delta"], 0.08)
        self.assertEqual([item["factor"] for item in result["items"]], ["valuation", "risk", "momentum"])

    def test_build_weight_strategy_patch_preview_maps_evidence_factor_aliases(self) -> None:
        session = _FakeSession()
        session.audit_by_id = type(
            "Audit",
            (),
            {
                "id": 8,
                "accepted": True,
                "suggestions_json": [
                    {"factor": "financial_profit", "action": "increase", "confidence": "medium"},
                    {"factor": "news_sentiment", "action": "decrease", "confidence": "low"},
                    {"factor": "risk_news", "action": "decrease", "confidence": "high"},
                ],
            },
        )()

        with tempfile.TemporaryDirectory() as tmpdir:
            strategy_dir = Path(tmpdir)
            (strategy_dir / "unit_strategy.json").write_text(
                '{"id":"unit_strategy","weights":{"financial_quality":0.4,"sentiment":0.3,"risk":0.3}}',
                encoding="utf-8",
            )
            with patch.object(review_tracker, "_STRATEGY_CONFIG_DIR", strategy_dir), patch.object(
                review_tracker, "_has_table", return_value=True
            ), patch.object(review_tracker, "SessionLocal", return_value=session):
                result = review_tracker.build_weight_strategy_patch_preview(8, strategy_id="unit_strategy")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            [(item["source_factor"], item["factor"]) for item in result["items"]],
            [("financial_profit", "financial_quality"), ("news_sentiment", "sentiment"), ("risk_news", "risk")],
        )

    def test_create_strategy_weight_patch_proposal_persists_preview(self) -> None:
        session = _FakeSession()
        preview = {
            "status": "ok",
            "audit_id": 7,
            "strategy_id": "retail_small",
            "step": 0.03,
            "max_delta": 0.08,
            "before": {"valuation": 0.1},
            "after": {"valuation": 0.2},
            "delta": {"valuation": 0.1},
            "items": [{"factor": "valuation"}],
        }

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "build_weight_strategy_patch_preview", return_value=preview
        ), patch.object(review_tracker, "SessionLocal", return_value=session):
            result = review_tracker.create_strategy_weight_patch_proposal(7, created_by=42, notes="candidate")

        self.assertEqual(result["id"], 101)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["created_by"], 42)
        self.assertEqual(result["before"], {"valuation": 0.1})
        self.assertTrue(session.committed)

    def test_create_strategy_weight_patch_proposal_returns_preview_status_when_not_ready(self) -> None:
        preview = {"status": "audit_not_accepted", "audit_id": 7, "items": []}

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "build_weight_strategy_patch_preview", return_value=preview
        ):
            result = review_tracker.create_strategy_weight_patch_proposal(7)

        self.assertEqual(result["status"], "preview_not_ready")
        self.assertEqual(result["preview"], preview)

    def test_list_and_decide_strategy_weight_patch_proposals(self) -> None:
        session = _FakeSession()
        proposal = type(
            "Proposal",
            (),
            {
                "id": 9,
                "audit_id": 7,
                "strategy_id": "retail_small",
                "status": "pending",
                "step": 0.03,
                "max_delta": 0.08,
                "before_json": {"valuation": 0.1},
                "after_json": {"valuation": 0.2},
                "delta_json": {"valuation": 0.1},
                "items_json": [],
                "preview_json": {},
                "created_by": 42,
                "decided_by": None,
                "decided_at": None,
                "notes": None,
                "created_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
            },
        )()
        session.proposal_rows = [proposal]
        session.proposal_by_id = proposal

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            rows = review_tracker.list_strategy_weight_patch_proposals(limit=10)
            updated = review_tracker.decide_strategy_weight_patch_proposal(9, "approved", decided_by=99, notes="ok")

        self.assertEqual(rows[0]["id"], 9)
        self.assertEqual(updated["status"], "approved")
        self.assertEqual(updated["decided_by"], 99)
        self.assertEqual(updated["notes"], "ok")
        self.assertIsNotNone(updated["decided_at"])

    def test_apply_strategy_weight_patch_proposal_writes_strategy_config(self) -> None:
        session = _FakeSession()
        proposal = type(
            "Proposal",
            (),
            {
                "id": 9,
                "audit_id": 7,
                "strategy_id": "unit_strategy",
                "status": "approved",
                "step": 0.03,
                "max_delta": 0.08,
                "before_json": {"valuation": 0.4, "risk": 0.6},
                "after_json": {"valuation": 0.7, "risk": 0.3},
                "delta_json": {"valuation": 0.3, "risk": -0.3},
                "items_json": [],
                "preview_json": {},
                "created_by": 42,
                "decided_by": 99,
                "decided_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
                "applied_by": None,
                "applied_at": None,
                "applied_error": None,
                "notes": None,
                "created_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
            },
        )()
        session.proposal_by_id = proposal

        with tempfile.TemporaryDirectory() as tmpdir:
            strategy_dir = Path(tmpdir)
            strategy_path = strategy_dir / "unit_strategy.json"
            strategy_path.write_text(
                '{"id":"unit_strategy","name":"Unit","weights":{"valuation":0.4,"risk":0.6},"filters":{"min_data_grade":"C"}}',
                encoding="utf-8",
            )
            with patch.object(review_tracker, "_STRATEGY_CONFIG_DIR", strategy_dir), patch.object(
                review_tracker, "_has_table", return_value=True
            ), patch.object(review_tracker, "SessionLocal", return_value=session):
                result = review_tracker.apply_strategy_weight_patch_proposal(9, applied_by=123, notes="applied")

            payload = json.loads(strategy_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["applied_by"], 123)
        self.assertIsNotNone(result["applied_at"])
        self.assertEqual(result["notes"], "applied")
        self.assertAlmostEqual(sum(payload["weights"].values()), 1.0, places=5)
        self.assertEqual(payload["weights"], {"valuation": 0.7, "risk": 0.3})
        self.assertEqual(payload["filters"], {"min_data_grade": "C"})
        self.assertTrue(session.committed)
        versions = [item for item in session.added if item.__class__.__name__ == "StrategyWeightVersion"]
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].before_json, {"valuation": 0.4, "risk": 0.6})
        self.assertEqual(versions[0].after_json, {"valuation": 0.7, "risk": 0.3})

    def test_list_and_rollback_strategy_weight_versions(self) -> None:
        session = _FakeSession()
        version = type(
            "Version",
            (),
            {
                "id": 11,
                "strategy_id": "unit_strategy",
                "proposal_id": 9,
                "version": 1,
                "before_json": {"valuation": 0.4, "risk": 0.6},
                "after_json": {"valuation": 0.7, "risk": 0.3},
                "applied_by": 123,
                "applied_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
                "rolled_back_by": None,
                "rolled_back_at": None,
                "rollback_error": None,
                "notes": None,
                "created_at": datetime(2026, 5, 10, 12, 1, tzinfo=timezone.utc),
            },
        )()
        session.version_rows = [version]
        session.version_by_id = version

        with tempfile.TemporaryDirectory() as tmpdir:
            strategy_dir = Path(tmpdir)
            strategy_path = strategy_dir / "unit_strategy.json"
            strategy_path.write_text(
                '{"id":"unit_strategy","name":"Unit","weights":{"valuation":0.7,"risk":0.3}}',
                encoding="utf-8",
            )
            with patch.object(review_tracker, "_STRATEGY_CONFIG_DIR", strategy_dir), patch.object(
                review_tracker, "_has_table", return_value=True
            ), patch.object(review_tracker, "SessionLocal", return_value=session):
                rows = review_tracker.list_strategy_weight_versions(strategy_id="unit_strategy", limit=10)
                rolled_back = review_tracker.rollback_strategy_weight_version(11, rolled_back_by=456, notes="rollback")

            payload = json.loads(strategy_path.read_text(encoding="utf-8"))

        self.assertEqual(rows[0]["id"], 11)
        self.assertEqual(rolled_back["rolled_back_by"], 456)
        self.assertIsNotNone(rolled_back["rolled_back_at"])
        self.assertEqual(payload["weights"], {"valuation": 0.4, "risk": 0.6})

    def test_rollback_strategy_weight_version_records_error(self) -> None:
        session = _FakeSession()
        version = type(
            "Version",
            (),
            {
                "id": 11,
                "strategy_id": "missing_strategy",
                "proposal_id": 9,
                "version": 1,
                "before_json": {"valuation": 1.0},
                "after_json": {"valuation": 0.8},
                "applied_by": 123,
                "applied_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
                "rolled_back_by": None,
                "rolled_back_at": None,
                "rollback_error": None,
                "notes": None,
                "created_at": datetime(2026, 5, 10, 12, 1, tzinfo=timezone.utc),
            },
        )()
        session.version_by_id = version

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(review_tracker, "_STRATEGY_CONFIG_DIR", Path(tmpdir)), patch.object(
                review_tracker, "_has_table", return_value=True
            ), patch.object(review_tracker, "SessionLocal", return_value=session):
                result = review_tracker.rollback_strategy_weight_version(11, rolled_back_by=456)

        self.assertIn("strategy config not found", result["rollback_error"])
        self.assertTrue(session.committed)

    def test_preview_strategy_weight_proposal_impact_compares_ranking(self) -> None:
        session = _FakeSession()
        proposal = type(
            "Proposal",
            (),
            {
                "id": 9,
                "audit_id": 7,
                "strategy_id": "unit_strategy",
                "status": "approved",
                "step": 0.03,
                "max_delta": 0.08,
                "before_json": {"technical": 0.7, "valuation": 0.3},
                "after_json": {"technical": 0.3, "valuation": 0.7},
                "delta_json": {},
                "items_json": [],
                "preview_json": {},
                "created_by": None,
                "decided_by": None,
                "decided_at": None,
                "applied_by": None,
                "applied_at": None,
                "applied_error": None,
                "notes": None,
                "created_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
            },
        )()
        session.proposal_by_id = proposal

        async def fake_pipeline(**_kwargs):
            return {
                "recommendations": [
                    {
                        "symbol": "000001.SZ",
                        "name": "Tech",
                        "score": 76,
                        "base_score": 76,
                        "risk_flags": [],
                        "data_grade": {"grade": "B"},
                        "score_breakdown": [
                            {"key": "base", "delta": 50},
                            {"key": "technical", "delta": 20},
                            {"key": "valuation", "delta": -12},
                        ],
                    },
                    {
                        "symbol": "000002.SZ",
                        "name": "Value",
                        "score": 76,
                        "base_score": 76,
                        "risk_flags": [],
                        "data_grade": {"grade": "B"},
                        "score_breakdown": [
                            {"key": "base", "delta": 50},
                            {"key": "technical", "delta": -8},
                            {"key": "valuation", "delta": 20},
                        ],
                    },
                ],
                "selection": {"mode": "unit"},
                "warnings": [],
            }

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ), patch(
            "backend.services.analysis_service.engine.research_pipeline.run_research_pipeline",
            side_effect=fake_pipeline,
        ):
            result = asyncio.run(review_tracker.preview_strategy_weight_proposal_impact(9, limit=2, candidate_limit=2))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["items"][0]["symbol"], "000002.SZ")
        self.assertGreater(result["changed_count"], 0)
        self.assertEqual(result["items"][0]["rank_delta"], 1)

    def test_apply_strategy_weight_patch_proposal_requires_approved_status(self) -> None:
        session = _FakeSession()
        proposal = type(
            "Proposal",
            (),
            {
                "id": 9,
                "audit_id": 7,
                "strategy_id": "unit_strategy",
                "status": "pending",
                "step": 0.03,
                "max_delta": 0.08,
                "before_json": {},
                "after_json": {"valuation": 1.0},
                "delta_json": {},
                "items_json": [],
                "preview_json": {},
                "created_by": None,
                "decided_by": None,
                "decided_at": None,
                "applied_by": None,
                "applied_at": None,
                "applied_error": None,
                "notes": None,
                "created_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
            },
        )()
        session.proposal_by_id = proposal

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            result = review_tracker.apply_strategy_weight_patch_proposal(9, applied_by=123)

        self.assertEqual(result["status"], "pending")
        self.assertIsNone(result["applied_at"])
        self.assertFalse(session.committed)

    def test_apply_strategy_weight_patch_proposal_records_apply_error(self) -> None:
        session = _FakeSession()
        proposal = type(
            "Proposal",
            (),
            {
                "id": 9,
                "audit_id": 7,
                "strategy_id": "missing_strategy",
                "status": "approved",
                "step": 0.03,
                "max_delta": 0.08,
                "before_json": {},
                "after_json": {"valuation": 1.0},
                "delta_json": {},
                "items_json": [],
                "preview_json": {},
                "created_by": None,
                "decided_by": 99,
                "decided_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
                "applied_by": None,
                "applied_at": None,
                "applied_error": None,
                "notes": None,
                "created_at": datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
            },
        )()
        session.proposal_by_id = proposal

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(review_tracker, "_STRATEGY_CONFIG_DIR", Path(tmpdir)), patch.object(
                review_tracker, "_has_table", return_value=True
            ), patch.object(review_tracker, "SessionLocal", return_value=session):
                result = review_tracker.apply_strategy_weight_patch_proposal(9, applied_by=123)

        self.assertEqual(result["status"], "approved")
        self.assertIn("strategy config not found", result["applied_error"])
        self.assertTrue(session.committed)

    def test_build_recent_review_summaries_groups_latest_observation_by_symbol(self) -> None:
        session = _FakeSession()
        observation = type(
            "Observation",
            (),
            {
                "id": 7,
                "symbol": "000001.SZ",
                "strategy_id": "retail_small",
                "snapshot_date": datetime(2026, 5, 9, tzinfo=timezone.utc),
                "close_price": 10.0,
            },
        )()
        review = type(
            "Review",
            (),
            {
                "observation_id": 7,
                "review_offset": "T+1",
                "review_date": datetime(2026, 5, 10, tzinfo=timezone.utc),
                "close_price": 11.0,
                "return_pct": 10.0,
                "max_drawdown_pct": None,
                "falsification_triggered": False,
                "risk_signal_valid": True,
                "notes": "source=unit",
            },
        )()
        session.rows = [observation]
        session.review_rows = [review]

        with patch.object(review_tracker, "_has_table", return_value=True), patch.object(
            review_tracker, "SessionLocal", return_value=session
        ):
            result = review_tracker.build_recent_review_summaries(
                ["000001.SZ", "600000.SH"],
                strategy="auto",
                offsets=("T+1", "T+5"),
                limit_per_symbol=1,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["missing_symbols"], ["600000.SH"])
        item = result["items"]["000001.SZ"]
        self.assertEqual(item["latest_snapshot_date"], "2026-05-09")
        self.assertEqual(item["strategy_id"], "retail_small")
        self.assertEqual(item["base_price"], 10.0)
        self.assertEqual(item["reviews"]["T+1"]["return_pct"], 10.0)
        self.assertIsNone(item["reviews"]["T+5"])

    def test_build_recent_review_summaries_reports_missing_tables(self) -> None:
        with patch.object(review_tracker, "_has_table", return_value=False):
            result = review_tracker.build_recent_review_summaries(["000001.SZ"])

        self.assertEqual(result, {"status": "tables_missing", "items": {}, "missing_symbols": ["000001.SZ"]})


if __name__ == "__main__":
    unittest.main()
