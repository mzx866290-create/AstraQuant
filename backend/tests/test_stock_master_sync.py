from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.services.data_crawler.pipeline.stock_master import (
    StockMasterETL,
    normalize_stock_master_row,
)
from backend.shared.models import Base, Stock


class StockMasterSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

    def test_normalize_stock_master_row_filters_invalid_and_st_rows(self) -> None:
        self.assertIsNone(normalize_stock_master_row({"symbol": "ABC", "name": "Invalid"}))
        self.assertIsNone(normalize_stock_master_row({"symbol": "600001", "name": "ST Risk"}))

        row = normalize_stock_master_row(
            {"symbol": "600519.SH", "name": "贵州茅台", "market": "", "sector": "食品饮料", "list_date": 20010827}
        )

        self.assertEqual(row["symbol"], "600519")
        self.assertEqual(row["market"], "SH")
        self.assertEqual(row["sector"], "食品饮料")
        self.assertEqual(row["list_date"].year, 2001)

    def test_stock_master_etl_upserts_by_six_digit_code_without_breaking_existing_rows(self) -> None:
        db = self.Session()
        try:
            db.add(Stock(symbol="600519.SH", name="旧茅台", market="SH", sector="旧行业"))
            db.commit()

            result = StockMasterETL().save(
                db,
                [
                    {"symbol": "600519", "name": "贵州茅台", "market": "SH", "sector": "食品饮料"},
                    {"symbol": "000858", "name": "五粮液", "market": "SZ", "sector": "食品饮料"},
                    {"symbol": "000858.SZ", "name": "重复五粮液", "market": "SZ", "sector": "食品饮料"},
                    {"symbol": "ABC", "name": "Invalid"},
                ],
            )

            self.assertEqual(result.fetched, 4)
            self.assertEqual(result.inserted, 1)
            self.assertEqual(result.updated, 1)
            self.assertEqual(result.skipped, 2)
            self.assertEqual(db.query(Stock).count(), 2)
            maotai = db.query(Stock).filter(Stock.symbol == "600519.SH").one()
            self.assertEqual(maotai.name, "贵州茅台")
            self.assertEqual(maotai.sector, "食品饮料")
        finally:
            db.close()

    def test_stock_master_etl_can_deactivate_missing_codes_when_requested(self) -> None:
        db = self.Session()
        try:
            db.add(Stock(symbol="600519", name="贵州茅台", market="SH", is_active=True))
            db.add(Stock(symbol="000858", name="五粮液", market="SZ", is_active=True))
            db.commit()

            result = StockMasterETL().save(
                db,
                [{"symbol": "600519", "name": "贵州茅台", "market": "SH"}],
                deactivate_missing=True,
            )

            self.assertEqual(result.deactivated, 1)
            self.assertTrue(db.query(Stock).filter(Stock.symbol == "600519").one().is_active)
            self.assertFalse(db.query(Stock).filter(Stock.symbol == "000858").one().is_active)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
