from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
import unittest

from fastapi import HTTPException, status
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text


@contextmanager
def _isolated_module(name: str):
    original = sys.modules.get(name)
    sys.modules.pop(name, None)
    try:
        module = importlib.import_module(name)
        yield module
    finally:
        sys.modules.pop(name, None)
        if original is not None:
            sys.modules[name] = original


def _call_default(column):
    return column.default.arg(None)


class SharedModelsQualityTests(unittest.TestCase):
    def test_models_reload_registers_expected_tables_and_core_column_contracts(self) -> None:
        with _isolated_module("backend.shared.models") as models:
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

            self.assertEqual(set(models.Base.metadata.tables), expected_tables)

            self.assertIsInstance(models.Stock.__table__.c.symbol.type, String)
            self.assertEqual(models.Stock.__table__.c.symbol.type.length, 20)
            self.assertIsInstance(models.Stock.__table__.c.market.type, String)
            self.assertEqual(models.Stock.__table__.c.market.type.length, 10)
            self.assertIsInstance(models.Stock.__table__.c.is_active.type, Boolean)
            self.assertTrue(models.Stock.__table__.c.is_active.default.arg)

            self.assertIsInstance(models.User.__table__.c.username.type, String)
            self.assertEqual(models.User.__table__.c.username.type.length, 50)
            self.assertEqual(models.User.__table__.c.role.default.arg, "free")
            self.assertIsInstance(models.User.__table__.c.created_at.type, DateTime)

            self.assertEqual(
                [(constraint.name, tuple(col.name for col in constraint.columns)) for constraint in models.Watchlist.__table__.constraints if constraint.name],
                [("uix_user_watchlist", ("user_id", "name"))],
            )
            self.assertEqual(
                [(constraint.name, tuple(col.name for col in constraint.columns)) for constraint in models.WatchlistItem.__table__.constraints if constraint.name],
                [("uix_watchlist_stock", ("watchlist_id", "stock_id"))],
            )

            self.assertIsInstance(models.PriceAlert.__table__.c.threshold.type, Float)
            self.assertIsInstance(models.UserActivityLog.__table__.c.created_at.type, DateTime)

            self.assertIsInstance(models.AIModel.__table__.c.provider.type, String)
            self.assertIsInstance(models.AIModel.__table__.c.api_key_encrypted.type, Text)
            self.assertIsInstance(models.AIModel.__table__.c.config.type, JSON)
            self.assertEqual(models.AIModel.__table__.c.allowed_roles.default.arg, "free,premium,admin")

            self.assertIsInstance(models.AIUsageLog.__table__.c.total_tokens.type, Integer)
            self.assertEqual(models.AIUsageLog.__table__.c.status.default.arg, "success")
            self.assertEqual(models.AIUsageLog.__table__.c.cost.default.arg, 0.0)

            self.assertEqual(
                [(constraint.name, tuple(col.name for col in constraint.columns)) for constraint in models.UserQuota.__table__.constraints if constraint.name],
                [("uix_user_quota", ("user_id",))],
            )

            self.assertIsInstance(models.CompanyAnnouncement.__table__.c.announce_date.type, DateTime)
            self.assertIsInstance(models.FinancialReport.__table__.c.report_date.type, DateTime)
            self.assertIsInstance(models.CrawlStatus.__table__.c.finished_at.type, DateTime)
            self.assertEqual(
                [(constraint.name, tuple(col.name for col in constraint.columns)) for constraint in models.CompanyAnnouncement.__table__.constraints if constraint.name],
                [("uix_announcement", ("stock_symbol", "title", "announce_date"))],
            )
            self.assertEqual(
                [(constraint.name, tuple(col.name for col in constraint.columns)) for constraint in models.FinancialReport.__table__.constraints if constraint.name],
                [("uix_financial", ("stock_symbol", "report_date"))],
            )
            self.assertEqual(
                [(constraint.name, tuple(col.name for col in constraint.columns)) for constraint in models.CrawlStatus.__table__.constraints if constraint.name],
                [("uix_crawl_status_latest", ("stock_symbol", "data_type"))],
            )
            self.assertEqual(
                [(constraint.name, tuple(col.name for col in constraint.columns)) for constraint in models.StockNews.__table__.constraints if constraint.name],
                [("uix_stock_news", ("stock_symbol", "title", "publish_time"))],
            )

    def test_models_reload_keeps_timestamp_defaults_and_index_contracts(self) -> None:
        with _isolated_module("backend.shared.models") as models:
            self.assertIsInstance(_call_default(models.Stock.__table__.c.updated_at), type(models.datetime.now(models.timezone.utc)))
            self.assertIsInstance(_call_default(models.User.__table__.c.updated_at), type(models.datetime.now(models.timezone.utc)))
            self.assertIsInstance(_call_default(models.Watchlist.__table__.c.created_at), type(models.datetime.now(models.timezone.utc)))
            self.assertIsInstance(_call_default(models.AIModel.__table__.c.created_at), type(models.datetime.now(models.timezone.utc)))
            self.assertIsInstance(_call_default(models.AIUsageLog.__table__.c.created_at), type(models.datetime.now(models.timezone.utc)))
            self.assertIsInstance(_call_default(models.UserQuota.__table__.c.last_reset_daily), type(models.datetime.now(models.timezone.utc)))
            self.assertIsInstance(_call_default(models.CompanyAnnouncement.__table__.c.created_at), type(models.datetime.now(models.timezone.utc)))
            self.assertIsInstance(_call_default(models.FinancialReport.__table__.c.created_at), type(models.datetime.now(models.timezone.utc)))
            self.assertIsInstance(_call_default(models.CrawlStatus.__table__.c.started_at), type(models.datetime.now(models.timezone.utc)))
            self.assertIsInstance(_call_default(models.StockNews.__table__.c.created_at), type(models.datetime.now(models.timezone.utc)))


class SharedExceptionsQualityTests(unittest.TestCase):
    def test_exceptions_reload_preserves_domain_codes_and_http_helpers(self) -> None:
        with _isolated_module("backend.shared.exceptions") as exceptions:
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

            helper_cases = (
                (exceptions.raise_unauthorized, status.HTTP_401_UNAUTHORIZED, None),
                (exceptions.raise_forbidden, status.HTTP_403_FORBIDDEN, None),
                (lambda: exceptions.raise_not_found("Stock"), status.HTTP_404_NOT_FOUND, "Stock"),
                (lambda: exceptions.raise_bad_request("bad request"), status.HTTP_400_BAD_REQUEST, "bad request"),
                (lambda: exceptions.raise_internal_error("boom"), status.HTTP_500_INTERNAL_SERVER_ERROR, "boom"),
            )

            for helper, expected_status, expected_detail in helper_cases:
                with self.subTest(status=expected_status):
                    with self.assertRaises(HTTPException) as raised:
                        helper()
                    self.assertEqual(raised.exception.status_code, expected_status)
                    if expected_detail is not None:
                        self.assertIn(expected_detail, str(raised.exception.detail))

            with self.assertRaises(HTTPException) as unauthorized:
                exceptions.raise_unauthorized()
            self.assertEqual(unauthorized.exception.headers, {"WWW-Authenticate": "Bearer"})


if __name__ == "__main__":
    unittest.main()
