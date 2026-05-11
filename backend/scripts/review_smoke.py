#!/usr/bin/env python
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.analysis_service.engine import review_tracker
from backend.shared.models import ObservationReview, ResearchObservation


class _MemoryStore:
    def __init__(self) -> None:
        self.observations: list[ResearchObservation] = []
        self.reviews: list[ObservationReview] = []
        self.next_observation_id = 1
        self.next_review_id = 1


class _FakeQuery:
    def __init__(self, store: _MemoryStore, model) -> None:
        self.store = store
        self.model = model
        self.filters = []

    def filter(self, *clauses):
        self.filters.extend(clauses)
        return self

    def order_by(self, *_clauses):
        return self

    def all(self):
        if self.model is ResearchObservation:
            return list(self.store.observations)
        if self.model is ObservationReview:
            return list(self.store.reviews)
        return []

    def first(self):
        if self.model is ResearchObservation:
            if len(self.filters) == 1 and self.store.observations:
                return self.store.observations[0]
            return None
        if self.model is ObservationReview:
            return None
        return None


class _FakeSession:
    def __init__(self, store: _MemoryStore) -> None:
        self.store = store
        self.committed = False
        self.closed = False

    def query(self, model):
        return _FakeQuery(self.store, model)

    def add(self, row):
        if isinstance(row, ResearchObservation):
            row.id = self.store.next_observation_id
            self.store.next_observation_id += 1
            self.store.observations.append(row)
        elif isinstance(row, ObservationReview):
            row.id = self.store.next_review_id
            self.store.next_review_id += 1
            self.store.reviews.append(row)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        self.closed = True


@contextmanager
def _patched_review_dependencies(store: _MemoryStore):
    original_has_table = review_tracker._has_table
    original_session_local = review_tracker.SessionLocal
    original_fetch_quote = review_tracker.fetch_quote

    async def fake_fetch_quote(symbol: str) -> dict:
        return {"symbol": symbol, "price": 9.0, "source": "review-smoke"}

    review_tracker._has_table = lambda _table_name: True
    review_tracker.SessionLocal = lambda: _FakeSession(store)
    review_tracker.fetch_quote = fake_fetch_quote
    try:
        yield
    finally:
        review_tracker._has_table = original_has_table
        review_tracker.SessionLocal = original_session_local
        review_tracker.fetch_quote = original_fetch_quote


async def _main() -> int:
    store = _MemoryStore()
    snapshot_date = date(2026, 5, 10)
    review_date = date(2026, 5, 11)
    recommendations = [
        {
            "symbol": "000001.SZ",
            "strategy_id": "retail_small",
            "score": 72,
            "price": 10.0,
            "score_breakdown": [{"key": "valuation", "delta": 5}],
            "evidence_chain": [{"factor": "valuation", "impact": 4}],
            "bull_case": [{"argument": "估值修复"}],
            "bear_case": [{"argument": "现金流仍需复核"}],
            "key_disagreement": [{"topic": "估值修复可持续性"}],
            "falsification": [{"condition": "跌破关键均线"}],
            "veto_result": {"passed": True, "warnings": [{"detail": "现金流仍需跟踪"}]},
        }
    ]

    with _patched_review_dependencies(store):
        saved = review_tracker.save_observation_snapshots(snapshot_date, "range_bound", recommendations)
        pending = review_tracker.list_pending_reviews(review_date, offsets=("T+1",))
        run_result = await review_tracker.run_pending_reviews(review_date, offsets=("T+1",))
        report = review_tracker.build_review_report()

    assert saved == 1, f"expected 1 saved observation, got {saved}"
    assert len(pending) == 1, f"expected 1 pending review, got {len(pending)}"
    assert run_result["status"] == "ok", run_result
    assert run_result["created"] == 1, run_result
    assert report["status"] == "ok", report
    assert report["summary"]["reviews"] == 1, report
    assert report["by_strategy"][0]["strategy_id"] == "retail_small", report
    assert report["by_strategy"][0]["avg_return_pct"] == -10.0, report

    print(
        json.dumps(
            {
                "status": "ok",
                "saved": saved,
                "pending": len(pending),
                "run_pending_reviews": run_result,
                "review_report": report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
