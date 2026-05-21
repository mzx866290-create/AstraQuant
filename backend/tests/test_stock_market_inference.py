from __future__ import annotations

import asyncio
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.shared.models import Base, Stock


class StockMarketInferenceTests(unittest.TestCase):
    def test_bj_legacy_codes_map_to_920_current_symbol(self) -> None:
        from backend.services.market_service.app.utils.symbols import bj_legacy_920_symbol

        self.assertEqual(bj_legacy_920_symbol("430047.BJ"), "920047.BJ")
        self.assertEqual(bj_legacy_920_symbol("BJ830799"), "920799.BJ")
        self.assertEqual(bj_legacy_920_symbol("920047.BJ"), "")
        self.assertEqual(bj_legacy_920_symbol("600519.SH"), "")

    def test_api_symbol_infers_bj_for_north_exchange_codes(self) -> None:
        from backend.services.market_service.app.api.v1 import stocks

        self.assertEqual(stocks._api_symbol("430047", ""), "430047.BJ")
        self.assertEqual(stocks._api_symbol("BJ830799", ""), "830799.BJ")
        self.assertEqual(stocks._api_symbol("600519.SS", "SS"), "600519.SH")

    def test_get_stock_fallback_keeps_bj_suffix(self) -> None:
        from backend.services.market_service.app.api.v1 import stocks

        public_info = {
            "name": "Unit BJ",
            "sector": "Test",
            "source": "unit",
        }
        with patch.object(stocks, "_fetch_public_stock_info", return_value=public_info) as fetch_info, patch(
            "backend.shared.database.SessionLocal",
            side_effect=RuntimeError("db unavailable"),
        ):
            result = asyncio.run(stocks.get_stock("430047.BJ"))

        fetch_info.assert_called_once_with("920047", "BJ")
        self.assertEqual(result["symbol"], "430047.BJ")
        self.assertEqual(result["resolved_symbol"], "920047.BJ")
        self.assertEqual(result["market"], "BJ")
        self.assertEqual(result["name"], "Unit BJ")

    def test_get_stock_old_bj_db_record_reports_920_resolved_symbol(self) -> None:
        from backend.services.market_service.app.api.v1 import stocks

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        db = session_factory()
        try:
            db.add(Stock(symbol="BJ430047", name="Unit BJ", market="BJ", sector="Test", is_active=True))
            db.commit()

            with patch.object(
                stocks,
                "_fetch_public_stock_info",
                return_value={"name": "Unit BJ", "latest_price": 31.45, "source": "unit"},
            ) as fetch_info, patch("backend.shared.database.SessionLocal", return_value=db):
                result = asyncio.run(stocks.get_stock("430047.BJ"))

            fetch_info.assert_called_once_with("920047", "BJ")
            self.assertEqual(result["symbol"], "430047.BJ")
            self.assertEqual(result["resolved_symbol"], "920047.BJ")
            self.assertEqual(result["latest_price"], 31.45)
        finally:
            db.close()

    def test_public_stock_info_ignores_empty_eastmoney_company_payload(self) -> None:
        from backend.services.market_service.app.api.v1 import stocks

        stocks._fetch_public_stock_info.cache_clear()
        f10_response = Mock()
        f10_response.raise_for_status.return_value = None
        f10_response.json.return_value = {"status": -1, "message": "invalid"}

        parts = [""] * 80
        parts[1] = "诺思兰德"
        parts[2] = "430047"
        parts[3] = "8.17"
        parts[44] = "14.71"
        parts[45] = "22.41"
        parts[72] = "180106427"
        parts[73] = "274271974"
        quote_response = Mock()
        quote_response.raise_for_status.return_value = None
        quote_response.content = f'v_bj430047="{"~".join(parts)}";'.encode("gbk")

        with patch("akshare.stock_individual_info_em", side_effect=RuntimeError("source down")), patch(
            "requests.get",
            side_effect=[f10_response, quote_response],
        ):
            result = stocks._fetch_public_stock_info("430047", "BJ")

        self.assertEqual(result["name"], "诺思兰德")
        self.assertEqual(result["source"], "tencent")
        self.assertEqual(result["sector"], "")
        self.assertIsNone(result["list_date"])

        stocks._fetch_public_stock_info.cache_clear()


class SinaTencentSourceTests(unittest.TestCase):
    def test_bj_symbols_use_bj_prefix_for_sina_tencent(self) -> None:
        from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource

        source = SinaTencentSource()

        self.assertEqual(source._tencent_symbol("830799.BJ"), "bj830799")
        self.assertEqual(source._tencent_symbol("BJ430047"), "bj430047")
        self.assertEqual(source._tencent_symbol("600519.SH"), "sh600519")
        self.assertEqual(source._tencent_symbol("000001.SZ"), "sz000001")

    def test_realtime_quote_maps_tencent_market_values(self) -> None:
        from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource

        parts = [""] * 80
        parts[1] = "诺思兰德"
        parts[3] = "8.17"
        parts[4] = "8.17"
        parts[30] = "20260515090000"
        parts[31] = "0.00"
        parts[32] = "0.00"
        parts[36] = "0"
        parts[37] = "0.00"
        parts[38] = "0.00"
        parts[39] = "-38.71"
        parts[44] = "14.71"
        parts[45] = "22.41"
        parts[46] = "8.44"

        response = Mock()
        response.raise_for_status.return_value = None
        response.content = f'v_bj430047="{"~".join(parts)}";'.encode("gbk")

        with patch("requests.get", return_value=response):
            result = SinaTencentSource()._fetch_realtime_quote_sync("430047.BJ")

        self.assertEqual(result["total_mv"], 2241000000.0)
        self.assertEqual(result["circ_mv"], 1471000000.0)


if __name__ == "__main__":
    unittest.main()
