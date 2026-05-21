from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.shared.models import Base, Stock


class FakeCache:
    def __init__(self) -> None:
        self.get_calls = []
        self.set_calls = []

    async def get(self, category: str, key: str):
        self.get_calls.append((category, key))
        return None

    async def set(self, category: str, key: str, value):
        self.set_calls.append((category, key, value))


class StockSearchSuffixTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

    def test_search_accepts_suffixed_symbol_when_db_stores_plain_code(self) -> None:
        from backend.services.market_service.app.api.v1 import search

        db = self.Session()
        cache = FakeCache()
        try:
            db.add(Stock(symbol="600519", name="贵州茅台", market="SH", is_active=True))
            db.commit()

            with patch("backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)), patch(
                "backend.shared.database.SessionLocal", return_value=db
            ):
                result = asyncio.run(search.search_stocks("600519.SH", market="SH", limit=10))

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["results"][0]["symbol"], "600519.SH")
            self.assertEqual(result["results"][0]["name"], "贵州茅台")
            self.assertEqual(cache.get_calls, [("search_result", "v4:600519.SH:SH:10")])
            self.assertEqual(cache.set_calls[0][0], "search_result")
        finally:
            db.close()

    def test_search_accepts_prefixed_symbol_when_db_stores_plain_code(self) -> None:
        from backend.services.market_service.app.api.v1 import search

        db = self.Session()
        cache = FakeCache()
        try:
            db.add(Stock(symbol="000858", name="五粮液", market="SZ", is_active=True))
            db.commit()

            with patch("backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)), patch(
                "backend.shared.database.SessionLocal", return_value=db
            ):
                result = asyncio.run(search.search_stocks("SZ000858", market="sz", limit=10))

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["results"][0]["symbol"], "000858.SZ")
            self.assertEqual(result["results"][0]["name"], "五粮液")
            self.assertEqual(cache.get_calls, [("search_result", "v4:SZ000858:SZ:10")])
        finally:
            db.close()

    def test_search_returns_current_bj_symbol_when_db_stores_prefixed_code(self) -> None:
        from backend.services.market_service.app.api.v1 import search

        db = self.Session()
        cache = FakeCache()
        try:
            db.add(Stock(symbol="BJ430047", name="Unit BJ", market="BJ", is_active=True))
            db.commit()

            with patch("backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)), patch(
                "backend.shared.database.SessionLocal", return_value=db
            ):
                result = asyncio.run(search.search_stocks("430047.BJ", market="BJ", limit=10))

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["results"][0]["symbol"], "920047.BJ")
            self.assertEqual(result["results"][0]["market"], "BJ")
        finally:
            db.close()

    def test_search_prefers_current_920_bj_symbol_for_legacy_bj_code(self) -> None:
        from backend.services.market_service.app.api.v1 import search

        db = self.Session()
        cache = FakeCache()
        try:
            db.add_all([
                Stock(symbol="BJ430047", name="Unit BJ", market="BJ", is_active=True),
                Stock(symbol="920047", name="Unit BJ", market="BJ", is_active=True),
            ])
            db.commit()

            with patch("backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)), patch(
                "backend.shared.database.SessionLocal", return_value=db
            ):
                result = asyncio.run(search.search_stocks("430047", market="BJ", limit=10))

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["results"][0]["symbol"], "920047.BJ")
            self.assertEqual(result["results"][0]["market"], "BJ")
        finally:
            db.close()

    def test_search_falls_back_to_current_920_symbol_for_exact_bj_code_missing_from_db(self) -> None:
        from backend.services.market_service.app.api.v1 import search

        db = self.Session()
        cache = FakeCache()
        try:
            with patch("backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)), patch(
                "backend.shared.database.SessionLocal", return_value=db
            ), patch(
                "backend.services.market_service.app.api.v1.stocks._fetch_public_stock_info",
                return_value={"name": "Unit BJ", "source": "unit"},
            ) as fetch_info:
                result = asyncio.run(search.search_stocks("BJ430047", market="BJ", limit=10))

            fetch_info.assert_called_once_with("920047", "BJ")
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["results"][0]["symbol"], "920047.BJ")
            self.assertEqual(result["results"][0]["name"], "Unit BJ")
            self.assertEqual(result["results"][0]["market"], "BJ")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
