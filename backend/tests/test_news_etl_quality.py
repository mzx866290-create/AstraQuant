from __future__ import annotations

from datetime import datetime, timedelta
import sys
import types
import unittest
from unittest.mock import Mock, patch

from backend.services.data_crawler.pipeline.news_etl import NewsETL


POSITIVE = "\u6b63\u9762"
NEGATIVE = "\u8d1f\u9762"
NEUTRAL = "\u4e2d\u6027"
HIGH = "\u9ad8"
MEDIUM = "\u4e2d"
LOW = "\u4f4e"


class _FakeSession:
    def __init__(self, rowcounts=None, *, fail_on_execute: bool = False) -> None:
        self.rowcounts = list(rowcounts or [])
        self.fail_on_execute = fail_on_execute
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def get_bind(self):
        return types.SimpleNamespace(dialect=types.SimpleNamespace(name="sqlite"))

    def execute(self, stmt):
        self.executed.append(stmt)
        if self.fail_on_execute:
            raise RuntimeError("write failed")
        rowcount = self.rowcounts.pop(0) if self.rowcounts else 0
        return types.SimpleNamespace(rowcount=rowcount)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _patched_save_imports():
    models = types.SimpleNamespace(StockNews=type("StockNews", (), {}))

    def insert_do_nothing(model, row, conflict_columns, dialect_name):
        return {
            "model": model.__name__,
            "row": dict(row),
            "conflict_columns": list(conflict_columns),
            "dialect_name": dialect_name,
        }

    upsert = types.SimpleNamespace(
        insert_do_nothing=insert_do_nothing,
        session_dialect_name=lambda session: session.get_bind().dialect.name,
    )
    return patch.dict(
        sys.modules,
        {
            "backend.shared.models": models,
            "backend.services.data_crawler.pipeline.upsert": upsert,
        },
    )


class NewsETLRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.etl = NewsETL()

    def test_compute_sentiment_maps_financial_keywords_to_label_score_and_impact(self) -> None:
        positive = self.etl.compute_sentiment("\u516c\u53f8\u4e1a\u7ee9\u5927\u5e45\u9884\u589e\u4e14\u8d85\u9884\u671f")
        negative = self.etl.compute_sentiment("\u516c\u53f8\u88ab\u7acb\u6848\u8c03\u67e5\u5e76\u5b58\u5728\u9000\u5e02\u98ce\u9669")
        neutral = self.etl.compute_sentiment("unit company hosts investor meeting")

        self.assertEqual(positive, (POSITIVE, 0.8, HIGH))
        self.assertEqual(negative, (NEGATIVE, -0.925, HIGH))
        self.assertEqual(neutral, (NEUTRAL, 0.0, LOW))

    def test_classify_event_and_keyword_extraction_are_rule_based_and_bounded(self) -> None:
        title = "\u4e1a\u7ee9\u9884\u589e \u56de\u8d2d \u5206\u7ea2 \u91cd\u7ec4 \u6da8\u505c \u4e2d\u6807 \u5408\u540c \u8ba2\u5355 \u83b7\u6279 \u653f\u7b56"

        self.assertEqual(self.etl.classify_event(title), "\u7ecf\u8425")
        self.assertEqual(self.etl.classify_event("\u76d1\u7ba1\u653f\u7b56\u53d1\u5e03"), "\u653f\u7b56")
        self.assertEqual(self.etl.classify_event("\u5238\u5546\u7814\u62a5\u4e0a\u8c03\u76ee\u6807\u4ef7"), "\u8206\u8bba")
        self.assertIsNone(self.etl.classify_event("unit text without category"))
        self.assertEqual(len(self.etl.extract_keywords(title)), 8)
        self.assertEqual(self.etl.extract_keywords(title)[:3], ["\u4e1a\u7ee9", "\u56de\u8d2d", "\u91cd\u7ec4"])

    def test_time_normalization_supports_common_absolute_and_relative_formats(self) -> None:
        self.assertEqual(self.etl._normalize_time("2026-05-07 09:30:00"), datetime(2026, 5, 7, 9, 30))
        self.assertEqual(self.etl._normalize_time("20260507"), datetime(2026, 5, 7))
        self.assertEqual(self.etl._normalize_time("05-07 09:30").month, 5)

        relative = self.etl._normalize_time("3\u5206\u949f\u524d")
        self.assertLess(abs((datetime.now() - relative).total_seconds() - 180), 5)
        self.assertIsNotNone(self.etl._normalize_time("bad-time"))

    def test_freshness_buckets_recent_today_week_and_historical_news(self) -> None:
        now = datetime.now()

        self.assertEqual(self.etl._compute_freshness(now - timedelta(minutes=10)), "realtime")
        self.assertEqual(self.etl._compute_freshness(now - timedelta(hours=2)), "today")
        self.assertEqual(self.etl._compute_freshness(now - timedelta(days=3)), "within_week")
        self.assertEqual(self.etl._compute_freshness(now - timedelta(days=9)), "historical")

    def test_clean_filters_invalid_rows_and_enriches_valid_news(self) -> None:
        raw_items = [
            {
                "title": "\u4e1a\u7ee9\u9884\u589e\u516c\u544a",
                "summary": "\u516c\u53f8\u51c0\u5229\u6da6\u9ad8\u901f\u589e\u957f" * 400,
                "source": "\u8d22\u8054\u793e",
                "url": "https://example.test/news",
                "publish_time": "2026-05-07 09:30:00",
                "related_sector": "\u98df\u54c1\u996e\u6599",
            },
            {"title": "abc", "publish_time": "2026-05-07 09:30:00"},
            {"title": "", "publish_time": "2026-05-07 09:30:00"},
        ]

        cleaned = self.etl.clean("600519.SH", raw_items)

        self.assertEqual(len(cleaned), 1)
        row = cleaned[0]
        self.assertEqual(row["stock_symbol"], "600519")
        self.assertEqual(row["title"], "\u4e1a\u7ee9\u9884\u589e\u516c\u544a")
        self.assertEqual(len(row["summary"]), 2000)
        self.assertEqual(row["source"], "\u8d22\u8054\u793e")
        self.assertEqual(row["url"], "https://example.test/news")
        self.assertEqual(row["publish_time"], datetime(2026, 5, 7, 9, 30))
        self.assertEqual(row["sentiment"], POSITIVE)
        self.assertEqual(row["event_category"], "\u7ecf\u8425")
        self.assertIn("\u4e1a\u7ee9", row["keywords"])
        self.assertEqual(row["related_sector"], "\u98df\u54c1\u996e\u6599")
        self.assertIn(row["freshness"], {"realtime", "today", "within_week", "historical"})


class NewsETLSaveTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_returns_zero_without_touching_session_when_cleaned_data_is_empty(self) -> None:
        etl = NewsETL()
        session = Mock()

        with _patched_save_imports():
            saved = await etl.save(session, "600519", [{"title": "abc"}])

        self.assertEqual(saved, 0)
        session.execute.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    async def test_save_counts_inserted_rows_uses_conflict_key_and_excludes_freshness(self) -> None:
        etl = NewsETL()
        session = _FakeSession(rowcounts=[1, 0])
        raw_items = [
            {"title": "\u4e1a\u7ee9\u9884\u589e\u516c\u544a", "publish_time": "2026-05-07 09:30:00"},
            {"title": "\u5927\u80a1\u4e1c\u51cf\u6301\u8ba1\u5212", "publish_time": "2026-05-07 10:30:00"},
        ]

        with _patched_save_imports():
            saved = await etl.save(session, "600519.SH", raw_items)

        self.assertEqual(saved, 1)
        self.assertEqual(session.commits, 1)
        self.assertEqual(session.rollbacks, 0)
        self.assertEqual(len(session.executed), 2)
        self.assertEqual(session.executed[0]["model"], "StockNews")
        self.assertEqual(session.executed[0]["conflict_columns"], ["stock_symbol", "title", "publish_time"])
        self.assertEqual(session.executed[0]["dialect_name"], "sqlite")
        self.assertNotIn("freshness", session.executed[0]["row"])
        self.assertEqual(session.executed[0]["row"]["stock_symbol"], "600519")

    async def test_save_rolls_back_and_reraises_on_write_failure(self) -> None:
        etl = NewsETL()
        session = _FakeSession(fail_on_execute=True)

        with _patched_save_imports():
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                await etl.save(
                    session,
                    "600519",
                    [{"title": "\u4e1a\u7ee9\u9884\u589e\u516c\u544a", "publish_time": "2026-05-07 09:30:00"}],
                )

        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
