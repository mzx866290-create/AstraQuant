from __future__ import annotations

import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.services.user_service.app.api.v1.watchlist_routes import AddItemRequest, add_to_watchlist
from backend.shared.models import Base, Stock, User, Watchlist, WatchlistItem
from backend.shared.security import hash_password


class WatchlistAddMissingStockTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

    def _session_with_watchlist(self):
        db = self.Session()
        user = User(
            username="unit",
            email="unit@example.com",
            password_hash=hash_password("UnitPass123"),
            role="free",
            is_active=True,
        )
        db.add(user)
        db.flush()
        watchlist = Watchlist(user_id=user.id, name="默认分组")
        db.add(watchlist)
        db.commit()
        db.refresh(user)
        db.refresh(watchlist)
        return db, user, watchlist

    async def test_add_symbol_creates_minimal_stock_when_master_data_missing(self) -> None:
        db, user, watchlist = self._session_with_watchlist()
        try:
            result = await add_to_watchlist(
                watchlist.id,
                AddItemRequest(symbol="600519.SH", name="贵州茅台", sector="食品饮料"),
                user,
                db,
            )

            stock = db.query(Stock).filter(Stock.symbol == "600519").one()
            item = db.query(WatchlistItem).filter(WatchlistItem.watchlist_id == watchlist.id).one()
            self.assertEqual(stock.market, "SH")
            self.assertEqual(stock.name, "贵州茅台")
            self.assertEqual(stock.sector, "食品饮料")
            self.assertEqual(item.stock_id, stock.id)
            self.assertEqual(result["symbol"], "600519.SH")
        finally:
            db.close()

    async def test_add_symbol_rejects_invalid_code(self) -> None:
        db, user, watchlist = self._session_with_watchlist()
        try:
            with self.assertRaises(HTTPException) as raised:
                await add_to_watchlist(
                    watchlist.id,
                    AddItemRequest(symbol="ABC"),
                    user,
                    db,
                )

            self.assertEqual(raised.exception.status_code, 400)
        finally:
            db.close()

    async def test_add_symbol_reuses_existing_stock(self) -> None:
        db, user, watchlist = self._session_with_watchlist()
        try:
            db.add(Stock(symbol="000858.SZ", name="五粮液", market="SZ", sector="食品饮料"))
            db.commit()

            result = await add_to_watchlist(
                watchlist.id,
                AddItemRequest(symbol="000858"),
                user,
                db,
            )

            self.assertEqual(db.query(Stock).count(), 1)
            self.assertEqual(result["symbol"], "000858.SZ")
            self.assertEqual(result["name"], "五粮液")
        finally:
            db.close()

    async def test_add_symbol_enriches_placeholder_stock_name(self) -> None:
        db, user, watchlist = self._session_with_watchlist()
        try:
            db.add(Stock(symbol="300750", name="300750", market="SZ"))
            db.commit()

            result = await add_to_watchlist(
                watchlist.id,
                AddItemRequest(symbol="300750", name="宁德时代", sector="新能源"),
                user,
                db,
            )

            stock = db.query(Stock).filter(Stock.symbol == "300750").one()
            self.assertEqual(stock.name, "宁德时代")
            self.assertEqual(stock.sector, "新能源")
            self.assertEqual(result["name"], "宁德时代")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
