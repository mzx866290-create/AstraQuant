import asyncio
import sys
import types
from datetime import date, datetime
from unittest import TestCase
from unittest.mock import patch

from backend.services.data_crawler.pipeline.etl import KLineETL, MinuteKLineETL, WeeklyKLineETL


def build_fake_clickhouse_module(client_calls: list[dict]):
    class FakeClient:
        def __init__(self, **kwargs):
            client_calls.append({"type": "init", **kwargs})

        def execute(self, query, values=None):
            client_calls.append({"type": "execute", "query": query, "values": values})

        def disconnect(self):
            client_calls.append({"type": "disconnect"})

    return types.SimpleNamespace(Client=FakeClient)


def clickhouse_daily_row(**overrides):
    row = {
        "symbol": "600519",
        "name": "Kweichow Moutai",
        "date": date(2026, 5, 6),
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 1000,
        "turnover": 12000.0,
        "change_pct": 1.2,
        "change": 0.13,
        "amplitude": 2.0,
        "turnover_rate": 0.5,
        "up_limit": 12.1,
        "down_limit": 9.9,
        "pe_ttm": 25.0,
        "total_mv": 1000000.0,
        "circ_mv": 900000.0,
        "adjust_flag": 1,
        "source": "unit-test",
    }
    row.update(overrides)
    return row


class ClickHouseWriteMetadataTests(TestCase):
    def test_daily_batch_write_appends_consistent_write_metadata(self) -> None:
        etl = KLineETL()
        client_calls: list[dict] = []
        fake_module = build_fake_clickhouse_module(client_calls)

        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict("os.environ", {"CLICKHOUSE_STOCK_DAILY_TABLE": "stock_daily"}, clear=False):
                saved = asyncio.run(etl._batch_write([
                    clickhouse_daily_row(),
                    clickhouse_daily_row(date=date(2026, 5, 7), close=12.0),
                ]))

        self.assertEqual(saved, 2)
        insert_values = [call for call in client_calls if call.get("type") == "execute"][1]["values"]
        self.assertEqual(len(insert_values[0]), 23)
        record_versions = {row[-3] for row in insert_values}
        updated_ats = {row[-2] for row in insert_values}
        batch_ids = {row[-1] for row in insert_values}
        self.assertEqual(len(record_versions), 1)
        self.assertEqual(len(updated_ats), 1)
        self.assertEqual(len(batch_ids), 1)
        self.assertIsInstance(insert_values[0][-3], int)
        self.assertIsInstance(insert_values[0][-2], datetime)
        self.assertRegex(insert_values[0][-1], r"^[0-9a-f]{32}$")

    def test_minute_batch_write_appends_write_metadata(self) -> None:
        etl = MinuteKLineETL()
        client_calls: list[dict] = []
        fake_module = build_fake_clickhouse_module(client_calls)
        rows = [{
            "symbol": "600519",
            "timestamp": datetime(2026, 5, 6, 9, 35, 0),
            "open": 1660.0,
            "high": 1670.0,
            "low": 1658.0,
            "close": 1668.88,
            "volume": 1000,
            "turnover": 5200000.5,
            "trade_status": "",
            "market": "SH",
        }]

        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict("os.environ", {"CLICKHOUSE_STOCK_MINUTE_TABLE": "stock_minute"}, clear=False):
                saved = asyncio.run(etl._batch_write(rows))

        self.assertEqual(saved, 1)
        insert_values = [call for call in client_calls if call.get("type") == "execute"][1]["values"]
        self.assertEqual(len(insert_values[0]), 13)
        self.assertIsInstance(insert_values[0][-3], int)
        self.assertIsInstance(insert_values[0][-2], datetime)
        self.assertRegex(insert_values[0][-1], r"^[0-9a-f]{32}$")

    def test_weekly_batch_write_keeps_explicit_write_metadata(self) -> None:
        etl = WeeklyKLineETL()
        client_calls: list[dict] = []
        fake_module = build_fake_clickhouse_module(client_calls)
        explicit_updated_at = datetime(2026, 5, 6, 9, 30, 0)
        rows = [{
            "symbol": "600519",
            "week_start": date(2026, 5, 4),
            "open": 10.0,
            "high": 12.0,
            "low": 9.0,
            "close": 11.0,
            "volume": 5000,
            "turnover": 62000.5,
            "change_pct": 1.0,
            "amplitude": 2.0,
            "record_version": 20260506093000000,
            "updated_at": explicit_updated_at,
            "etl_batch_id": "manual-batch",
        }]

        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict("os.environ", {"CLICKHOUSE_STOCK_WEEKLY_TABLE": "stock_weekly"}, clear=False):
                saved = asyncio.run(etl._batch_write(rows, "week_start", "CLICKHOUSE_STOCK_WEEKLY_TABLE", "stock_weekly"))

        self.assertEqual(saved, 1)
        insert_values = [call for call in client_calls if call.get("type") == "execute"][1]["values"]
        self.assertEqual(insert_values[0][-3:], (20260506093000000, explicit_updated_at, "manual-batch"))
