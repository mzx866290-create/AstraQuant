"""
Sina/Tencent public quote source.

This source is intentionally small and dependency-light. EastMoney and AKShare
can be unstable behind local proxies, while Sina/Tencent quote endpoints are
often enough for realtime quote, daily K-line, PE and PB fallback.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Optional

import requests

from .base import BaseDataSource


class SinaTencentSource(BaseDataSource):
    def __init__(self):
        super().__init__(name="Sina/Tencent", priority=3)

    def _code(self, symbol: str) -> str:
        match = re.search(r"\d{6}", (symbol or "").upper())
        return match.group(0) if match else ""

    def _market(self, symbol: str) -> str:
        text = (symbol or "").strip().upper()
        code = self._code(text)
        if text.endswith(".BJ") or text.startswith("BJ"):
            return "BJ"
        if text.endswith(".SH") or text.endswith(".SS") or text.startswith("SH"):
            return "SH"
        if text.endswith(".SZ") or text.startswith("SZ"):
            return "SZ"
        if code.startswith(("4", "8", "920")):
            return "BJ"
        if code.startswith(("5", "6", "9")):
            return "SH"
        return "SZ"

    def _market_prefix(self, symbol: str) -> str:
        return self._market(symbol).lower()

    def _tencent_symbol(self, symbol: str) -> str:
        return f"{self._market_prefix(symbol)}{self._code(symbol)}"

    async def fetch_daily_kline(
        self, symbol: str, start_date: str = "", end_date: str = "", adjust: str = ""
    ) -> list[dict]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._fetch_daily_kline_sync(symbol, start_date=start_date, end_date=end_date),
        )

    def _fetch_daily_kline_sync(
        self,
        symbol: str,
        limit: int = 240,
        start_date: str = "",
        end_date: str = "",
    ) -> list[dict]:
        sec = self._tencent_symbol(symbol)
        url = "https://quotes.sina.cn/cn/api/openapi.php/CN_MarketDataService.getKLineData"
        resp = requests.get(
            url,
            params={"symbol": sec, "scale": "240", "ma": "no", "datalen": str(limit)},
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = ((payload.get("result") or {}).get("data") or [])
        result = []
        for row in rows:
            try:
                result.append({
                    "date": str(row.get("day", "")),
                    "open": float(row.get("open") or 0),
                    "high": float(row.get("high") or 0),
                    "low": float(row.get("low") or 0),
                    "close": float(row.get("close") or 0),
                    "volume": int(float(row.get("volume") or 0)),
                    "turnover": float(row.get("turnover") or 0) if row.get("turnover") else 0.0,
                })
            except (TypeError, ValueError):
                continue

        for idx, item in enumerate(result):
            if idx == 0:
                item["change_pct"] = 0.0
            else:
                prev = result[idx - 1]["close"]
                item["change_pct"] = round((item["close"] - prev) / prev * 100, 2) if prev else 0.0
        if start_date:
            result = [row for row in result if str(row.get("date", ""))[:10] >= start_date[:10]]
        if end_date:
            result = [row for row in result if str(row.get("date", ""))[:10] <= end_date[:10]]
        return result

    async def fetch_realtime_quote(self, symbol: str) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._fetch_realtime_quote_sync(symbol))

    def _fetch_realtime_quote_sync(self, symbol: str) -> dict:
        sec = self._tencent_symbol(symbol)
        resp = requests.get(
            "https://qt.gtimg.cn/q=" + sec,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12,
        )
        resp.raise_for_status()
        text = resp.content.decode("gbk", errors="ignore").strip()
        match = re.search(r'="(.*)"', text)
        if not match:
            raise RuntimeError(f"Tencent quote response is empty for {symbol}")
        parts = match.group(1).split("~")
        if len(parts) < 47:
            raise RuntimeError(f"Tencent quote response is incomplete for {symbol}")

        def f(index: int) -> float:
            try:
                return float(parts[index])
            except (IndexError, TypeError, ValueError):
                return 0.0

        timestamp = parts[30] if len(parts) > 30 else ""
        formatted_time = datetime.now().isoformat()
        if len(timestamp) >= 14 and timestamp.isdigit():
            formatted_time = (
                f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}T"
                f"{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}"
            )

        price = f(3)
        prev_close = f(4)
        return {
            "symbol": symbol,
            "name": parts[1] if len(parts) > 1 else symbol,
            "price": price,
            "change": f(31) or round(price - prev_close, 2),
            "change_pct": f(32),
            "high": f(33),
            "low": f(34),
            "open": f(5),
            "volume": int(f(36) * 100),       # Tencent uses hands.
            "turnover": f(37) * 10000,        # ten-thousand yuan -> yuan.
            "turnover_rate": f(38),
            "pe_ttm": f(39),
            "total_mv": f(45) * 100000000,
            "circ_mv": f(44) * 100000000,
            "pb": f(46),
            "timestamp": formatted_time,
            "source": "tencent",
        }

    async def search_stocks(self, query: str) -> list[dict]:
        return []

    async def health_check(self) -> bool:
        try:
            await self.fetch_realtime_quote("000001.SZ")
            return True
        except Exception:
            return False
