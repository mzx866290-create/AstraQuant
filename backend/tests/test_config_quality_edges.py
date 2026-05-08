from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from backend.shared import config


class RuntimeConfigQualityTests(unittest.TestCase):
    def test_app_env_and_production_detection_follow_app_env_then_environment(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(config.app_env(), "development")
            self.assertFalse(config.is_production())

        with patch.dict("os.environ", {"ENVIRONMENT": "production"}, clear=True):
            self.assertEqual(config.app_env(), "production")
            self.assertTrue(config.is_production())

        with patch.dict("os.environ", {"APP_ENV": "prod", "ENVIRONMENT": "development"}, clear=True):
            self.assertEqual(config.app_env(), "prod")
            self.assertTrue(config.is_production())

        with patch.dict("os.environ", {"APP_ENV": "staging"}, clear=True):
            self.assertFalse(config.is_production())

    def test_placeholder_detection_handles_none_trimmed_values_and_extra_list(self) -> None:
        self.assertTrue(config.is_placeholder(None))
        self.assertTrue(config.is_placeholder(""))
        self.assertTrue(config.is_placeholder("changeme"))
        self.assertTrue(config.is_placeholder(config.DEFAULT_JWT_SECRET))
        self.assertTrue(config.is_placeholder("custom-placeholder", extra={"custom-placeholder"}))
        self.assertFalse(config.is_placeholder("real-secret-value"))

    def test_fernet_key_shape_validation_is_strict_about_base64_and_decoded_length(self) -> None:
        valid = base64.urlsafe_b64encode(b"1" * 32).decode("ascii")
        too_short = base64.urlsafe_b64encode(b"1" * 31).decode("ascii")

        self.assertTrue(config.looks_like_fernet_key(valid))
        self.assertFalse(config.looks_like_fernet_key(too_short))
        self.assertFalse(config.looks_like_fernet_key("not-base64!!"))
        self.assertFalse(config.looks_like_fernet_key(""))
        self.assertFalse(config.looks_like_fernet_key(None))

    def test_validate_production_settings_noops_outside_production(self) -> None:
        unsafe_dev_env = {
            "APP_ENV": "development",
            "JWT_SECRET": "",
            "DB_PASS": "changeme",
            "DB_HOST": "localhost",
            "AUTH_REQUIRED": "false",
            "USE_SQLITE": "true",
            "AI_ENCRYPTION_KEY": "",
        }

        with patch.dict("os.environ", unsafe_dev_env, clear=True):
            config.validate_production_settings("unit-dev", require_ai_encryption=True)

    def test_validate_production_settings_collects_ai_key_placeholder_and_valid_key_paths(self) -> None:
        base_env = {
            "APP_ENV": "production",
            "JWT_SECRET": "prod-secret-with-at-least-32-characters",
            "DB_PASS": "prod-db-password",
            "DB_HOST": "postgres",
            "AUTH_REQUIRED": "true",
            "USE_SQLITE": "false",
        }

        with patch.dict("os.environ", {**base_env, "AI_ENCRYPTION_KEY": "test-ai-key"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "AI_ENCRYPTION_KEY must be configured"):
                config.validate_production_settings("analysis-service", require_ai_encryption=True)

        valid = base64.urlsafe_b64encode(b"2" * 32).decode("ascii")
        with patch.dict("os.environ", {**base_env, "AI_ENCRYPTION_KEY": valid}, clear=True):
            config.validate_production_settings("analysis-service", require_ai_encryption=True)

    def test_fastapi_docs_kwargs_disable_docs_only_in_production(self) -> None:
        with patch.dict("os.environ", {"APP_ENV": "production"}, clear=True):
            self.assertEqual(config.fastapi_docs_kwargs(), {"docs_url": None, "redoc_url": None, "openapi_url": None})

        with patch.dict("os.environ", {"APP_ENV": "development"}, clear=True):
            self.assertEqual(
                config.fastapi_docs_kwargs(),
                {
                    "docs_url": "/api/v1/docs",
                    "redoc_url": "/api/v1/redoc",
                    "openapi_url": "/api/v1/openapi.json",
                },
            )


if __name__ == "__main__":
    unittest.main()
