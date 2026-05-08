from __future__ import annotations

import importlib
import os
import sys
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException, status
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.pool import QueuePool, StaticPool


class SharedDatabaseConfigTests(unittest.TestCase):
    MODULE_NAME = "backend.shared.database"
    ENV_KEYS = (
        "APP_ENV",
        "ENVIRONMENT",
        "USE_SQLITE",
        "DB_PATH",
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_PASS",
        "DB_NAME",
        "LOG_LEVEL",
    )

    def import_database(self, env: dict[str, str], *, missing: tuple[str, ...] = ()):
        original = sys.modules.pop(self.MODULE_NAME, None)
        env_patch = {key: os.environ.get(key, "") for key in self.ENV_KEYS}
        env_patch.update(env)
        for key in missing:
            env_patch.pop(key, None)

        with patch.dict(os.environ, env_patch, clear=False), patch(
            "sqlalchemy.create_engine", return_value=Mock(name="engine")
        ) as create_engine:
            try:
                module = importlib.import_module(self.MODULE_NAME)
            finally:
                sys.modules.pop(self.MODULE_NAME, None)
                if original is not None:
                    sys.modules[self.MODULE_NAME] = original

        return module, create_engine

    def test_sqlite_fallback_uses_static_pool_without_required_db_credentials(self) -> None:
        module, create_engine = self.import_database(
            {
                "APP_ENV": "development",
                "USE_SQLITE": "true",
                "DB_PATH": "unit-test.db",
                "DB_USER": "",
                "DB_PASS": "",
                "LOG_LEVEL": "INFO",
            }
        )

        self.assertTrue(module.USE_SQLITE)
        self.assertTrue(module.DATABASE_URL.startswith("sqlite:///"))
        self.assertTrue(module.DATABASE_URL.endswith("unit-test.db"))
        create_engine.assert_called_once()
        _, kwargs = create_engine.call_args
        self.assertEqual(kwargs["connect_args"], {"check_same_thread": False})
        self.assertIs(kwargs["poolclass"], StaticPool)
        self.assertFalse(kwargs["echo"])

    def test_production_forbids_sqlite_even_when_explicitly_requested(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "USE_SQLITE=true is forbidden in production"):
            self.import_database({"APP_ENV": "production", "USE_SQLITE": "true"})

    def test_postgres_branch_requires_user_and_password(self) -> None:
        with self.assertRaisesRegex(ValueError, "DB_USER, DB_PASS"):
            self.import_database(
                {
                    "APP_ENV": "development",
                    "USE_SQLITE": "false",
                    "DB_HOST": "db.internal",
                    "DB_USER": "",
                    "DB_PASS": "",
                }
            )

    def test_postgres_branch_builds_url_and_queue_pool_options(self) -> None:
        module, create_engine = self.import_database(
            {
                "APP_ENV": "development",
                "USE_SQLITE": "false",
                "DB_HOST": "db.internal",
                "DB_PORT": "15432",
                "DB_NAME": "stocks_test",
                "DB_USER": "reader",
                "DB_PASS": "secret",
                "LOG_LEVEL": "DEBUG",
            }
        )

        self.assertFalse(module.USE_SQLITE)
        self.assertEqual(module.DATABASE_URL, "postgresql://reader:secret@db.internal:15432/stocks_test")
        create_engine.assert_called_once()
        _, kwargs = create_engine.call_args
        self.assertIs(kwargs["poolclass"], QueuePool)
        self.assertEqual(kwargs["pool_size"], 20)
        self.assertEqual(kwargs["max_overflow"], 40)
        self.assertTrue(kwargs["pool_pre_ping"])
        self.assertTrue(kwargs["echo"])

    def test_get_db_closes_session_after_generator_is_exhausted(self) -> None:
        module, _ = self.import_database(
            {
                "APP_ENV": "development",
                "USE_SQLITE": "true",
                "DB_PATH": "unit-test.db",
            }
        )
        session = Mock(name="session")
        module.SessionLocal = Mock(return_value=session)

        db_generator = module.get_db()
        self.assertIs(next(db_generator), session)
        with self.assertRaises(StopIteration):
            next(db_generator)
        session.close.assert_called_once_with()


