from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]


PRODUCTION_SAFE_ENV = {
    "APP_ENV": "production",
    "JWT_SECRET": "prod-secret-with-at-least-32-characters",
    "DB_PASS": "prod-db-password",
    "DB_HOST": "postgres",
    "AUTH_REQUIRED": "true",
    "USE_SQLITE": "false",
    "AI_ENCRYPTION_KEY": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
}


class ComposeSecretConfigTests(unittest.TestCase):
    def test_compose_requires_db_password_without_weak_fallback(self) -> None:
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("POSTGRES_PASSWORD: ${DB_PASS:?", compose)
        self.assertNotIn("${DB_PASS:-changeme}", compose)

    def test_compose_requires_grafana_password_without_weak_fallback(self) -> None:
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASS:?", compose)
        self.assertNotIn("${GRAFANA_PASS:-admin}", compose)

    def test_env_example_does_not_ship_working_default_passwords(self) -> None:
        env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertNotIn("DB_PASS=changeme", env_example)
        self.assertNotIn("GRAFANA_PASS=admin", env_example)


class ProductionConfigGuardTests(unittest.TestCase):
    def test_production_settings_reject_unsafe_defaults(self) -> None:
        from backend.shared.config import validate_production_settings

        unsafe_env = {
            **PRODUCTION_SAFE_ENV,
            "JWT_SECRET": "your-super-secret-jwt-key-change-in-production",
            "DB_PASS": "changeme",
            "DB_HOST": "localhost",
            "AUTH_REQUIRED": "false",
            "USE_SQLITE": "true",
        }

        with patch.dict("os.environ", unsafe_env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "JWT_SECRET.*AUTH_REQUIRED.*DB_PASS.*USE_SQLITE.*DB_HOST"):
                validate_production_settings("unit-test-service")

    def test_analysis_service_requires_ai_encryption_in_production(self) -> None:
        from backend.shared.config import validate_production_settings

        env = {**PRODUCTION_SAFE_ENV, "AI_ENCRYPTION_KEY": ""}
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "AI_ENCRYPTION_KEY"):
                validate_production_settings("analysis-service", require_ai_encryption=True)

    def test_analysis_service_rejects_invalid_ai_encryption_key_format(self) -> None:
        from backend.shared.config import validate_production_settings

        env = {**PRODUCTION_SAFE_ENV, "AI_ENCRYPTION_KEY": "not-a-fernet-key"}
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "valid Fernet key"):
                validate_production_settings("analysis-service", require_ai_encryption=True)

    def test_safe_production_settings_pass(self) -> None:
        from backend.shared.config import validate_production_settings

        with patch.dict("os.environ", PRODUCTION_SAFE_ENV, clear=True):
            validate_production_settings("unit-test-service", require_ai_encryption=True)


class JwtSecretGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_modules = {name: sys.modules.get(name) for name in ("bcrypt", "jose")}
        fake_bcrypt = types.SimpleNamespace(
            gensalt=lambda: b"salt",
            hashpw=lambda password, salt: b"hashed",
            checkpw=lambda password, hashed: True,
        )
        fake_jwt = types.SimpleNamespace(
            encode=lambda payload, secret, algorithm: "encoded-token",
            decode=lambda token, secret, algorithms: {"sub": "1"},
        )
        fake_jose = types.SimpleNamespace(JWTError=Exception, jwt=fake_jwt)
        sys.modules["bcrypt"] = fake_bcrypt
        sys.modules["jose"] = fake_jose

    def tearDown(self) -> None:
        for name, module in self._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.modules.pop("backend.shared.security", None)

    def _reload_security(self):
        sys.modules.pop("backend.shared.security", None)
        import backend.shared.security as security

        return importlib.reload(security)

    def test_jwt_secret_is_required(self) -> None:
        with patch.dict("os.environ", {"APP_ENV": "development", "JWT_SECRET": ""}, clear=True):
            security = self._reload_security()
            with self.assertRaisesRegex(RuntimeError, "JWT_SECRET is required"):
                security.create_access_token({"sub": "1"})

    def test_production_rejects_default_jwt_secret(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "APP_ENV": "production",
                "JWT_SECRET": "dev-only-insecure-jwt-secret-change-me",
            },
            clear=True,
        ):
            security = self._reload_security()
            with self.assertRaisesRegex(RuntimeError, "unsafe default"):
                security.create_access_token({"sub": "1"})


