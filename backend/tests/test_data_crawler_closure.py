import asyncio
import sys
import types
from datetime import date, datetime
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from backend.services.data_crawler.app.main import DataCrawler
from backend.services.data_crawler.pipeline.etl import (
    ClickHouseWriteUnavailable,
    KLineETL,
    MinuteKLineETL,
    MonthlyKLineETL,
    WeeklyKLineETL,
)


class MemoryKLineETL(KLineETL):
    def __init__(self):
        self.rows = []

    async def _batch_write(self, rows):
        self.rows.extend(rows)
        return len(rows)


class FakeMoneyFlowSourceChain:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def fetch_with_fallback(self, method_name: str, **kwargs):
        self.calls.append({"method_name": method_name, **kwargs})
        return {"data": self.rows, "source": "unit-money-flow"}


class FakeMoneyFlowETL:
    def __init__(self, saved_count: int):
        self.saved_count = saved_count
        self.calls = []

    async def save(self, symbol: str, data: list[dict], source: str):
        self.calls.append({"symbol": symbol, "data": data, "source": source})
        return self.saved_count


class FakeDailySourceChain:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def fetch_daily_kline(self, symbol: str, start_date: str = "", end_date: str = "", adjust: str = ""):
        self.calls.append({
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust,
        })
        return {"data": self.rows, "source": "unit-source"}


class FakePeriodKLineSourceChain:
    def __init__(self, rows, source: str = "unit-period-kline"):
        self.rows = rows
        self.source = source
        self.calls = []

    async def fetch_with_fallback(self, method_name: str, **kwargs):
        self.calls.append({"method_name": method_name, **kwargs})
        return {"data": self.rows, "source": self.source}


class FakeRealtimeQuoteSourceChain:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls = []

    async def fetch_with_fallback(self, method_name: str, **kwargs):
        self.calls.append({"method_name": method_name, **kwargs})
        return {"data": self.rows, "source": "unit-realtime"}


class AsyncCloseRecorder:
    def __init__(self, should_fail: bool = False):
        self.closed = False
        self.should_fail = should_fail

    async def close(self):
        self.closed = True
        if self.should_fail:
            raise RuntimeError("close failed")


class FakeDailyETL:
    def __init__(self, saved_count: int):
        self.saved_count = saved_count
        self.calls = []

    async def save_daily_kline(self, symbol: str, data: list[dict], source: str):
        self.calls.append({"symbol": symbol, "data": data, "source": source})
        return self.saved_count


class FakePeriodKLineETL:
    def __init__(self, saved_count: int):
        self.saved_count = saved_count
        self.calls = []

    async def save(self, symbol: str, data: list[dict], source: str):
        self.calls.append({"symbol": symbol, "data": data, "source": source})
        return self.saved_count


class FakePeriodKLineETL:
    def __init__(self, saved_count: int):
        self.saved_count = saved_count
        self.calls = []

    async def save(self, symbol: str, data: list[dict], source: str):
        self.calls.append({"symbol": symbol, "data": data, "source": source})
        return self.saved_count


class FakeRealtimeQuoteETL:
    def __init__(self, saved_count: int):
        self.saved_count = saved_count
        self.calls = []

    async def save(self, symbol: str, data: list[dict]):
        self.calls.append({"symbol": symbol, "data": data})
        return self.saved_count


class FakeCircuitBreaker:
    def __init__(self):
        self.failure_count = 0
        self.success_count = 0

    def is_available(self):
        return True

    def record_failure(self):
        self.failure_count += 1

    def record_success(self):
        self.success_count += 1


class UnsupportedOptionalSource:
    name = "unsupported"
    priority = 1

    def __init__(self):
        self.circuit_breaker = FakeCircuitBreaker()


class SupportedOptionalSource:
    name = "supported"
    priority = 2

    def __init__(self):
        self.circuit_breaker = FakeCircuitBreaker()

    async def fetch_stock_notices(self, symbol: str, limit: int = 20):
        return [{"title": f"{symbol}-{limit}"}]


def clickhouse_row(**overrides):
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


def build_fake_clickhouse_module(client_calls: list[dict], execute_side_effect=None):
    class FakeClient:
        def __init__(self, **kwargs):
            client_calls.append({"type": "init", **kwargs})

        def execute(self, query, values=None):
            client_calls.append({"type": "execute", "query": query, "values": values})
            if execute_side_effect is not None:
                execute_side_effect(query, values)

        def disconnect(self):
            client_calls.append({"type": "disconnect"})

    return types.SimpleNamespace(Client=FakeClient)


