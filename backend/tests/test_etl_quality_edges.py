import sys
import types
from datetime import date, datetime
from unittest import TestCase
from unittest.mock import patch

from backend.services.data_crawler.pipeline import etl
from backend.services.data_crawler.pipeline.etl import ClickHouseWriteUnavailable, KLineETL


def kline_source_row(**overrides):
    row = {
        "name": "Kweichow Moutai",
        "date": "2026-05-06",
        "open": "10.5",
        "high": "12.0",
        "low": "10.0",
        "close": "11.5",
        "volume": "1000.8",
        "turnover": "12000.5",
        "change_pct": "1.2",
        "change": "0.13",
        "amplitude": "2.0",
        "turnover_rate": "0.5",
        "up_limit": "12.1",
        "down_limit": "9.9",
        "pe_ttm": "25.0",
        "total_mv": "1000000.0",
        "circ_mv": "900000.0",
    }
    row.update(overrides)
    return row


class ClickHouseHelperEdgeTests(TestCase):
    def test_clickhouse_table_name_accepts_valid_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                etl._clickhouse_table_name("CLICKHOUSE_STOCK_DAILY_TABLE", "stock_daily"),
                "stock_daily",
            )

    def test_clickhouse_table_name_rejects_invalid_env_value(self) -> None:
        with patch.dict("os.environ", {"CLICKHOUSE_STOCK_DAILY_TABLE": "stock-daily"}, clear=True):
            with self.assertRaisesRegex(ClickHouseWriteUnavailable, "invalid ClickHouse table name"):
                etl._clickhouse_table_name("CLICKHOUSE_STOCK_DAILY_TABLE", "stock_daily")

    def test_create_clickhouse_client_wraps_missing_driver(self) -> None:
        with patch.dict(sys.modules, {"clickhouse_driver": None}):
            with self.assertRaisesRegex(ClickHouseWriteUnavailable, "clickhouse-driver is not installed"):
                etl._create_clickhouse_client()

    def test_create_clickhouse_client_rejects_invalid_port(self) -> None:
        fake_module = types.SimpleNamespace(Client=lambda **kwargs: object())
        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict("os.environ", {"CLICKHOUSE_NATIVE_PORT": "not-a-port"}, clear=True):
                with self.assertRaisesRegex(ClickHouseWriteUnavailable, "invalid CLICKHOUSE_NATIVE_PORT"):
                    etl._create_clickhouse_client()

    def test_create_clickhouse_client_passes_expected_connection_args(self) -> None:
        init_calls = []

        class FakeClient:
            def __init__(self, **kwargs):
                init_calls.append(kwargs)

        fake_module = types.SimpleNamespace(Client=FakeClient)
        env = {
            "CLICKHOUSE_HOST": "clickhouse.internal",
            "CLICKHOUSE_NATIVE_PORT": "9440",
            "CLICKHOUSE_USER": "etl_user",
            "CLICKHOUSE_PASSWORD": "secret",
            "CLICKHOUSE_DATABASE": "market",
        }

        with patch.dict(sys.modules, {"clickhouse_driver": fake_module}):
            with patch.dict("os.environ", env, clear=True):
                client = etl._create_clickhouse_client()

        self.assertIsInstance(client, FakeClient)
        self.assertEqual(init_calls, [{
            "host": "clickhouse.internal",
            "port": 9440,
            "user": "etl_user",
            "password": "secret",
            "database": "market",
            "connect_timeout": 3,
            "send_receive_timeout": 10,
        }])

    def test_close_clickhouse_client_ignores_missing_disconnect(self) -> None:
        etl._close_clickhouse_client(object())

    def test_close_clickhouse_client_swallows_disconnect_errors(self) -> None:
        calls = []

        class BrokenClient:
            def disconnect(self):
                calls.append("disconnect")
                raise RuntimeError("socket already closed")

        etl._close_clickhouse_client(BrokenClient())

        self.assertEqual(calls, ["disconnect"])

    def test_sql_literal_formats_supported_values(self) -> None:
        cases = [
            (datetime(2026, 5, 6, 9, 30, 45), "toDateTime('2026-05-06 09:30:45')"),
            (date(2026, 5, 6), "toDate('2026-05-06')"),
            ("O'Reilly\\path\r\n\t", "'O\\'Reilly\\\\path\\r\\n\\t'"),
            (True, "1"),
            (False, "0"),
            (None, "NULL"),
            (42, "42"),
            (12.5, "12.5"),
        ]

        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(etl._sql_literal(value), expected)


