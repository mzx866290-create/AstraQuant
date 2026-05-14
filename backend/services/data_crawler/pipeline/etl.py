"""ETL pipeline for cleaning K-line data and writing it to ClickHouse."""
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

CLICKHOUSE_WRITE_METADATA_COLUMNS = ("record_version", "updated_at", "etl_batch_id")


class ClickHouseWriteUnavailable(RuntimeError):
    """Raised when K-line rows cannot be durably written to ClickHouse."""


def _clickhouse_table_name(env_name: str, default: str) -> str:
    table = os.getenv(env_name, default)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ClickHouseWriteUnavailable(f"invalid ClickHouse table name: {table!r}")
    return table


def _create_clickhouse_client():
    try:
        from clickhouse_driver import Client
    except Exception as exc:
        raise ClickHouseWriteUnavailable("clickhouse-driver is not installed") from exc

    host = os.getenv("CLICKHOUSE_HOST", "localhost")
    try:
        port = int(os.getenv("CLICKHOUSE_NATIVE_PORT", "9000"))
    except ValueError as exc:
        raise ClickHouseWriteUnavailable("invalid CLICKHOUSE_NATIVE_PORT") from exc
    user = os.getenv("CLICKHOUSE_USER", "default")
    password = os.getenv("CLICKHOUSE_PASSWORD", "")
    database = os.getenv("CLICKHOUSE_DATABASE", "default")

    return Client(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        connect_timeout=3,
        send_receive_timeout=10,
    )


def _close_clickhouse_client(client) -> None:
    disconnect = getattr(client, "disconnect", None)
    if callable(disconnect):
        try:
            disconnect()
        except Exception:
            logger.debug("failed to disconnect ClickHouse client cleanly", exc_info=True)


def _sql_literal(value) -> str:
    if isinstance(value, datetime):
        return f"toDateTime('{value.strftime('%Y-%m-%d %H:%M:%S')}')"
    if isinstance(value, date):
        return f"toDate('{value.isoformat()}')"
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\r", "\\r")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        return f"'{escaped}'"
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return "NULL"
    return str(value)


def _build_delete_predicate(rows: list[dict], key_columns: list[str]) -> str:
    seen = set()
    key_tuples = []
    for row in rows:
        key = tuple(row[column] for column in key_columns)
        if key in seen:
            continue
        seen.add(key)
        key_tuples.append(key)

    if len(key_columns) == 1:
        values = ", ".join(_sql_literal(key[0]) for key in key_tuples)
        return f"{key_columns[0]} IN ({values})"

    tuple_values = ", ".join(
        f"({', '.join(_sql_literal(value) for value in key)})"
        for key in key_tuples
    )
    return f"({', '.join(key_columns)}) IN ({tuple_values})"


def _dedupe_rows_by_key(rows: list[dict], key_columns: list[str]) -> list[dict]:
    deduped_by_key = {}
    for row in rows:
        key = tuple(row[column] for column in key_columns)
        deduped_by_key[key] = row
    return list(deduped_by_key.values())


def _with_write_metadata(rows: list[dict]) -> list[dict]:
    if not rows:
        return []

    written_at = datetime.utcnow()
    record_version = int(written_at.timestamp() * 1_000_000)
    batch_id = uuid4().hex
    enriched_rows = []

    for row in rows:
        enriched = dict(row)
        enriched.setdefault("record_version", record_version)
        enriched.setdefault("updated_at", written_at)
        enriched.setdefault("etl_batch_id", batch_id)
        enriched_rows.append(enriched)

    return enriched_rows


def _write_rows_to_clickhouse(
    *,
    table: str,
    columns: list[str],
    rows: list[dict],
    key_columns: list[str],
    row_label: str,
) -> int:
    if not rows:
        return 0

    rows = _dedupe_rows_by_key(rows, key_columns)
    values = [tuple(row[column] for column in columns) for row in rows]
    client = _create_clickhouse_client()

    try:
        predicate = _build_delete_predicate(rows, key_columns)
        client.execute(f"ALTER TABLE {table} DELETE WHERE {predicate} SETTINGS mutations_sync = 1")
        client.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES", values)
        logger.debug("wrote %s %s rows to ClickHouse", len(rows), row_label)
        return len(rows)
    except Exception as exc:
        raise ClickHouseWriteUnavailable(f"ClickHouse write failed: {exc}") from exc
    finally:
        _close_clickhouse_client(client)


