import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch


class _EmptyNewsQuery:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return []


class _EmptyNewsSession:
    def __init__(self):
        self.closed = False

    def query(self, model):
        return _EmptyNewsQuery()

    def close(self):
        self.closed = True


class NewsManualCrawlContractTests(unittest.TestCase):
    def test_news_query_reads_cache_without_live_fallback_by_default(self) -> None:
        from backend.services.market_service.app.api.v1 import news_api

        db = _EmptyNewsSession()

        with patch("backend.shared.database.SessionLocal", return_value=db), \
             patch("backend.services.data_crawler.sources.news_source.create_news_chain") as create_chain:
            result = asyncio.run(news_api.get_stock_news("600519", limit=20))

        create_chain.assert_not_called()
        self.assertTrue(db.closed)
        self.assertEqual(result["symbol"], "600519")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["news"], [])
        self.assertEqual(result["data_quality"]["source"], "database")
        self.assertIn("no news available", result["data_quality"]["warnings"])

    def test_manual_news_crawl_skips_recent_success_without_external_fetch(self) -> None:
        from backend.services.market_service.app.api.v1 import crawl

        finished_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        recent_status = SimpleNamespace(
            status="success",
            source="多源新闻",
            fetched_count=30,
            saved_count=4,
            error_message=None,
            started_at=finished_at,
            finished_at=finished_at,
        )
        db = Mock()
        user = SimpleNamespace(id=7, role="free")

        with patch("backend.shared.database.SessionLocal", return_value=db), \
             patch.object(crawl, "_latest_crawl_status", return_value=recent_status), \
             patch("backend.services.data_crawler.sources.news_source.create_news_chain") as create_chain:
            result = asyncio.run(crawl.crawl_stock_news("600519.SH", current_user=user))

        create_chain.assert_not_called()
        self.assertEqual(result["status"], "fresh")
        self.assertTrue(result["skipped"])
        self.assertTrue(result["from_cache"])
        self.assertIn("分钟前已更新，无需重复采集", result["message"])
        self.assertEqual(result["crawl_status"]["status"], "fresh")
        self.assertEqual(result["crawl_status"]["saved"], 4)
        db.close.assert_called_once()

    def test_news_scheduler_is_manual_first_by_default(self) -> None:
        from backend.services.data_crawler.app import main

        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(main.scheduled_news_enabled())

        with patch.dict("os.environ", {"DATA_CRAWLER_ENABLE_SCHEDULED_NEWS": "true"}, clear=True):
            self.assertTrue(main.scheduled_news_enabled())


if __name__ == "__main__":
    unittest.main()