class RowPreparationEdgeTests(TestCase):
    def test_build_delete_predicate_dedupes_single_key_values(self) -> None:
        rows = [
            {"symbol": "600519"},
            {"symbol": "000001"},
            {"symbol": "600519"},
        ]

        self.assertEqual(
            etl._build_delete_predicate(rows, ["symbol"]),
            "symbol IN ('600519', '000001')",
        )

    def test_build_delete_predicate_dedupes_multi_key_values(self) -> None:
        rows = [
            {"symbol": "600519", "date": date(2026, 5, 6)},
            {"symbol": "000001", "date": date(2026, 5, 7)},
            {"symbol": "600519", "date": date(2026, 5, 6)},
        ]

        self.assertEqual(
            etl._build_delete_predicate(rows, ["symbol", "date"]),
            "(symbol, date) IN (('600519', toDate('2026-05-06')), ('000001', toDate('2026-05-07')))",
        )

    def test_dedupe_rows_by_key_keeps_last_row_for_same_key(self) -> None:
        rows = [
            {"symbol": "600519", "date": date(2026, 5, 6), "close": 11.0},
            {"symbol": "000001", "date": date(2026, 5, 6), "close": 10.0},
            {"symbol": "600519", "date": date(2026, 5, 6), "close": 12.0},
        ]

        deduped = etl._dedupe_rows_by_key(rows, ["symbol", "date"])
        by_symbol = {row["symbol"]: row for row in deduped}

        self.assertEqual(len(deduped), 2)
        self.assertEqual(by_symbol["600519"]["close"], 12.0)
        self.assertEqual(by_symbol["000001"]["close"], 10.0)

    def test_with_write_metadata_returns_empty_list_for_empty_rows(self) -> None:
        self.assertEqual(etl._with_write_metadata([]), [])

    def test_with_write_metadata_adds_defaults_without_overwriting_existing_values(self) -> None:
        explicit_updated_at = datetime(2026, 5, 6, 9, 30, 0)
        rows = [
            {"symbol": "600519"},
            {
                "symbol": "000001",
                "record_version": 20260506093000000,
                "updated_at": explicit_updated_at,
                "etl_batch_id": "manual-batch",
            },
        ]

        enriched = etl._with_write_metadata(rows)

        self.assertNotIn("record_version", rows[0])
        self.assertIsInstance(enriched[0]["record_version"], int)
        self.assertIsInstance(enriched[0]["updated_at"], datetime)
        self.assertRegex(enriched[0]["etl_batch_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(enriched[1]["record_version"], 20260506093000000)
        self.assertEqual(enriched[1]["updated_at"], explicit_updated_at)
        self.assertEqual(enriched[1]["etl_batch_id"], "manual-batch")


class ClickHouseWriteEdgeTests(TestCase):
    def test_write_rows_to_clickhouse_returns_zero_for_empty_rows_without_client(self) -> None:
        with patch.object(etl, "_create_clickhouse_client") as create_client:
            saved = etl._write_rows_to_clickhouse(
                table="stock_daily",
                columns=["symbol", "date", "close"],
                rows=[],
                key_columns=["symbol", "date"],
                row_label="K-line",
            )

        self.assertEqual(saved, 0)
        create_client.assert_not_called()

    def test_write_rows_to_clickhouse_deletes_then_inserts_and_closes_client(self) -> None:
        calls = []

        class FakeClient:
            def execute(self, query, values=None):
                calls.append(("execute", query, values))

            def disconnect(self):
                calls.append(("disconnect",))

        rows = [
            {"symbol": "600519", "date": date(2026, 5, 6), "close": 11.0},
            {"symbol": "600519", "date": date(2026, 5, 6), "close": 12.0},
            {"symbol": "000001", "date": date(2026, 5, 7), "close": 10.0},
        ]

        with patch.object(etl, "_create_clickhouse_client", return_value=FakeClient()):
            saved = etl._write_rows_to_clickhouse(
                table="stock_daily",
                columns=["symbol", "date", "close"],
                rows=rows,
                key_columns=["symbol", "date"],
                row_label="K-line",
            )

        self.assertEqual(saved, 2)
        self.assertEqual(calls[0][0], "execute")
        self.assertEqual(
            calls[0][1],
            "ALTER TABLE stock_daily DELETE WHERE (symbol, date) IN "
            "(('600519', toDate('2026-05-06')), ('000001', toDate('2026-05-07'))) "
            "SETTINGS mutations_sync = 1",
        )
        self.assertEqual(calls[1], (
            "execute",
            "INSERT INTO stock_daily (symbol, date, close) VALUES",
            [
                ("600519", date(2026, 5, 6), 12.0),
                ("000001", date(2026, 5, 7), 10.0),
            ],
        ))
        self.assertEqual(calls[2], ("disconnect",))

    def test_write_rows_to_clickhouse_wraps_execute_failure_and_closes_client(self) -> None:
        calls = []

        class BrokenClient:
            def execute(self, query, values=None):
                calls.append(("execute", query, values))
                raise RuntimeError("delete failed")

            def disconnect(self):
                calls.append(("disconnect",))

        with patch.object(etl, "_create_clickhouse_client", return_value=BrokenClient()):
            with self.assertRaisesRegex(ClickHouseWriteUnavailable, "delete failed"):
                etl._write_rows_to_clickhouse(
                    table="stock_daily",
                    columns=["symbol", "date", "close"],
                    rows=[{"symbol": "600519", "date": date(2026, 5, 6), "close": 11.0}],
                    key_columns=["symbol", "date"],
                    row_label="K-line",
                )

        self.assertEqual(calls[-1], ("disconnect",))


class KLineCleanRowEdgeTests(TestCase):
    def test_clean_row_returns_normalized_valid_row(self) -> None:
        row = KLineETL()._clean_row("600519.SH", kline_source_row(), "unit-test", 2)

        self.assertEqual(row["symbol"], "600519")
        self.assertEqual(row["name"], "Kweichow Moutai")
        self.assertEqual(row["date"], date(2026, 5, 6))
        self.assertEqual(row["open"], 10.5)
        self.assertEqual(row["high"], 12.0)
        self.assertEqual(row["low"], 10.0)
        self.assertEqual(row["close"], 11.5)
        self.assertEqual(row["volume"], 1000)
        self.assertEqual(row["turnover"], 12000.5)
        self.assertEqual(row["adjust_flag"], 2)
        self.assertEqual(row["source"], "unit-test")

    def test_clean_row_rejects_invalid_ohlc(self) -> None:
        row = KLineETL()._clean_row(
            "600519",
            kline_source_row(high="10.5", low="10.0", open="11.0", close="10.2"),
            "unit-test",
            1,
        )

        self.assertIsNone(row)

    def test_clean_row_rejects_missing_date(self) -> None:
        row = KLineETL()._clean_row("600519", kline_source_row(date=""), "unit-test", 1)

        self.assertIsNone(row)

    def test_clean_row_rejects_non_numeric_price(self) -> None:
        row = KLineETL()._clean_row("600519", kline_source_row(open="not-a-number"), "unit-test", 1)

        self.assertIsNone(row)

    def test_clean_row_parses_string_date_date_and_datetime_values(self) -> None:
        cases = [
            ("2026-05-06 15:00:00", date(2026, 5, 6)),
            (date(2026, 5, 7), date(2026, 5, 7)),
            (datetime(2026, 5, 8, 15, 0, 0), date(2026, 5, 8)),
        ]

        for raw_date, expected in cases:
            with self.subTest(raw_date=raw_date):
                row = KLineETL()._clean_row(
                    "600519",
                    kline_source_row(date=raw_date),
                    "unit-test",
                    1,
                )

                self.assertEqual(row["date"], expected)
