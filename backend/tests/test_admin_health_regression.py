from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient


DEV_AUTH_ENV = {
    "APP_ENV": "development",
    "AUTH_REQUIRED": "false",
    "JWT_SECRET": "test-secret-with-at-least-32-characters",
    "USE_SQLITE": "true",
}


class DevAdminGuardRegressionTests(unittest.TestCase):
    def _reload_auth(self):
        import backend.shared.auth as auth

        return importlib.reload(auth)

    def test_require_admin_rejects_dev_admin_unless_explicitly_allowed(self) -> None:
        env = {**DEV_AUTH_ENV, "ALLOW_DEV_ADMIN": "false"}
        with patch.dict("os.environ", env, clear=True):
            auth = self._reload_auth()
            checker = auth.require_admin()
            dev_admin = SimpleNamespace(role="admin")

            with self.assertRaises(HTTPException) as raised:
                asyncio.run(checker(current_user=dev_admin))

        self.assertEqual(raised.exception.status_code, 403)
        self.assertIn("ALLOW_DEV_ADMIN=true", str(raised.exception.detail))

    def test_require_admin_allows_dev_admin_when_explicitly_enabled(self) -> None:
        env = {**DEV_AUTH_ENV, "ALLOW_DEV_ADMIN": "true"}
        with patch.dict("os.environ", env, clear=True):
            auth = self._reload_auth()
            checker = auth.require_admin()
            dev_admin = SimpleNamespace(role="admin")

            current_user = asyncio.run(checker(current_user=dev_admin))

        self.assertIs(current_user, dev_admin)


class PublicHealthRegressionTests(unittest.TestCase):
    SERVICE_MODULES = (
        "backend.services.analysis_service.app.main",
        "backend.services.data_crawler.app.main",
        "backend.services.market_service.app.main",
        "backend.services.user_service.app.main",
    )

    SAFE_ENV = {
        "APP_ENV": "development",
        "AUTH_REQUIRED": "true",
        "JWT_SECRET": "test-secret-with-at-least-32-characters",
        "USE_SQLITE": "true",
        "AI_ENCRYPTION_KEY": "test-ai-key",
        "DATA_CRAWLER_ENABLE_SCHEDULER": "false",
    }

    def _import_app(self, module_name: str):
        module = self._import_module(module_name)
        return module.app

    def _import_module(self, module_name: str):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app.") or name == "api" or name.startswith("api."):
                sys.modules.pop(name, None)
        module = importlib.import_module(module_name)
        return importlib.reload(module)

    def test_public_health_does_not_expose_internal_urls_or_error_details(self) -> None:
        with patch.dict("os.environ", self.SAFE_ENV, clear=False):
            for module_name in self.SERVICE_MODULES:
                with self.subTest(service=module_name):
                    app = self._import_app(module_name)
                    response = TestClient(app).get("/health")

                    self.assertEqual(response.status_code, 200)
                    body = response.json()
                    self.assertEqual(body.get("status"), "ok")
                    self.assertNotIn("url", body)
                    self.assertNotIn("error", body)
                    self.assertNotIn("detail", body)
                    self.assertNotIn("localhost", str(body).lower())
                    self.assertNotIn("127.0.0.1", str(body))
                    self.assertNotIn("postgres", str(body).lower())
                    self.assertNotIn("redis", str(body).lower())

    def test_public_analysis_health_redacts_internal_probe_details(self) -> None:
        with patch.dict("os.environ", self.SAFE_ENV, clear=False):
            module = self._import_module("backend.services.analysis_service.app.main")

            async def fake_collect_service_health() -> list[dict]:
                return [
                    {
                        "service": "market-service",
                        "status": "error",
                        "url": "http://127.0.0.1:8001/health",
                        "error": "postgres refused connection",
                    },
                    {
                        "service": "user-service",
                        "status": "ok",
                        "url": "http://localhost:8002/health",
                    },
                ]

            with patch.object(module, "_collect_service_health", fake_collect_service_health):
                response = TestClient(module.app).get("/api/v1/analysis/public-health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["services"], [
            {"service": "market-service", "status": "error"},
            {"service": "user-service", "status": "ok"},
        ])
        self.assertNotIn("url", str(body).lower())
        self.assertNotIn("refused", str(body).lower())
        self.assertNotIn("127.0.0.1", str(body))
        self.assertNotIn("localhost", str(body).lower())
        self.assertNotIn("postgres", str(body).lower())


if __name__ == "__main__":
    unittest.main()