class AIKeyEncryptionGuardTests(unittest.TestCase):
    def _reload_auth(self):
        sys.modules.pop("backend.shared.auth", None)
        import backend.shared.auth as auth

        return importlib.reload(auth)

    def test_encrypt_api_key_uses_derived_fallback_in_non_production(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "APP_ENV": "development",
                "JWT_SECRET": "dev-secret-with-at-least-32-characters",
                "AI_ENCRYPTION_KEY": "",
            },
            clear=True,
        ):
            auth = self._reload_auth()
            encrypted = auth.encrypt_api_key("sk-demo")

        self.assertNotEqual(encrypted, "sk-demo")
        self.assertEqual(len(encrypted) > 20, True)

    def test_decrypt_api_key_accepts_legacy_plaintext_in_non_production(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "APP_ENV": "development",
                "JWT_SECRET": "dev-secret-with-at-least-32-characters",
                "AI_ENCRYPTION_KEY": "",
            },
            clear=True,
        ):
            auth = self._reload_auth()
            decrypted = auth.decrypt_api_key("sk-legacy-plaintext")

        self.assertEqual(decrypted, "sk-legacy-plaintext")

    def test_decrypt_api_key_rejects_mismatched_explicit_key(self) -> None:
        env = {
            "APP_ENV": "development",
            "JWT_SECRET": "dev-secret-with-at-least-32-characters",
            "AI_ENCRYPTION_KEY": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        }
        with patch.dict("os.environ", env, clear=True):
            auth = self._reload_auth()
            encrypted = auth.encrypt_api_key("sk-demo")

        wrong_env = {
            **env,
            "AI_ENCRYPTION_KEY": "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXpBQkNERUY=",
        }
        with patch.dict("os.environ", wrong_env, clear=True):
            auth = self._reload_auth()
            with self.assertRaisesRegex(RuntimeError, "could not be decrypted"):
                auth.decrypt_api_key(encrypted)


class DataQualityFallbackTests(unittest.TestCase):
    def test_generated_fallback_market_data_is_not_marked_high_quality(self) -> None:
        from backend.services.analysis_service.engine.data_quality import DataQualityBuilder, build_data_grade

        stock_data = {
            "price": 10.0,
            "quote": {"source": "local-fallback", "open": 9.8, "high": 10.2, "low": 9.7, "volume": 1000},
            "quote_source": "local-fallback",
            "kline_source": "local-fallback",
            "kline_data": [{"date": "2026-05-06", "close": 10.0}],
        }

        quality = DataQualityBuilder.from_stock_data(stock_data)

        self.assertTrue(quality["quote"]["is_fallback"])
        self.assertIn("quote_from_kline_fallback", quality["quote"]["warnings"])
        self.assertNotEqual(quality["quote"]["confidence"], "high")
        self.assertTrue(quality["kline"]["is_fallback"])
        self.assertIn(build_data_grade(stock_data)["grade"], {"C", "D"})

    def test_synthetic_quote_from_kline_is_explicitly_marked(self) -> None:
        from backend.services.analysis_service.engine.data_quality import DataQualityBuilder

        stock_data = {
            "price": 10.0,
            "quote": {"source": "synthetic-from-kline", "price": 10.0, "synthetic": True},
            "quote_source": "synthetic-from-kline",
            "kline_source": "sina-secondary",
            "kline_data": [{"date": "2026-05-06", "close": 10.0}],
        }

        quality = DataQualityBuilder.from_stock_data(stock_data)

        self.assertEqual(quality["quote"]["source"], "synthetic-from-kline")
        self.assertTrue(quality["quote"]["is_fallback"])
        self.assertIn("quote_from_kline_fallback", quality["quote"]["warnings"])
        self.assertNotEqual(quality["quote"]["confidence"], "high")

    def test_secondary_kline_keeps_real_source_and_warns(self) -> None:
        from backend.services.analysis_service.engine.data_quality import DataQualityBuilder

        stock_data = {
            "price": 10.0,
            "quote": {"source": "sina_tencent", "price": 10.0, "open": 9.9, "volume": 1000},
            "quote_source": "sina_tencent",
            "kline_source": "eastmoney-secondary",
            "kline_data": [{"date": f"2026-04-{day:02d}", "close": 10.0 + day} for day in range(1, 22)],
        }

        quality = DataQualityBuilder.from_stock_data(stock_data)

        self.assertEqual(quality["kline"]["source"], "eastmoney-secondary")
        self.assertTrue(quality["kline"]["is_fallback"])
        self.assertIn("kline_secondary_source_used", quality["kline"]["warnings"])
        self.assertNotEqual(quality["kline"]["source"], "local-fallback")

    def test_financial_valuation_source_is_not_fallback_when_quote_missing(self) -> None:
        from backend.services.analysis_service.engine.data_quality import DataQualityBuilder

        stock_data = {
            "price": 0.0,
            "quote": {},
            "quote_source": "",
            "financial": {"source": "akshare-financial", "pe_ttm": 12.3, "pb": 1.4, "report_date": "2026-03-31"},
        }

        quality = DataQualityBuilder.from_stock_data(stock_data)

        self.assertEqual(quality["valuation"]["source"], "akshare-financial")
        self.assertFalse(quality["valuation"]["is_fallback"])
        self.assertEqual(quality["valuation"]["warnings"], [])


if __name__ == "__main__":
    unittest.main()
