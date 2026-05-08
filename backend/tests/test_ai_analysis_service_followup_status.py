from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend.services.analysis_service.engine import ai_analysis_service as service
from backend.shared.models import AIModel, AIUsageLog


DISCLAIMER_FRAGMENT = "\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae"
DISCLAIMER_SENTENCE = f"\u4ee5\u4e0a\u89e3\u8bfb\u4ec5\u4f9b\u5b66\u4e60\u548c\u53c2\u8003\uff0c{DISCLAIMER_FRAGMENT}\u3002"


def _model(
    model_id: int,
    *,
    name: str | None = None,
    allowed_roles: str | None = "free,premium,admin",
    is_active: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=model_id,
        name=name or f"model-{model_id}",
        provider="openai",
        model_id=f"external-{model_id}",
        api_key_encrypted=f"encrypted-{model_id}",
        api_base_url=None,
        description=f"description-{model_id}",
        config={},
        is_active=is_active,
        allowed_roles=allowed_roles,
        sort_order=model_id,
    )


def _user(*, user_id: int = 42, role: str | None = "free") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=role)


def _follow_up_request(**overrides) -> SimpleNamespace:
    data = {
        "model_id": 1,
        "symbol": "000001",
        "question": "What should I watch next?",
        "analysis": "Existing analysis with enough length to pass the schema boundary.",
        "report_meta": {"report_mode": "summary"},
        "prompt_style": "default",
        "audience": "normal",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class _FakeQuery:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = list(rows)
        self.filtered = False

    def filter(self, *_args, **_kwargs):
        self.filtered = True
        return self

    def order_by(self, *_args, **_kwargs):
        self.rows = sorted(self.rows, key=lambda row: (getattr(row, "sort_order", 0), getattr(row, "id", 0)))
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def count(self):
        return len(self.rows)


class _FakeDb:
    def __init__(
        self,
        models: list[SimpleNamespace] | None = None,
        crawl_rows: list[SimpleNamespace] | None = None,
        fail_on_crawl: bool = False,
    ) -> None:
        self.models = list(models or [])
        self.crawl_rows = list(crawl_rows or [])
        self.fail_on_crawl = fail_on_crawl
        self.added: list[object] = []
        self.commit_count = 0

    def query(self, entity):
        if entity is AIModel:
            return _FakeQuery([model for model in self.models if getattr(model, "is_active", True)])
        if self.fail_on_crawl:
            raise RuntimeError("crawl table unavailable")
        return _FakeQuery(self.crawl_rows)

    def add(self, item) -> None:
        self.added.append(item)

    def commit(self) -> None:
        self.commit_count += 1


class AIAnalysisServiceFollowUpStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_follow_up_rejects_quota_before_model_lookup(self) -> None:
        db = _FakeDb([_model(1)])

        with patch.object(service, "check_quota_available", return_value=(False, "quota exhausted")):
            with self.assertRaises(HTTPException) as raised:
                await service.follow_up_analysis(_follow_up_request(), _user(), db)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "quota exhausted")
        self.assertEqual(db.commit_count, 0)
        self.assertEqual(db.added, [])

    async def test_follow_up_rejects_missing_or_inactive_model(self) -> None:
        db = _FakeDb([_model(1, is_active=False)])

        with patch.object(service, "check_quota_available", return_value=(True, "")):
            with self.assertRaises(HTTPException) as raised:
                await service.follow_up_analysis(_follow_up_request(), _user(), db)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(db.commit_count, 0)

    async def test_follow_up_rejects_role_not_allowed_for_model(self) -> None:
        db = _FakeDb([_model(1, allowed_roles="admin")])

        with patch.object(service, "check_quota_available", return_value=(True, "")):
            with self.assertRaises(HTTPException) as raised:
                await service.follow_up_analysis(_follow_up_request(), _user(role="free"), db)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(db.commit_count, 0)

    async def test_follow_up_success_sanitizes_direct_advice_and_records_usage(self) -> None:
        requested_model = _model(1, name="primary")
        db = _FakeDb([requested_model])
        router = AsyncMock(
            return_value=(
                {
                    "content": "Strong buy setup with target price 10 after the latest report.",
                    "prompt_tokens": 7,
                    "completion_tokens": 11,
                    "total_tokens": 18,
                    "cost": 0.09,
                    "response_time_ms": 210,
                },
                requested_model,
                None,
            )
        )

        with patch.object(service, "check_quota_available", return_value=(True, "")):
            with patch.object(service.model_router, "analyze_with_fallback", router):
                with patch.object(service, "increment_quota") as increment_quota:
                    response = await service.follow_up_analysis(_follow_up_request(), _user(), db)

        self.assertEqual(response.actual_model, "primary")
        self.assertEqual(response.tokens_used, 18)
        self.assertEqual(response.report_meta["status"], "success")
        self.assertTrue(response.report_meta["sanitized"])
        self.assertNotIn("strong buy", response.answer.lower())
        self.assertNotIn("target price", response.answer.lower())
        self.assertEqual(response.answer.count(DISCLAIMER_FRAGMENT), 1)
        self.assertEqual(len(db.added), 1)
        self.assertIsInstance(db.added[0], AIUsageLog)
        self.assertEqual(db.added[0].status, "success")
        self.assertEqual(db.added[0].total_tokens, 18)
        self.assertEqual(db.added[0].response_time_ms, 210)
        self.assertEqual(db.commit_count, 1)
        increment_quota.assert_called_once_with(42)
        router.assert_awaited_once()

    async def test_follow_up_success_preserves_existing_disclaimer_without_duplication(self) -> None:
        requested_model = _model(1, name="primary")
        db = _FakeDb([requested_model])
        router = AsyncMock(
            return_value=(
                {
                    "content": f"Focus on observable risks and data gaps. {DISCLAIMER_SENTENCE}",
                    "prompt_tokens": 5,
                    "completion_tokens": 8,
                    "total_tokens": 13,
                    "cost": 0.03,
                    "response_time_ms": 120,
                },
                requested_model,
                None,
            )
        )

        with patch.object(service, "check_quota_available", return_value=(True, "")):
            with patch.object(service.model_router, "analyze_with_fallback", router):
                with patch.object(service, "increment_quota"):
                    response = await service.follow_up_analysis(_follow_up_request(), _user(), db)

        self.assertEqual(response.report_meta["status"], "success")
        self.assertFalse(response.report_meta["sanitized"])
        self.assertEqual(response.answer.count(DISCLAIMER_FRAGMENT), 1)
        self.assertIn(DISCLAIMER_SENTENCE, response.answer)
        self.assertEqual(db.commit_count, 1)

    async def test_follow_up_model_failure_uses_local_fallback_and_error_usage(self) -> None:
        requested_model = _model(1, name="primary")
        db = _FakeDb([requested_model])
        router = AsyncMock(side_effect=RuntimeError("gateway down"))

        with patch.object(service, "check_quota_available", return_value=(True, "")):
            with patch.object(service.model_router, "analyze_with_fallback", router):
                with patch.object(service, "increment_quota") as increment_quota:
                    response = await service.follow_up_analysis(_follow_up_request(), _user(), db)

        self.assertEqual(response.actual_model, "local-fallback")
        self.assertEqual(response.tokens_used, 0)
        self.assertEqual(response.response_time_ms, 0)
        self.assertEqual(response.report_meta["status"], "error")
        self.assertIn("gateway down", response.fallback_reason)
        self.assertIn("gateway down", response.answer)
        self.assertEqual(response.answer.count(DISCLAIMER_FRAGMENT), 1)
        self.assertEqual(len(db.added), 1)
        self.assertIsInstance(db.added[0], AIUsageLog)
        self.assertEqual(db.added[0].status, "error")
        self.assertEqual(db.added[0].error_message, "gateway down")
        self.assertEqual(db.commit_count, 1)
        increment_quota.assert_not_called()

    async def test_get_analysis_readiness_adds_clean_symbol_and_crawl_status(self) -> None:
        stock_data = {
            "symbol": "000001",
            "name": "Unit Bank",
            "price": 12.3,
            "quote": {"open": 12.0, "high": 12.5, "low": 11.8, "volume": 100, "turnover": 200, "source": "unit"},
            "quote_source": "unit",
            "kline_data": [{"date": f"2026-04-{day:02d}", "close": 10 + day / 10} for day in range(1, 22)],
            "kline_source": "unit-kline",
            "financial": {"report_date": "2026-03-31", "source": "unit-fin", "revenue": 1, "net_profit": 1, "operating_cf": 1, "pe_ttm": 9, "pb": 1},
            "announcements": [{"announce_date": "2026-05-01", "title": "unit"}],
            "news": [{"publish_time": "2026-05-06T09:00:00+00:00", "title": "unit"}],
        }
        finished_at = datetime(2026, 5, 7, 8, 30, tzinfo=timezone.utc)
        crawl_row = SimpleNamespace(
            data_type="daily_kline",
            status="success",
            source="eastmoney",
            fetched_count=21,
            saved_count=21,
            error_message=None,
            finished_at=finished_at,
        )
        db = _FakeDb([_model(1), _model(2)], [crawl_row])

        with patch.object(service, "get_stock_data", AsyncMock(return_value=stock_data)) as get_stock_data:
            with patch.object(service, "check_quota_available", return_value=(True, "")):
                readiness = await service.get_analysis_readiness("000001", _user(), db)

        self.assertEqual(readiness["symbol"], "000001")
        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["items"]["ai_model"]["count"], 2)
        self.assertEqual(readiness["crawl_status"]["daily_kline"]["status"], "success")
        self.assertEqual(readiness["crawl_status"]["daily_kline"]["finished_at"], finished_at.isoformat())
        get_stock_data.assert_awaited_once_with("000001", include_news=True)

    def test_get_crawl_status_returns_empty_dict_when_query_fails(self) -> None:
        self.assertEqual(service._get_crawl_status("000001", _FakeDb(fail_on_crawl=True)), {})


if __name__ == "__main__":
    unittest.main()
