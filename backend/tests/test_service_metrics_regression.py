from __future__ import annotations

import importlib
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class ServiceMetricsRegressionTests(unittest.TestCase):
    SERVICE_MODULES = (
        ("backend.services.market_service.app.main", "market-service"),
        ("backend.services.user_service.app.main", "user-service"),
        ("backend.services.analysis_service.app.main", "analysis-service"),
        ("backend.services.data_crawler.app.main", "data-crawler"),
    )

    SAFE_ENV = {
        "APP_ENV": "development",
        "AUTH_REQUIRED": "true",
        "JWT_SECRET": "test-secret-with-at-least-32-characters",
        "USE_SQLITE": "true",
        "AI_ENCRYPTION_KEY": "test-ai-key",
        "DATA_CRAWLER_ENABLE_SCHEDULER": "false",
    }

    def _import_module(self, module_name: str):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app.") or name == "api" or name.startswith("api."):
                sys.modules.pop(name, None)
        module = importlib.import_module(module_name)
        return importlib.reload(module)

    def test_metrics_endpoint_exposes_http_service_metrics(self) -> None:
        with patch.dict("os.environ", self.SAFE_ENV, clear=False):
            for module_name, service_name in self.SERVICE_MODULES:
                with self.subTest(service=service_name):
                    module = self._import_module(module_name)
                    client = TestClient(module.app)

                    response = client.get("/health")
                    self.assertEqual(response.status_code, 200)

                    metrics = client.get("/metrics")
                    self.assertEqual(metrics.status_code, 200)
                    body = metrics.text

                    self.assertIn("stock_platform_service_info", body)
                    self.assertIn("stock_platform_http_requests_total", body)
                    self.assertIn("stock_platform_http_request_duration_seconds", body)
                    self.assertIn("stock_platform_http_requests_in_progress", body)
                    self.assertIn(f'service="{service_name}"', body)
                    self.assertIn('path="/health"', body)


if __name__ == "__main__":
    unittest.main()