class KLineETL:
    """K-line ETL pipeline."""

    async def save_daily_kline(
        self,
        symbol: str,
        data: list[dict],
        source: str,
        adjust_flag: int = 1,
    ) -> int:
        if not data:
            logger.warning("[%s] no K-line data to write", symbol)
            return 0

        cleaned_by_key = {}
        for item in data:
            row = self._clean_row(symbol, item, source, adjust_flag)
            if row:
                cleaned_by_key[(row["symbol"], row["date"], row["adjust_flag"])] = row

        cleaned = list(cleaned_by_key.values())

        if not cleaned:
            logger.warning("[%s] no valid K-line rows after cleaning", symbol)
            return 0

        await self._batch_write(cleaned)
        logger.info("[%s] wrote %s K-line rows", symbol, len(cleaned))
        return len(cleaned)

    def _clean_row(self, symbol: str, item: dict, source: str, adjust_flag: int) -> Optional[dict]:
        try:
            open_px = float(item.get("open", 0))
            high = float(item.get("high", 0))
            low = float(item.get("low", 0))
            close = float(item.get("close", 0))
            volume = int(float(item.get("volume", 0)))
            turnover = float(item.get("turnover", 0))

            if high < low or high < max(open_px, close) or low > min(open_px, close):
                logger.debug("[%s] skipped invalid OHLC row: %s", symbol, item.get("date"))
                return None

            date_val = item.get("date", "")
            if not date_val:
                return None

            return {
                "symbol": symbol[:6],
                "name": item.get("name", ""),
                "date": self._parse_date(date_val),
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "turnover": turnover,
                "change_pct": float(item.get("change_pct", 0)),
                "change": float(item.get("change", 0)),
                "amplitude": float(item.get("amplitude", 0)),
                "turnover_rate": float(item.get("turnover_rate", 0)),
                "up_limit": float(item.get("up_limit", 0)),
                "down_limit": float(item.get("down_limit", 0)),
                "pe_ttm": float(item.get("pe_ttm", 0)),
                "total_mv": float(item.get("total_mv", 0)),
                "circ_mv": float(item.get("circ_mv", 0)),
                "adjust_flag": adjust_flag,
                "source": source,
            }
        except (ValueError, TypeError) as exc:
            logger.debug("[%s] failed to parse K-line row: %s", symbol, exc)
            return None

    async def _batch_write(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        rows = _with_write_metadata(rows)
        table = _clickhouse_table_name("CLICKHOUSE_STOCK_DAILY_TABLE", "stock_daily")
        columns = [
            "symbol",
            "name",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "change_pct",
            "change",
            "amplitude",
            "turnover_rate",
            "up_limit",
            "down_limit",
            "pe_ttm",
            "total_mv",
            "circ_mv",
            "adjust_flag",
            "source",
            *CLICKHOUSE_WRITE_METADATA_COLUMNS,
        ]
        return _write_rows_to_clickhouse(
            table=table,
            columns=columns,
            rows=rows,
            key_columns=["symbol", "date", "adjust_flag"],
            row_label="K-line",
        )

    @staticmethod
    def _parse_date(value) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


class MoneyFlowETL:
    """Clean money flow rows and write them to ClickHouse."""

    async def save_money_flow(self, symbol: str, data: list[dict], source: str) -> int:
        return await self.save(symbol, data, source)

    async def save(self, symbol: str, data: list[dict], source: str) -> int:
        if not data:
            logger.warning("[%s] no money flow data to write", symbol)
            return 0

        cleaned_by_key = {}
        for item in data:
            row = self._clean_row(symbol, item, source)
            if row:
                cleaned_by_key[(row["symbol"], row["date"])] = row

        cleaned = list(cleaned_by_key.values())
        if not cleaned:
            logger.warning("[%s] no valid money flow rows after cleaning", symbol)
            return 0

        await self._batch_write(cleaned)
        logger.info("[%s] wrote %s money flow rows", symbol, len(cleaned))
        return len(cleaned)

    def _clean_row(self, symbol: str, item: dict, source: str) -> Optional[dict]:
        date_value = item.get("date")
        if not date_value:
            return None
        return {
            "symbol": symbol[:6],
            "date": self._parse_date(date_value),
            "main_net_inflow": self._safe_float(item.get("main_inflow")),
            "small_net_inflow": self._safe_float(item.get("small_inflow")),
            "mid_net_inflow": self._safe_float(item.get("mid_inflow")),
            "big_net_inflow": self._safe_float(item.get("big_inflow")),
            "super_net_inflow": self._safe_float(item.get("super_inflow")),
            "main_pct": self._safe_float(item.get("main_pct")),
            "source": source,
        }

    async def _batch_write(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        rows = _with_write_metadata(rows)
        table = _clickhouse_table_name("CLICKHOUSE_MONEY_FLOW_TABLE", "money_flow")
        columns = [
            "symbol",
            "date",
            "main_net_inflow",
            "small_net_inflow",
            "mid_net_inflow",
            "big_net_inflow",
            "super_net_inflow",
            "main_pct",
            "source",
            *CLICKHOUSE_WRITE_METADATA_COLUMNS,
        ]
        return _write_rows_to_clickhouse(
            table=table,
            columns=columns,
            rows=rows,
            key_columns=["symbol", "date"],
            row_label="money flow",
        )

    @staticmethod
    def _safe_float(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_date(value) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if re.fullmatch(r"\d{8}", text):
            return datetime.strptime(text, "%Y%m%d").date()
        return datetime.strptime(text[:10], "%Y-%m-%d").date()


class MinuteKLineETL:
    """Clean minute-level rows and write them to ClickHouse."""

    async def save_minute_snapshot(self, symbol: str, data: dict, source: str = "") -> int:
        return await self.save(symbol, [data])

    async def save(self, symbol: str, data: list[dict]) -> int:
        if not data:
            logger.warning("[%s] no minute rows to write", symbol)
            return 0

        cleaned_by_key = {}
        for item in data:
            row = self._clean_row(symbol, item)
            if row:
                cleaned_by_key[(row["symbol"], row["timestamp"])] = row

        cleaned = list(cleaned_by_key.values())
        if not cleaned:
            logger.warning("[%s] no valid minute rows after cleaning", symbol)
            return 0

        await self._batch_write(cleaned)
        logger.info("[%s] wrote %s minute rows", symbol, len(cleaned))
        return len(cleaned)

    def _clean_row(self, symbol: str, item: dict) -> Optional[dict]:
        timestamp_value = item.get("date") or item.get("timestamp")
        if not timestamp_value:
            return None

        open_px = self._safe_float(item.get("open", item.get("price")))
        high = self._safe_float(item.get("high", item.get("price")))
        low = self._safe_float(item.get("low", item.get("price")))
        close = self._safe_float(item.get("close", item.get("price")))
        if high < low or high < max(open_px, close) or low > min(open_px, close):
            logger.debug("[%s] skipped invalid minute row: %s", symbol, timestamp_value)
            return None

        return {
            "symbol": symbol[:6],
            "timestamp": self._parse_timestamp(timestamp_value),
            "open": open_px,
            "high": high,
            "low": low,
            "close": close,
            "volume": int(float(item.get("volume", 0) or 0)),
            "turnover": self._safe_float(item.get("turnover")),
            "trade_status": str(item.get("trade_status", ""))[:32],
            "market": self._market(symbol),
        }

    async def _batch_write(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        rows = _with_write_metadata(rows)
        table = _clickhouse_table_name("CLICKHOUSE_STOCK_MINUTE_TABLE", "stock_minute")
        columns = [
            "symbol",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "trade_status",
            "market",
            *CLICKHOUSE_WRITE_METADATA_COLUMNS,
        ]
        return _write_rows_to_clickhouse(
            table=table,
            columns=columns,
            rows=rows,
            key_columns=["symbol", "timestamp"],
            row_label="minute",
        )

    @staticmethod
    def _safe_float(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_timestamp(value) -> datetime:
        if isinstance(value, datetime):
            return value
        text = str(value or "").strip().replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(text[:19], fmt)
            except ValueError:
                continue
        raise ValueError(f"invalid minute timestamp: {value!r}")

    @staticmethod
    def _market(symbol: str) -> str:
        code = symbol[:6]
        if code.startswith(("6", "9", "5")):
            return "SH"
        if code.startswith(("0", "1", "2", "3")):
            return "SZ"
        if code.startswith(("4", "8")):
            return "BJ"
        return ""


class RealtimeQuoteETL(MinuteKLineETL):
    """Compatibility alias for minute snapshot persistence."""


class WeeklyKLineETL:
    """Clean weekly K-line rows and write them to ClickHouse."""

    async def save(self, symbol: str, data: list[dict], source: str) -> int:
        return await self._save_period(symbol, data, "week_start", "CLICKHOUSE_STOCK_WEEKLY_TABLE", "stock_weekly")

    async def _save_period(
        self,
        symbol: str,
        data: list[dict],
        period_column: str,
        table_env: str,
        table_default: str,
    ) -> int:
        if not data:
            logger.warning("[%s] no %s rows to write", symbol, period_column)
            return 0

        cleaned_by_key = {}
        for item in data:
            row = self._clean_row(symbol, item, period_column)
            if row:
                cleaned_by_key[(row["symbol"], row[period_column])] = row

        cleaned = list(cleaned_by_key.values())
        if not cleaned:
            logger.warning("[%s] no valid %s rows after cleaning", symbol, period_column)
            return 0

        await self._batch_write(cleaned, period_column, table_env, table_default)
        logger.info("[%s] wrote %s %s rows", symbol, len(cleaned), period_column)
        return len(cleaned)

    def _clean_row(self, symbol: str, item: dict, period_column: str) -> Optional[dict]:
        date_value = item.get("start_date") or item.get("date")
        if not date_value:
            return None
        period_start = self._period_start(date_value, period_column)
        open_px = self._safe_float(item.get("open"))
        high = self._safe_float(item.get("high"))
        low = self._safe_float(item.get("low"))
        close = self._safe_float(item.get("close"))
        if high < low or high < max(open_px, close) or low > min(open_px, close):
            logger.debug("[%s] skipped invalid %s row: %s", symbol, period_column, date_value)
            return None
        return {
            "symbol": symbol[:6],
            period_column: period_start,
            "open": open_px,
            "high": high,
            "low": low,
            "close": close,
            "volume": int(float(item.get("volume", 0) or 0)),
            "turnover": self._safe_float(item.get("turnover")),
            "change_pct": self._safe_float(item.get("change_pct")),
            "amplitude": self._safe_float(item.get("amplitude")),
        }

    async def _batch_write(
        self,
        rows: list[dict],
        period_column: str,
        table_env: str,
        table_default: str,
    ) -> int:
        if not rows:
            return 0

        rows = _with_write_metadata(rows)
        table = _clickhouse_table_name(table_env, table_default)
        columns = [
            "symbol",
            period_column,
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "change_pct",
            "amplitude",
            *CLICKHOUSE_WRITE_METADATA_COLUMNS,
        ]
        return _write_rows_to_clickhouse(
            table=table,
            columns=columns,
            rows=rows,
            key_columns=["symbol", period_column],
            row_label=period_column,
        )

    @staticmethod
    def _period_start(value, period_column: str) -> date:
        current = WeeklyKLineETL._parse_date(value)
        if period_column == "week_start":
            return current - timedelta(days=current.weekday())
        return current.replace(day=1)

    @staticmethod
    def _parse_date(value) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if re.fullmatch(r"\d{8}", text):
            return datetime.strptime(text, "%Y%m%d").date()
        return datetime.strptime(text[:10], "%Y-%m-%d").date()

    @staticmethod
    def _safe_float(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


class MonthlyKLineETL(WeeklyKLineETL):
    """Clean monthly K-line rows and write them to ClickHouse."""

    async def save(self, symbol: str, data: list[dict], source: str) -> int:
        return await self._save_period(symbol, data, "month_start", "CLICKHOUSE_STOCK_MONTHLY_TABLE", "stock_monthly")