class DataCrawlerClosureTests(TestCase):
    def _require_etl_class(self, class_name: str):
        from backend.services.data_crawler.pipeline import etl as etl_module

        etl_class = getattr(etl_module, class_name, None)
        if etl_class is None:
            self.fail(
                f"{class_name} is not implemented in "
                "backend.services.data_crawler.pipeline.etl"
            )
        return etl_class

    def _run_periodic_kline_task_or_skip(self, crawler: DataCrawler, method_name: str):
        result = asyncio.run(getattr(crawler, method_name)())
        if result.get("status") == "not_implemented":
            self.skipTest(f"{method_name} is still not implemented in production")
        return result

    def test_kline_etl_returns_saved_count_and_cleans_rows(self) -> None:
        etl = MemoryKLineETL()
        saved = asyncio.run(etl.save_daily_kline(
            "600519.SH",
            [{
                "date": "2026-05-06",
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "volume": "1000",
            }],
            "unit-test",
        ))

        self.assertEqual(saved, 1)
        self.assertEqual(etl.rows[0]["symbol"], "600519")
        self.assertEqual(etl.rows[0]["date"], date(2026, 5, 6))

    def test_weekly_kline_etl_returns_saved_count_and_cleans_rows(self) -> None:
        class MemoryWeeklyKLineETL(WeeklyKLineETL):
            def __init__(self):
                self.rows = []

            async def _batch_write(self, rows, period_column, table_env, table_default):
                self.rows.extend(rows)
                return len(rows)

        etl = MemoryWeeklyKLineETL()
        saved = asyncio.run(etl.save(
            "600519.SH",
            [{
                "date": "2026-05-01",
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "volume": "5000",
                "turnover": "62000.5",
            }],
            "unit-source",
        ))

        self.assertEqual(saved, 1)
        self.assertEqual(etl.rows[0]["symbol"], "600519")
        self.assertEqual(etl.rows[0]["week_start"], date(2026, 4, 27))
        self.assertEqual(etl.rows[0]["turnover"], 62000.5)
        self.assertEqual(etl.rows[0]["close"], 11.0)

    def test_monthly_kline_etl_returns_saved_count_and_cleans_rows(self) -> None:
        class MemoryMonthlyKLineETL(MonthlyKLineETL):
            def __init__(self):
                self.rows = []

            async def _batch_write(self, rows, period_column, table_env, table_default):
                self.rows.extend(rows)
                return len(rows)

        etl = MemoryMonthlyKLineETL()
        saved = asyncio.run(etl.save(
            "000858.SZ",
            [{
                "date": "2026-04-30",
                "open": 120,
                "high": 135,
                "low": 118,
                "close": 132,
                "volume": "8000",
            }],
            "unit-source",
        ))

        self.assertEqual(saved, 1)
        self.assertEqual(etl.rows[0]["symbol"], "000858")
        self.assertEqual(etl.rows[0]["month_start"], date(2026, 4, 1))
        self.assertEqual(etl.rows[0]["close"], 132.0)
        self.assertEqual(etl.rows[0]["volume"], 8000)

    def test_kline_etl_deduplicates_same_symbol_date_before_write(self) -> None:
        etl = MemoryKLineETL()
        saved = asyncio.run(etl.save_daily_kline(
            "600519",
            [
                {"date": "2026-05-06", "open": 10, "high": 12, "low": 9, "close": 11},
                {"date": "2026-05-06", "open": 10, "high": 13, "low": 9, "close": 12},
            ],
            "unit-test",
        ))

        self.assertEqual(saved, 1)
        self.assertEqual(etl.rows[0]["close"], 12.0)

    def test_kline_etl_does_not_pretend_invalid_rows_were_saved(self) -> None:
        etl = MemoryKLineETL()
        saved = asyncio.run(etl.save_daily_kline(
            "600519",
            [{"date": "2026-05-06", "open": 10, "high": 8, "low": 9, "close": 11}],
            "unit-test",
        ))

        self.assertEqual(saved, 0)
        self.assertEqual(etl.rows, [])

    def test_batch_write_rejects_invalid_table_name_before_insert(self) -> None:
        etl = KLineETL()
        with patch.dict("os.environ", {"CLICKHOUSE_STOCK_DAILY_TABLE": "stock_daily;drop"}, clear=False):
            with self.assertRaises(ClickHouseWriteUnavailable):
                asyncio.run(etl._batch_write([{"symbol": "600519"}]))

    def test_weekly_kline_batch_write_rejects_invalid_table_name_before_insert(self) -> None:
        etl = WeeklyKLineETL()
        with patch.dict("os.environ", {"CLICKHOUSE_STOCK_WEEKLY_TABLE": "stock_weekly;drop"}, clear=False):
            with self.assertRaises(ClickHouseWriteUnavailable):
                asyncio.run(etl._batch_write([{"symbol": "600519"}], "week_start", "CLICKHOUSE_STOCK_WEEKLY_TABLE", "stock_weekly"))

    def test_monthly_kline_batch_write_rejects_invalid_table_name_before_insert(self) -> None:
        etl = MonthlyKLineETL()
        with patch.dict("os.environ", {"CLICKHOUSE_STOCK_MONTHLY_TABLE": "stock_monthly;drop"}, clear=False):
            with self.assertRaises(ClickHouseWriteUnavailable):
                asyncio.run(etl._batch_write([{"symbol": "600519"}], "month_start", "CLICKHOUSE_STOCK_MONTHLY_TABLE", "stock_monthly"))

    def test_batch_write_uses_clickhouse_native_port(self) -> None:
        etl = KLineETL()
        client_calls = []
        fake_module = build_fake_clickhouse_module(client_calls)
        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict(
                "os.environ",
                {
                    "CLICKHOUSE_PORT": "8123",
                    "CLICKHOUSE_NATIVE_PORT": "9000",
                    "CLICKHOUSE_STOCK_DAILY_TABLE": "stock_daily",
                },
                clear=False,
            ):
                saved = asyncio.run(etl._batch_write([clickhouse_row()]))

        self.assertEqual(saved, 1)
        self.assertEqual(client_calls[0]["port"], 9000)
        execute_calls = [call for call in client_calls if call.get("type") == "execute"]
        self.assertIn("ALTER TABLE stock_daily DELETE WHERE", execute_calls[0]["query"])
        self.assertIn("INSERT INTO stock_daily", execute_calls[1]["query"])

    def test_daily_batch_write_deletes_existing_keys_before_insert(self) -> None:
        etl = KLineETL()
        client_calls = []
        fake_module = build_fake_clickhouse_module(client_calls)

        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict("os.environ", {"CLICKHOUSE_STOCK_DAILY_TABLE": "stock_daily"}, clear=False):
                saved = asyncio.run(etl._batch_write([
                    clickhouse_row(),
                    clickhouse_row(date=date(2026, 5, 7), close=12.0),
                ]))

        self.assertEqual(saved, 2)
        execute_calls = [call for call in client_calls if call.get("type") == "execute"]
        self.assertEqual(len(execute_calls), 2)
        self.assertIn("(symbol, date, adjust_flag) IN", execute_calls[0]["query"])
        self.assertIn("toDate('2026-05-06')", execute_calls[0]["query"])
        self.assertIn("toDate('2026-05-07')", execute_calls[0]["query"])
        self.assertIn("SETTINGS mutations_sync = 1", execute_calls[0]["query"])
        self.assertIn("INSERT INTO stock_daily", execute_calls[1]["query"])
        self.assertEqual(len(execute_calls[1]["values"]), 2)

    def test_minute_batch_write_uses_timestamp_key_for_idempotent_delete(self) -> None:
        etl = MinuteKLineETL()
        client_calls = []
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
        delete_query = [call for call in client_calls if call.get("type") == "execute"][0]["query"]
        self.assertIn("(symbol, timestamp) IN", delete_query)
        self.assertIn("toDateTime('2026-05-06 09:35:00')", delete_query)

    def test_weekly_batch_write_uses_period_key_for_idempotent_delete(self) -> None:
        etl = WeeklyKLineETL()
        client_calls = []
        fake_module = build_fake_clickhouse_module(client_calls)
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
        }]

        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict("os.environ", {"CLICKHOUSE_STOCK_WEEKLY_TABLE": "stock_weekly"}, clear=False):
                saved = asyncio.run(etl._batch_write(rows, "week_start", "CLICKHOUSE_STOCK_WEEKLY_TABLE", "stock_weekly"))

        self.assertEqual(saved, 1)
        delete_query = [call for call in client_calls if call.get("type") == "execute"][0]["query"]
        self.assertIn("(symbol, week_start) IN", delete_query)
        self.assertIn("toDate('2026-05-04')", delete_query)

    def test_clickhouse_delete_failure_does_not_fall_through_to_insert(self) -> None:
        etl = KLineETL()
        client_calls = []

        def fail_on_delete(query, values):
            if query.startswith("ALTER TABLE"):
                raise RuntimeError("delete failed")

        fake_module = build_fake_clickhouse_module(client_calls, execute_side_effect=fail_on_delete)
        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict("os.environ", {"CLICKHOUSE_STOCK_DAILY_TABLE": "stock_daily"}, clear=False):
                with self.assertRaisesRegex(ClickHouseWriteUnavailable, "delete failed"):
                    asyncio.run(etl._batch_write([clickhouse_row()]))

        execute_calls = [call for call in client_calls if call.get("type") == "execute"]
        self.assertEqual(len(execute_calls), 1)
        self.assertEqual(client_calls[-1]["type"], "disconnect")

    def test_money_flow_etl_returns_saved_count_and_cleans_rows(self) -> None:
        money_flow_etl_class = self._require_etl_class("MoneyFlowETL")

        class MemoryMoneyFlowETL(money_flow_etl_class):
            def __init__(self):
                self.rows = []

            async def _batch_write(self, rows):
                self.rows.extend(rows)
                return len(rows)

        etl = MemoryMoneyFlowETL()
        saved = asyncio.run(etl.save(
            "600519.SH",
            [{
                "date": "2026-05-06",
                "main_inflow": "1234567.8",
                "small_inflow": "100.5",
                "mid_inflow": "200.5",
                "big_inflow": "300.5",
                "super_inflow": "400.5",
            }],
            "unit-test",
        ))

        self.assertEqual(saved, 1)
        self.assertEqual(etl.rows[0]["symbol"], "600519")
        self.assertEqual(etl.rows[0]["date"], date(2026, 5, 6))
        self.assertEqual(etl.rows[0]["main_net_inflow"], 1234567.8)
        self.assertEqual(etl.rows[0]["source"], "unit-test")

    def test_money_flow_batch_write_rejects_invalid_table_name_before_insert(self) -> None:
        money_flow_etl_class = self._require_etl_class("MoneyFlowETL")
        etl = money_flow_etl_class()

        with patch.dict("os.environ", {"CLICKHOUSE_MONEY_FLOW_TABLE": "money_flow;drop"}, clear=False):
            with self.assertRaises(ClickHouseWriteUnavailable):
                asyncio.run(etl._batch_write([{"symbol": "600519"}]))

    def test_realtime_quote_etl_returns_saved_count_and_cleans_snapshot(self) -> None:
        realtime_quote_etl_class = self._require_etl_class("MinuteKLineETL")

        class MemoryRealtimeQuoteETL(realtime_quote_etl_class):
            def __init__(self):
                self.rows = []

            async def _batch_write(self, rows):
                self.rows.extend(rows)
                return len(rows)

        etl = MemoryRealtimeQuoteETL()
        saved = asyncio.run(etl.save(
            "600519.SH",
            [{
                "timestamp": "2026-05-06T09:35:00",
                "open": 1660.0,
                "high": 1670.0,
                "low": 1658.0,
                "close": 1668.88,
                "volume": "1000",
                "turnover": "5200000.5",
            }],
        ))

        self.assertEqual(saved, 1)
        self.assertEqual(etl.rows[0]["symbol"], "600519")
        self.assertEqual(etl.rows[0]["timestamp"], datetime(2026, 5, 6, 9, 35, 0))
        self.assertEqual(etl.rows[0]["close"], 1668.88)
        self.assertEqual(etl.rows[0]["market"], "SH")

    def test_realtime_quote_batch_write_rejects_invalid_table_name_before_insert(self) -> None:
        realtime_quote_etl_class = self._require_etl_class("MinuteKLineETL")
        etl = realtime_quote_etl_class()

        with patch.dict("os.environ", {"CLICKHOUSE_STOCK_MINUTE_TABLE": "stock_minute;drop"}, clear=False):
            with self.assertRaises(ClickHouseWriteUnavailable):
                asyncio.run(etl._batch_write([{"symbol": "600519"}]))

    def test_daily_kline_task_requests_and_filters_target_date(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakeDailySourceChain([
            {"date": "2026-05-05", "open": 9, "high": 10, "low": 8, "close": 9},
            {"date": "2026-05-06", "open": 10, "high": 12, "low": 9, "close": 11},
        ])
        crawler.etl = FakeDailyETL(saved_count=1)
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        with patch.dict("os.environ", {"DATA_CRAWLER_DAILY_TARGET_DATE": "2026-05-06"}, clear=False):
            result = asyncio.run(crawler.collect_daily_kline_for_all())

        self.assertEqual(result["target_date"], "2026-05-06")
        self.assertEqual(result["success"], 1)
        self.assertEqual(crawler.source_chain.calls[0]["start_date"], "2026-05-06")
        self.assertEqual(crawler.source_chain.calls[0]["end_date"], "2026-05-06")
        self.assertEqual([row["date"] for row in crawler.etl.calls[0]["data"]], ["2026-05-06"])
        self.assertEqual(records[0][0][2], "success")

    def test_daily_kline_no_saved_is_not_counted_as_success(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakeDailySourceChain([
            {"date": "2026-05-06", "open": 10, "high": 12, "low": 9, "close": 11},
        ])
        crawler.etl = FakeDailyETL(saved_count=0)
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        with patch.dict("os.environ", {"DATA_CRAWLER_DAILY_TARGET_DATE": "2026-05-06"}, clear=False):
            result = asyncio.run(crawler.collect_daily_kline_for_all())

        self.assertEqual(result["success"], 0)
        self.assertEqual(records[0][0][2], "no_saved")

    def test_daily_kline_write_error_is_recorded_as_error(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakeDailySourceChain([
            {"date": "2026-05-06", "open": 10, "high": 12, "low": 9, "close": 11},
        ])
        crawler.etl = types.SimpleNamespace(save_daily_kline=AsyncMock(side_effect=RuntimeError("write failed")))
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        with patch.dict("os.environ", {"DATA_CRAWLER_DAILY_TARGET_DATE": "2026-05-06"}, clear=False):
            result = asyncio.run(crawler.collect_daily_kline_for_all())

        self.assertEqual(result["success"], 0)
        self.assertEqual(records[0][0][2], "error")
        self.assertIn("write failed", records[0][1]["error_message"])

    def test_weekly_kline_task_fetches_writes_and_records_status(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakePeriodKLineSourceChain([
            {"date": "2026-05-01", "open": 10, "high": 12, "low": 9, "close": 11}
        ])
        crawler.weekly_etl = FakePeriodKLineETL(saved_count=1)
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = self._run_periodic_kline_task_or_skip(crawler, "collect_weekly_kline")

        self.assertEqual(result["task"], "weekly_kline")
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["period"], "1w")
        self.assertEqual(crawler.source_chain.calls[0]["method_name"], "fetch_kline")
        self.assertEqual(crawler.source_chain.calls[0]["symbol"], "600519")
        self.assertEqual(crawler.source_chain.calls[0]["period"], "1w")
        self.assertEqual(crawler.source_chain.calls[0]["adjust"], "1")
        self.assertEqual(crawler.source_chain.calls[0]["limit"], 1)
        self.assertEqual(crawler.weekly_etl.calls[0]["symbol"], "600519")
        self.assertEqual(crawler.weekly_etl.calls[0]["source"], "unit-period-kline")
        self.assertEqual(records[0][0][1], "weekly_kline")
        self.assertEqual(records[0][0][2], "success")

    def test_weekly_kline_task_no_saved_is_not_counted_as_success(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakePeriodKLineSourceChain([
            {"date": "2026-05-01", "open": 10, "high": 12, "low": 9, "close": 11}
        ])
        crawler.weekly_etl = FakePeriodKLineETL(saved_count=0)
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = self._run_periodic_kline_task_or_skip(crawler, "collect_weekly_kline")

        self.assertEqual(result["task"], "weekly_kline")
        self.assertEqual(result["success"], 0)
        self.assertEqual(records[0][0][2], "no_saved")
        self.assertEqual(records[0][1]["fetched"], 1)
        self.assertEqual(records[0][1]["saved"], 0)

    def test_weekly_kline_write_error_is_recorded_as_error(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakePeriodKLineSourceChain([
            {"date": "2026-05-01", "open": 10, "high": 12, "low": 9, "close": 11}
        ])
        crawler.weekly_etl = types.SimpleNamespace(save=AsyncMock(side_effect=RuntimeError("write failed")))
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = self._run_periodic_kline_task_or_skip(crawler, "collect_weekly_kline")

        self.assertEqual(result["success"], 0)
        self.assertEqual(records[0][0][2], "error")
        self.assertIn("write failed", records[0][1]["error_message"])

    def test_monthly_kline_task_fetches_writes_and_records_status(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakePeriodKLineSourceChain([
            {"date": "2026-04-30", "open": 120, "high": 135, "low": 118, "close": 132}
        ])
        crawler.monthly_etl = FakePeriodKLineETL(saved_count=1)
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = self._run_periodic_kline_task_or_skip(crawler, "collect_monthly_kline")

        self.assertEqual(result["task"], "monthly_kline")
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["period"], "1M")
        self.assertEqual(crawler.source_chain.calls[0]["method_name"], "fetch_kline")
        self.assertEqual(crawler.source_chain.calls[0]["symbol"], "600519")
        self.assertEqual(crawler.source_chain.calls[0]["period"], "1M")
        self.assertEqual(crawler.source_chain.calls[0]["adjust"], "1")
        self.assertEqual(crawler.source_chain.calls[0]["limit"], 1)
        self.assertEqual(crawler.monthly_etl.calls[0]["symbol"], "600519")
        self.assertEqual(crawler.monthly_etl.calls[0]["source"], "unit-period-kline")
        self.assertEqual(records[0][0][1], "monthly_kline")
        self.assertEqual(records[0][0][2], "success")

    def test_monthly_kline_task_no_saved_is_not_counted_as_success(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakePeriodKLineSourceChain([
            {"date": "2026-04-30", "open": 120, "high": 135, "low": 118, "close": 132}
        ])
        crawler.monthly_etl = FakePeriodKLineETL(saved_count=0)
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = self._run_periodic_kline_task_or_skip(crawler, "collect_monthly_kline")

        self.assertEqual(result["task"], "monthly_kline")
        self.assertEqual(result["success"], 0)
        self.assertEqual(records[0][0][2], "no_saved")
        self.assertEqual(records[0][1]["fetched"], 1)
        self.assertEqual(records[0][1]["saved"], 0)

    def test_money_flow_task_fetches_writes_and_records_status(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakeMoneyFlowSourceChain([
            {
                "date": "2026-05-06",
                "main_inflow": 1234567.8,
                "small_inflow": 100.5,
                "mid_inflow": 200.5,
                "big_inflow": 300.5,
                "super_inflow": 400.5,
            }
        ])
        crawler.money_flow_etl = FakeMoneyFlowETL(saved_count=1)
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = asyncio.run(crawler.collect_money_flow())

        self.assertEqual(result["task"], "money_flow")
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["limit"], 20)
        self.assertEqual(crawler.source_chain.calls[0]["method_name"], "fetch_money_flow")
        self.assertEqual(crawler.source_chain.calls[0]["symbol"], "600519")
        self.assertEqual(crawler.source_chain.calls[0]["limit"], 20)
        self.assertEqual(crawler.money_flow_etl.calls[0]["symbol"], "600519")
        self.assertEqual(crawler.money_flow_etl.calls[0]["source"], "unit-money-flow")
        self.assertEqual(records[0][0][1], "money_flow")
        self.assertEqual(records[0][0][2], "success")

    def test_money_flow_task_no_saved_is_not_counted_as_success(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakeMoneyFlowSourceChain([
            {"date": "2026-05-06", "main_inflow": 1234567.8}
        ])
        crawler.money_flow_etl = FakeMoneyFlowETL(saved_count=0)
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = asyncio.run(crawler.collect_money_flow())

        self.assertEqual(result["success"], 0)
        self.assertEqual(records[0][0][2], "no_saved")
        self.assertEqual(records[0][1]["fetched"], 1)
        self.assertEqual(records[0][1]["saved"], 0)

    def test_money_flow_write_error_is_recorded_as_error(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakeMoneyFlowSourceChain([
            {"date": "2026-05-06", "main_inflow": 1234567.8}
        ])
        crawler.money_flow_etl = types.SimpleNamespace(save=AsyncMock(side_effect=RuntimeError("write failed")))
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = asyncio.run(crawler.collect_money_flow())

        self.assertEqual(result["success"], 0)
        self.assertEqual(records[0][0][2], "error")
        self.assertIn("write failed", records[0][1]["error_message"])

    def test_realtime_quote_task_fetches_writes_and_records_status(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakeRealtimeQuoteSourceChain([{
            "date": "2026-05-06 09:35:00",
            "open": 1660.0,
            "high": 1670.0,
            "low": 1658.0,
            "close": 1668.88,
            "volume": 1000,
            "turnover": 5200000.5,
        }])
        crawler.realtime_quote_etl = FakeRealtimeQuoteETL(saved_count=1)
        crawler.minute_etl = crawler.realtime_quote_etl
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = asyncio.run(crawler.collect_realtime_quotes())

        self.assertEqual(result["task"], "realtime_quotes")
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(crawler.source_chain.calls[0]["method_name"], "fetch_kline")
        self.assertEqual(crawler.source_chain.calls[0]["symbol"], "600519")
        self.assertEqual(crawler.source_chain.calls[0]["period"], "5m")
        self.assertEqual(crawler.source_chain.calls[0]["limit"], 1)
        self.assertEqual(crawler.realtime_quote_etl.calls[0]["symbol"], "600519")
        self.assertEqual(crawler.realtime_quote_etl.calls[0]["data"][0]["close"], 1668.88)
        self.assertEqual(records[0][0][1], "realtime_quotes")
        self.assertEqual(records[0][0][2], "success")

    def test_realtime_quote_task_no_saved_is_not_counted_as_success(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakeRealtimeQuoteSourceChain([{
            "date": "2026-05-06 09:35:00",
            "close": 1668.88,
        }])
        crawler.realtime_quote_etl = FakeRealtimeQuoteETL(saved_count=0)
        crawler.minute_etl = crawler.realtime_quote_etl
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = asyncio.run(crawler.collect_realtime_quotes())

        self.assertEqual(result["success"], 0)
        self.assertEqual(records[0][0][2], "no_saved")
        self.assertEqual(records[0][1]["fetched"], 1)
        self.assertEqual(records[0][1]["saved"], 0)

    def test_realtime_quote_write_error_is_recorded_as_error(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler._get_tracked_symbols = lambda: ["600519"]
        crawler.source_chain = FakeRealtimeQuoteSourceChain([{
            "date": "2026-05-06 09:35:00",
            "close": 1668.88,
        }])
        crawler.minute_etl = types.SimpleNamespace(save=AsyncMock(side_effect=RuntimeError("write failed")))
        crawler.realtime_quote_etl = crawler.minute_etl
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = asyncio.run(crawler.collect_realtime_quotes())

        self.assertEqual(result["success"], 0)
        self.assertEqual(records[0][0][2], "error")
        self.assertIn("write failed", records[0][1]["error_message"])

    def test_record_status_failure_is_swallowed(self) -> None:
        crawler = object.__new__(DataCrawler)

        with patch("backend.shared.database.SessionLocal", side_effect=RuntimeError("db down")):
            result = crawler._record_status("600519", "daily_kline", "success", date(2026, 5, 6))

        self.assertIsNone(result)

    def test_insert_do_nothing_generates_postgresql_conflict_clause(self) -> None:
        from sqlalchemy.dialects import postgresql, sqlite
        from backend.shared.models import StockNews
        from backend.services.data_crawler.pipeline.upsert import insert_do_nothing

        values = {
            "stock_symbol": "600519",
            "title": "unit test news",
            "source": "unit",
            "publish_time": date(2026, 5, 6),
        }

        pg_sql = str(insert_do_nothing(
            StockNews,
            values,
            ["stock_symbol", "title", "publish_time"],
            "postgresql",
        ).compile(dialect=postgresql.dialect()))
        sqlite_sql = str(insert_do_nothing(
            StockNews,
            values,
            ["stock_symbol", "title", "publish_time"],
            "sqlite",
        ).compile(dialect=sqlite.dialect()))

        self.assertIn("ON CONFLICT", pg_sql)
        self.assertIn("DO NOTHING", pg_sql)
        self.assertIn("ON CONFLICT", sqlite_sql)

    def test_fallback_chain_skips_unsupported_optional_methods_without_failure(self) -> None:
        from backend.services.data_crawler.sources.fallback_chain import DataSourceChain

        unsupported = UnsupportedOptionalSource()
        supported = SupportedOptionalSource()
        chain = DataSourceChain()
        chain.register_many(unsupported, supported)

        result = asyncio.run(chain.fetch_with_fallback("fetch_stock_notices", symbol="600519", limit=5))

        self.assertEqual(result["source"], "supported")
        self.assertEqual(result["data"], [{"title": "600519-5"}])
        self.assertEqual(unsupported.circuit_breaker.failure_count, 0)
        self.assertEqual(supported.circuit_breaker.success_count, 1)

    def test_news_etl_write_error_is_not_reported_as_no_saved(self) -> None:
        from backend.services.data_crawler.pipeline.news_etl import NewsETL

        db = Mock()
        db.get_bind.return_value.dialect.name = "sqlite"
        db.execute.side_effect = RuntimeError("write failed")

        with self.assertRaisesRegex(RuntimeError, "write failed"):
            asyncio.run(NewsETL().save(
                db,
                "600519",
                [{"title": "unit test news", "publish_time": "2026-05-06", "source": "unit"}],
            ))

        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    def test_manual_news_crawl_returns_inline_status_when_status_write_fails(self) -> None:
        from backend.services.market_service.app.api.v1 import crawl

        class FakeChain:
            async def fetch_stock_news(self, symbol: str, limit: int = 30):
                return [{"title": "unit test news"}]

            async def close(self):
                pass

        class FakeNewsETL:
            async def save(self, db, symbol: str, news: list[dict]):
                return 0

        db = Mock()
        with patch("backend.shared.database.SessionLocal", return_value=db), \
             patch("backend.services.data_crawler.sources.news_source.create_news_chain", return_value=FakeChain()), \
             patch("backend.services.data_crawler.pipeline.news_etl.NewsETL", return_value=FakeNewsETL()), \
             patch.object(crawl, "_save_crawl_status", return_value=None):
            result = asyncio.run(crawl.crawl_stock_news("600519", current_user=Mock()))

        self.assertEqual(result["status"], "no_saved")
        self.assertEqual(result["crawl_status"]["status"], "no_saved")
        self.assertEqual(result["saved"], 0)
        db.close.assert_called_once()

    def test_unimplemented_task_records_observable_status(self) -> None:
        crawler = object.__new__(DataCrawler)
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = crawler._mark_task_not_implemented("weekly_kline")

        self.assertEqual(result["status"], "not_implemented")
        self.assertEqual(records[0][0][0], "GLOBAL")
        self.assertEqual(records[0][0][1], "weekly_kline")
        self.assertEqual(records[0][0][2], "not_implemented")

    def test_empty_symbol_pool_records_observable_status(self) -> None:
        crawler = object.__new__(DataCrawler)
        records = []
        crawler._record_status = lambda *args, **kwargs: records.append((args, kwargs))

        result = crawler._mark_empty_symbol_pool("daily_kline")

        self.assertEqual(result["status"], "empty_symbol_pool")
        self.assertEqual(result["success"], 0)
        self.assertEqual(result["total"], 0)
        self.assertEqual(records[0][0][0], "GLOBAL")
        self.assertEqual(records[0][0][1], "daily_kline")
        self.assertEqual(records[0][0][2], "empty_symbol_pool")

    def test_shutdown_async_closes_scheduler_and_chains(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler.scheduler = Mock()
        crawler.scheduler.running = True
        crawler.source_chain = AsyncCloseRecorder()
        crawler.news_chain = AsyncCloseRecorder()

        asyncio.run(crawler.shutdown_async())

        crawler.scheduler.shutdown.assert_called_once()
        self.assertTrue(crawler.source_chain.closed)
        self.assertTrue(crawler.news_chain.closed)

    def test_shutdown_async_continues_when_chain_close_fails(self) -> None:
        crawler = object.__new__(DataCrawler)
        crawler.scheduler = Mock()
        crawler.scheduler.running = False
        crawler.source_chain = AsyncCloseRecorder(should_fail=True)
        crawler.news_chain = AsyncCloseRecorder()

        asyncio.run(crawler.shutdown_async())

        self.assertTrue(crawler.source_chain.closed)
        self.assertTrue(crawler.news_chain.closed)

    def test_tracked_symbols_are_loaded_from_watchlists_when_available(self) -> None:
        crawler = object.__new__(DataCrawler)
        db = Mock()
        query = db.query.return_value
        query.join.return_value = query
        query.filter.return_value = query
        query.distinct.return_value = query
        query.all.return_value = [("600519.SH",), ("000858",), ("600519",)]

        with patch("backend.shared.database.SessionLocal", return_value=db):
            symbols = crawler._get_tracked_symbols()

        self.assertEqual(symbols, ["000858", "600519"])
        db.close.assert_called_once()

    def test_production_without_tracked_symbols_does_not_use_demo_defaults(self) -> None:
        crawler = object.__new__(DataCrawler)
        db = Mock()
        query = db.query.return_value
        query.join.return_value = query
        query.filter.return_value = query
        query.distinct.return_value = query
        query.all.return_value = []

        with patch.dict(
            "os.environ",
            {
                "APP_ENV": "production",
                "DATA_CRAWLER_FALLBACK_SYMBOLS": "",
                "DB_USER": "unit_test",
                "DB_PASS": "unit_test_password",
            },
            clear=False,
        ):
            with patch("backend.shared.database.SessionLocal", return_value=db):
                symbols = crawler._get_tracked_symbols()

        self.assertEqual(symbols, [])
        db.close.assert_called_once()
