import asyncio
import sys
import types
from datetime import date, datetime
from unittest import TestCase
from unittest.mock import patch

from backend.services.data_crawler.pipeline.etl import (
    ClickHouseWriteUnavailable,
    KLineETL,
    MinuteKLineETL,
    MoneyFlowETL,
    MonthlyKLineETL,
    WeeklyKLineETL,
)


def build_recording_clickhouse_module(client_calls: list[dict], *, fail_first_insert: bool = False):
    state = {
        "rows_by_key": {},
        "pending_delete_table": None,
        "insert_count": 0,
    }

    def table_from_insert(query: str) -> str:
        return query.split("INSERT INTO ", 1)[1].split(" ", 1)[0]

    def table_from_delete(query: str) -> str:
        return query.split("ALTER TABLE ", 1)[1].split(" DELETE WHERE ", 1)[0]

    def key_for(table: str, values: tuple):
        if table == "stock_daily":
            return values[0], values[2], values[18]
        return values[0], values[1]

    class FakeClient:
        def __init__(self, **kwargs):
            client_calls.append({"type": "init", **kwargs})

        def execute(self, query, values=None):
            client_calls.append({"type": "execute", "query": query, "values": values})
            if query.startswith("ALTER TABLE"):
                state["pending_delete_table"] = table_from_delete(query)
                return
            if query.startswith("INSERT INTO"):
                table = table_from_insert(query)
                if state["pending_delete_table"] == table:
                    for row_values in values:
                        state["rows_by_key"].pop((table, key_for(table, row_values)), None)
                    state["pending_delete_table"] = None
                for row_values in values:
                    state["rows_by_key"][(table, key_for(table, row_values))] = row_values
                state["insert_count"] += 1
                if fail_first_insert and state["insert_count"] == 1:
                    raise RuntimeError("insert timeout after partial success")

        def disconnect(self):
            client_calls.append({"type": "disconnect"})

    module = types.SimpleNamespace(Client=FakeClient)
    module.state = state
    return module


def daily_row(**overrides):
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


def minute_row(**overrides):
    row = {
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
    }
    row.update(overrides)
    return row


def period_row(period_column: str, **overrides):
    row = {
        "symbol": "600519",
        period_column: date(2026, 5, 4) if period_column == "week_start" else date(2026, 5, 1),
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 5000,
        "turnover": 62000.5,
        "change_pct": 1.0,
        "amplitude": 2.0,
    }
    row.update(overrides)
    return row


def money_flow_row(**overrides):
    row = {
        "symbol": "600519",
        "date": date(2026, 5, 6),
        "main_net_inflow": 100.0,
        "small_net_inflow": 1.0,
        "mid_net_inflow": 2.0,
        "big_net_inflow": 3.0,
        "super_net_inflow": 4.0,
        "main_pct": 5.0,
        "source": "unit-test",
    }
    row.update(overrides)
    return row


class ETLIdempotencyTests(TestCase):
    def test_batch_writes_filter_duplicate_business_keys_before_insert(self) -> None:
        cases = [
            (
                "daily",
                KLineETL()._batch_write,
                [daily_row(close=11.0), daily_row(close=12.0)],
                {"CLICKHOUSE_STOCK_DAILY_TABLE": "stock_daily"},
                1,
            ),
            (
                "minute",
                MinuteKLineETL()._batch_write,
                [minute_row(close=1668.88), minute_row(close=1669.88)],
                {"CLICKHOUSE_STOCK_MINUTE_TABLE": "stock_minute"},
                1,
            ),
            (
                "weekly",
                lambda rows: WeeklyKLineETL()._batch_write(rows, "week_start", "CLICKHOUSE_STOCK_WEEKLY_TABLE", "stock_weekly"),
                [period_row("week_start", close=11.0), period_row("week_start", close=12.0)],
                {"CLICKHOUSE_STOCK_WEEKLY_TABLE": "stock_weekly"},
                1,
            ),
            (
                "monthly",
                lambda rows: MonthlyKLineETL()._batch_write(rows, "month_start", "CLICKHOUSE_STOCK_MONTHLY_TABLE", "stock_monthly"),
                [period_row("month_start", close=11.0), period_row("month_start", close=12.0)],
                {"CLICKHOUSE_STOCK_MONTHLY_TABLE": "stock_monthly"},
                1,
            ),
        ]

        for name, write, rows, env, expected_insert_count in cases:
            with self.subTest(name=name):
                client_calls: list[dict] = []
                fake_module = build_recording_clickhouse_module(client_calls)
                with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
                    with patch.dict("os.environ", env, clear=False):
                        saved = asyncio.run(write(rows))

                execute_calls = [call for call in client_calls if call.get("type") == "execute"]
                self.assertEqual(saved, expected_insert_count)
                self.assertTrue(execute_calls[0]["query"].startswith("ALTER TABLE"))
                self.assertTrue(execute_calls[1]["query"].startswith("INSERT INTO"))
                self.assertEqual(len(execute_calls[1]["values"]), expected_insert_count)

    def test_cross_batch_rerun_replaces_existing_daily_key(self) -> None:
        etl = KLineETL()
        client_calls: list[dict] = []
        fake_module = build_recording_clickhouse_module(client_calls)

        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict("os.environ", {"CLICKHOUSE_STOCK_DAILY_TABLE": "stock_daily"}, clear=False):
                first_saved = asyncio.run(etl._batch_write([daily_row(close=11.0)]))
                second_saved = asyncio.run(etl._batch_write([daily_row(close=12.0)]))

        self.assertEqual(first_saved, 1)
        self.assertEqual(second_saved, 1)
        stored_rows = list(fake_module.state["rows_by_key"].values())
        self.assertEqual(len(stored_rows), 1)
        self.assertEqual(stored_rows[0][6], 12.0)

    def test_partial_insert_success_can_be_retried_without_duplicate_daily_rows(self) -> None:
        etl = KLineETL()
        client_calls: list[dict] = []
        fake_module = build_recording_clickhouse_module(client_calls, fail_first_insert=True)

        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict("os.environ", {"CLICKHOUSE_STOCK_DAILY_TABLE": "stock_daily"}, clear=False):
                with self.assertRaisesRegex(ClickHouseWriteUnavailable, "partial success"):
                    asyncio.run(etl._batch_write([daily_row(close=11.0)]))
                saved = asyncio.run(etl._batch_write([daily_row(close=12.0)]))

        self.assertEqual(saved, 1)
        stored_rows = list(fake_module.state["rows_by_key"].values())
        self.assertEqual(len(stored_rows), 1)
        self.assertEqual(stored_rows[0][6], 12.0)
