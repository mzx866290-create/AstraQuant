from __future__ import annotations

import importlib
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from fastapi.testclient import TestClient


class DataCrawlerObservabilityTests(unittest.TestCase):
    def _module(self):
        module = importlib.import_module("backend.services.data_crawler.app.main")
        return importlib.reload(module)

    def test_health_endpoint_is_public_and_sanitized(self) -> None:
        with patch.dict("os.environ", {"DATA_CRAWLER_ENABLE_SCHEDULER": "false"}, clear=False):
            module = self._module()
            response = TestClient(module.app).get("/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "data-crawler")
        self.assertNotIn("postgres", str(body).lower())
        self.assertNotIn("redis", str(body).lower())
        self.assertNotIn("clickhouse", str(body).lower())
        self.assertNotIn("127.0.0.1", str(body))
        self.assertNotIn("localhost", str(body).lower())

    def test_ready_endpoint_reports_scheduler_and_dependencies(self) -> None:
        with patch.dict("os.environ", {"DATA_CRAWLER_ENABLE_SCHEDULER": "false"}, clear=False):
            module = self._module()
            with (
                patch.object(module, "database_check", return_value={"name": "database", "status": "ok", "required": True}),
                patch.object(module, "clickhouse_check", return_value={"name": "clickhouse", "status": "ok", "required": False}),
                patch.object(module, "scheduler_check", return_value={"name": "scheduler", "status": "ok", "required": True}),
            ):
                response = TestClient(module.app).get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")

    def test_ready_endpoint_fails_when_scheduler_is_not_running(self) -> None:
        with patch.dict("os.environ", {"DATA_CRAWLER_ENABLE_SCHEDULER": "false"}, clear=False):
            module = self._module()
            with (
                patch.object(module, "database_check", return_value={"name": "database", "status": "ok", "required": True}),
                patch.object(module, "clickhouse_check", return_value={"name": "clickhouse", "status": "ok", "required": False}),
                patch.object(module, "scheduler_check", return_value={"name": "scheduler", "status": "error", "required": True}),
            ):
                response = TestClient(module.app).get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")

    def test_metrics_endpoint_exposes_crawler_task_and_scheduler_metrics(self) -> None:
        with patch.dict("os.environ", {"DATA_CRAWLER_ENABLE_SCHEDULER": "false"}, clear=False):
            module = self._module()
            module.observe_crawler_task(
                "daily_kline",
                "error",
                source="unit-source",
                fetched=3,
                saved=1,
            )
            module.crawler.runtime.mark_disabled()
            module.observe_scheduler_state(module.crawler.runtime, module.crawler.scheduler.running)
            response = TestClient(module.app).get("/metrics")

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("stock_platform_data_crawler_task_runs_total", body)
        self.assertIn("stock_platform_data_crawler_task_rows_total", body)
        self.assertIn("stock_platform_data_crawler_task_last_run_timestamp_seconds", body)
        self.assertIn("stock_platform_data_crawler_task_last_status", body)
        self.assertIn("stock_platform_data_crawler_scheduler_enabled", body)
        self.assertIn("stock_platform_data_crawler_scheduler_running", body)
        self.assertIn('task="daily_kline"', body)
        self.assertIn('status="error"', body)
        self.assertIn('source="unit-source"', body)

    def test_news_scheduler_tasks_are_observed_with_distinct_task_names(self) -> None:
        with patch.dict("os.environ", {"DATA_CRAWLER_ENABLE_SCHEDULER": "false"}, clear=False):
            module = self._module()
            crawler = object.__new__(module.DataCrawler)
            crawler.runtime = module.CrawlerRuntimeState()
            db = Mock()

            with (
                patch("backend.shared.database.SessionLocal", return_value=db),
                patch.object(module, "record_crawl_status", return_value=Mock()),
            ):
                crawler._record_status(
                    "600519",
                    "news",
                    "success",
                    module.now_utc(),
                    source="multi-source-news",
                    fetched=2,
                    saved=2,
                    metric_task_name="stock_news_close",
                )

        tasks = {item["task"] for item in crawler.runtime.snapshot(False)["last_tasks"]}
        self.assertIn("stock_news_close", tasks)
        self.assertNotIn("news", tasks)
        db.close.assert_called_once()


class DataCrawlerOpsConfigTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_dockerfile_exposes_healthchecked_http_service(self) -> None:
        dockerfile = (self.ROOT / "backend/services/data_crawler/Dockerfile").read_text(encoding="utf-8")

        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("EXPOSE 8000", dockerfile)
        self.assertIn('"uvicorn"', dockerfile)
        self.assertIn('"app.main:app"', dockerfile)

    def test_runtime_requirements_include_observability_server(self) -> None:
        requirements = (self.ROOT / "backend/services/data_crawler/requirements.txt").read_text(encoding="utf-8")

        self.assertIn("fastapi==", requirements)
        self.assertIn("uvicorn[standard]==", requirements)
        self.assertIn("prometheus-client==", requirements)

    def test_prometheus_scrapes_data_crawler(self) -> None:
        prometheus = (self.ROOT / "infra/prometheus/prometheus.yml").read_text(encoding="utf-8")
        compose = (self.ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("job_name: 'data-crawler'", prometheus)
        self.assertIn("data-crawler:8000", prometheus)
        self.assertIn("stock_platform_data_crawler", compose)
        self.assertIn("healthcheck:", compose)


if __name__ == "__main__":
    unittest.main()