class SharedExceptionsTests(unittest.TestCase):
    @staticmethod
    def import_exceptions():
        return importlib.reload(importlib.import_module("backend.shared.exceptions"))

    def test_domain_exceptions_preserve_message_and_code_contracts(self) -> None:
        exceptions = self.import_exceptions()

        cases = (
            (exceptions.StockPlatformException("base", "BASE"), "base", "BASE"),
            (exceptions.AuthenticationException("auth failed"), "auth failed", "AUTH_ERROR"),
            (exceptions.AuthorizationException("no access"), "no access", "AUTHORIZATION_ERROR"),
            (exceptions.ValidationException("bad input"), "bad input", "VALIDATION_ERROR"),
            (exceptions.DataSourceException("source down"), "source down", "DATA_SOURCE_ERROR"),
            (exceptions.DatabaseException("db down"), "db down", "DATABASE_ERROR"),
            (exceptions.CacheException("cache down"), "cache down", "CACHE_ERROR"),
        )

        for exc, message, code in cases:
            with self.subTest(code=code):
                self.assertEqual(exc.message, message)
                self.assertEqual(exc.code, code)
                self.assertEqual(str(exc), message)

        not_found = exceptions.ResourceNotFoundException("Stock")
        self.assertEqual(not_found.code, "RESOURCE_NOT_FOUND")
        self.assertIn("Stock", not_found.message)

    def test_http_exception_helpers_map_to_expected_status_codes(self) -> None:
        exceptions = self.import_exceptions()

        helper_cases = (
            (exceptions.raise_unauthorized, status.HTTP_401_UNAUTHORIZED),
            (exceptions.raise_forbidden, status.HTTP_403_FORBIDDEN),
            (lambda: exceptions.raise_not_found("Stock"), status.HTTP_404_NOT_FOUND),
            (lambda: exceptions.raise_bad_request("bad request"), status.HTTP_400_BAD_REQUEST),
            (lambda: exceptions.raise_internal_error("boom"), status.HTTP_500_INTERNAL_SERVER_ERROR),
        )

        for helper, expected_status in helper_cases:
            with self.subTest(status=expected_status):
                with self.assertRaises(HTTPException) as raised:
                    helper()
                self.assertEqual(raised.exception.status_code, expected_status)

        with self.assertRaises(HTTPException) as unauthorized:
            exceptions.raise_unauthorized()
        self.assertEqual(unauthorized.exception.headers, {"WWW-Authenticate": "Bearer"})

        for helper, expected_detail in (
            (lambda: exceptions.raise_bad_request("bad request"), "bad request"),
            (lambda: exceptions.raise_internal_error("boom"), "boom"),
        ):
            with self.subTest(detail=expected_detail):
                with self.assertRaises(HTTPException) as raised:
                    helper()
                self.assertEqual(raised.exception.detail, expected_detail)


class SharedModelsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.models = importlib.reload(importlib.import_module("backend.shared.models"))

    def assert_column_contract(
        self,
        model,
        column_name: str,
        column_type,
        *,
        nullable: bool | None = None,
        unique: bool | None = None,
        index: bool | None = None,
        default: object = None,
        has_default: bool = False,
        foreign_key: str | None = None,
    ) -> None:
        column = model.__table__.c[column_name]
        self.assertIsInstance(column.type, column_type)
        if nullable is not None:
            self.assertEqual(column.nullable, nullable)
        if unique is not None:
            self.assertEqual(bool(column.unique), unique)
        if index is not None:
            self.assertEqual(bool(column.index), index)
        if has_default:
            self.assertIsNotNone(column.default)
            self.assertEqual(column.default.arg, default)
        if foreign_key is not None:
            self.assertEqual(next(iter(column.foreign_keys)).target_fullname, foreign_key)

    def test_core_table_names_are_registered_in_metadata(self) -> None:
        expected_tables = {
            "stocks",
            "users",
            "watchlists",
            "watchlist_items",
            "price_alerts",
            "user_activity_logs",
            "ai_models",
            "ai_usage_logs",
            "user_quotas",
            "company_announcements",
            "financial_reports",
            "crawl_status",
            "stock_news",
        }

        self.assertEqual(set(self.models.Base.metadata.tables), expected_tables)

    def test_stock_and_user_columns_keep_identity_and_default_contracts(self) -> None:
        self.assert_column_contract(
            self.models.Stock, "symbol", String, nullable=False, unique=True, index=True
        )
        self.assertEqual(self.models.Stock.__table__.c.symbol.type.length, 20)
        self.assert_column_contract(self.models.Stock, "market", String, nullable=False, index=True)
        self.assert_column_contract(self.models.Stock, "is_active", Boolean, has_default=True, default=True)
        self.assert_column_contract(self.models.Stock, "updated_at", DateTime, nullable=True)

        self.assert_column_contract(
            self.models.User, "username", String, nullable=False, unique=True, index=True
        )
        self.assertEqual(self.models.User.__table__.c.username.type.length, 50)
        self.assert_column_contract(self.models.User, "email", String, nullable=False, unique=True)
        self.assert_column_contract(self.models.User, "role", String, has_default=True, default="free")
        self.assert_column_contract(self.models.User, "created_at", DateTime)

    def test_user_owned_tables_keep_foreign_keys_and_uniqueness(self) -> None:
        self.assert_column_contract(
            self.models.Watchlist, "user_id", Integer, nullable=False, foreign_key="users.id"
        )
        self.assertEqual(
            [(constraint.name, tuple(col.name for col in constraint.columns)) for constraint in self.models.Watchlist.__table__.constraints if constraint.name],
            [("uix_user_watchlist", ("user_id", "name"))],
        )

        self.assert_column_contract(
            self.models.WatchlistItem,
            "watchlist_id",
            Integer,
            nullable=False,
            foreign_key="watchlists.id",
        )
        self.assert_column_contract(
            self.models.WatchlistItem, "stock_id", Integer, nullable=False, foreign_key="stocks.id"
        )
        self.assertEqual(
            [(constraint.name, tuple(col.name for col in constraint.columns)) for constraint in self.models.WatchlistItem.__table__.constraints if constraint.name],
            [("uix_watchlist_stock", ("watchlist_id", "stock_id"))],
        )

        self.assert_column_contract(
            self.models.PriceAlert, "threshold", Float, nullable=False
        )
        self.assert_column_contract(
            self.models.PriceAlert, "stock_id", Integer, nullable=False, foreign_key="stocks.id"
        )

    def test_ai_and_quota_tables_keep_operational_contracts(self) -> None:
        self.assert_column_contract(self.models.AIModel, "provider", String, nullable=False)
        self.assert_column_contract(self.models.AIModel, "model_id", String, nullable=False)
        self.assert_column_contract(self.models.AIModel, "api_key_encrypted", Text, nullable=False)
        self.assert_column_contract(self.models.AIModel, "config", JSON, nullable=True)
        self.assert_column_contract(self.models.AIModel, "is_active", Boolean, has_default=True, default=True)
        self.assert_column_contract(
            self.models.AIModel,
            "allowed_roles",
            String,
            has_default=True,
            default="free,premium,admin",
        )

        self.assert_column_contract(self.models.AIUsageLog, "user_id", Integer, nullable=False, index=True)
        self.assert_column_contract(self.models.AIUsageLog, "model_id", Integer, nullable=False, index=True)
        self.assert_column_contract(self.models.AIUsageLog, "status", String, has_default=True, default="success")
        self.assert_column_contract(self.models.AIUsageLog, "cost", Float, has_default=True, default=0.0)

        self.assert_column_contract(self.models.UserQuota, "user_id", Integer, nullable=False, index=True)
        self.assert_column_contract(self.models.UserQuota, "daily_limit", Integer, has_default=True, default=10)
        self.assert_column_contract(self.models.UserQuota, "monthly_limit", Integer, has_default=True, default=100)
        self.assertEqual(
            [(constraint.name, tuple(col.name for col in constraint.columns)) for constraint in self.models.UserQuota.__table__.constraints if constraint.name],
            [("uix_user_quota", ("user_id",))],
        )

    def test_market_data_tables_keep_indexes_and_unique_constraints(self) -> None:
        self.assert_column_contract(
            self.models.CompanyAnnouncement, "stock_symbol", String, nullable=False, index=True
        )
        self.assert_column_contract(
            self.models.CompanyAnnouncement, "announce_date", DateTime, nullable=False, index=True
        )
        self.assert_column_contract(
            self.models.FinancialReport, "stock_symbol", String, nullable=False, index=True
        )
        self.assert_column_contract(
            self.models.FinancialReport, "report_date", DateTime, nullable=False, index=True
        )
        self.assert_column_contract(
            self.models.CrawlStatus, "data_type", String, nullable=False, index=True
        )
        self.assert_column_contract(
            self.models.CrawlStatus, "finished_at", DateTime, nullable=False, index=True
        )
        self.assert_column_contract(
            self.models.StockNews, "publish_time", DateTime, nullable=False, index=True
        )
        self.assert_column_contract(self.models.StockNews, "sentiment_score", Float, has_default=True, default=0.0)
        self.assert_column_contract(self.models.StockNews, "keywords", JSON, nullable=True)

        named_constraints = {
            table.name: {constraint.name for constraint in table.constraints if constraint.name}
            for table in self.models.Base.metadata.sorted_tables
        }
        self.assertIn("uix_announcement", named_constraints["company_announcements"])
        self.assertIn("uix_financial", named_constraints["financial_reports"])
        self.assertIn("uix_crawl_status_latest", named_constraints["crawl_status"])
        self.assertIn("uix_stock_news", named_constraints["stock_news"])


if __name__ == "__main__":
    unittest.main()
