"""
东方财富数据源 - A股主要数据源
提供: 实时行情 / 日K线 / 股票搜索 / 资金流向 / 龙虎榜
使用东方财富公开API (无需Token)
"""
import json
import logging
from datetime import datetime
from typing import Optional

import aiohttp
import pandas as pd

from .base import BaseDataSource

logger = logging.getLogger(__name__)


class EastMoneySource(BaseDataSource):
    """
    东方财富数据源 (优先级最高)
    - 免费，无需Token
    - 数据最全：行情/K线/资金流向/龙虎榜/财务数据
    """

    # 东方财富API端点
    BASE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
    KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    SEARCH_URL = "https://searchadapter.eastmoney.com/api/suggest/get"
    MONEY_FLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    MONEY_FLOW_LATEST_URL = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    BATCH_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    KLINE_PERIOD_MAP = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "60m": "60",
        "1d": "101",
        "1w": "102",
        "1M": "103",
    }

    # 东方财富市场代码映射
    MARKET_MAP = {
        "SH": "1",   # 沪市
        "SZ": "0",   # 深市
        "BJ": "0",   # 北交所
    }

    def __init__(self):
        super().__init__(name="东方财富", priority=1)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False, force_close=True)
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://quote.eastmoney.com/",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _to_em_security(self, symbol: str) -> str:
        """转东方财富证券代码: 0.000001 或 1.600519"""
        code = symbol[:6]
        market = self._get_market(symbol)
        secid = self.MARKET_MAP.get(market, "1")
        return f"{secid}.{code}"

    async def fetch_daily_kline(
        self, symbol: str, start_date: str = "", end_date: str = "", adjust: str = "1"
    ) -> list[dict]:
        """
        获取日K线数据
        adjust: 0=不复权 1=前复权 2=后复权
        """
        return await self.fetch_kline(
            symbol=symbol,
            period="1d",
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )

    async def fetch_kline(
        self,
        symbol: str,
        period: str = "1d",
        start_date: str = "",
        end_date: str = "",
        adjust: str = "1",
        limit: int = 500,
    ) -> list[dict]:
        """
        获取日/周/月K线数据。
        period: 1d=日K, 1w=周K, 1M=月K
        adjust: 0=不复权 1=前复权 2=后复权
        """
        klt = self.KLINE_PERIOD_MAP.get(period)
        if not klt:
            raise ValueError(f"unsupported EastMoney kline period: {period}")

        secid = self._to_em_security(symbol)
        params = {
            "secid": secid,
            "ut": "fa5fd1943c7b386f172d6893dbfd32bb",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": klt,
            "fqt": adjust,
            "end": end_date.replace("-", "") if end_date else "20500101",
            "lmt": str(max(1, min(limit, 1000))),
        }
        if start_date:
            params["beg"] = start_date.replace("-", "")

        session = await self._get_session()
        async with session.get(self.KLINE_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        raw = data.get("data", {}) or {}
        klines = raw.get("klines", [])
        result = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 11:
                result.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": int(float(parts[5])),
                    "turnover": float(parts[6]),
                    "change_pct": float(parts[8]) if parts[8] else 0,
                })
        return result

    async def fetch_realtime_quote(self, symbol: str) -> dict:
        """获取A股实时行情"""
        secid = self._to_em_security(symbol)
        params = {
            "secid": secid,
            "ut": "fa5fd1943c7b386f172d6893dbfd32bb",
            "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21",
        }
        session = await self._get_session()
        async with session.get(self.BASE_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        d = data.get("data", {}) or {}
        return {
            "symbol": symbol,
            "name": d.get("f14", ""),
            "price": d.get("f43", 0) or d.get("f2", 0),
            "change": d.get("f169", 0) or d.get("f4", 0),
            "change_pct": d.get("f170", 0) or d.get("f3", 0),
            "high": d.get("f44", 0) or d.get("f15", 0),
            "low": d.get("f45", 0) or d.get("f16", 0),
            "open": d.get("f46", 0) or d.get("f17", 0),
            "volume": int(d.get("f47", 0) or d.get("f5", 0)),
            "turnover": float(d.get("f48", 0) or d.get("f6", 0)),
            "bid": d.get("f19", 0),
            "ask": d.get("f20", 0),
            "total_mv": float(d.get("f20", 0) or 0),   # 总市值
            "circ_mv": float(d.get("f21", 0) or 0),     # 流通市值
            "pe_ttm": float(d.get("f9", 0) or 0),       # 滚动市盈率
            "turnover_rate": float(d.get("f8", 0) or 0), # 换手率
            "timestamp": datetime.now().isoformat(),
        }

    async def search_stocks(self, query: str) -> list[dict]:
        """搜索A股股票"""
        params = {
            "input": query,
            "type": "14",  # 全部
            "token": "fa5fd1943c7b386f172d6893dbfd32bb",
        }
        session = await self._get_session()
        async with session.get(self.SEARCH_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        result = []
        # 东方财富搜索返回格式: QuotationCodeTable.Data
        table_data = data.get("QuotationCodeTable", {}).get("Data", []) or []
        for item in table_data:
            # Classify 为 "AStock" 表示A股
            if item.get("Classify") == "AStock":
                code = item.get("Code", "")
                # JYS: 1=深交所, 2=上交所, 9=北交所
                jys = item.get("JYS", "")
                if jys == "2":
                    market = "SH"
                elif jys == "1":
                    market = "SZ"
                elif jys == "9":
                    market = "BJ"
                else:
                    market = "SH" if code.startswith(("6", "9")) else "SZ"
                result.append({
                    "symbol": f"{code}.{market}",
                    "name": item.get("Name", ""),
                    "market": market,
                    "pinyin": item.get("PinYin", ""),
                })
        return result

    async def fetch_money_flow(self, symbol: str, limit: int = 20) -> list[dict]:
        """获取A股资金流向数据（东方财富特色）"""
        import asyncio
        import requests

        secid = self._to_em_security(symbol)
        params = {
            "secid": secid,
            "ut": "fa5fd1943c7b386f172d6893dbfd32bb",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "lmt": str(max(1, min(limit, 120))),
        }

        def _get_json(url: str, query: dict) -> dict:
            resp = requests.get(
                url,
                params=query,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://quote.eastmoney.com/",
                },
                timeout=12,
            )
            resp.raise_for_status()
            return resp.json()

        def _safe_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def _fetch_rank_current() -> Optional[dict]:
            code = symbol[:6]
            fs = "m:1+t:2,m:1+t:23" if code.startswith(("6", "9")) else "m:0+t:6,m:0+t:80"
            base_query = {
                "po": "0",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f12",
                "fs": fs,
                "fields": "f12,f14,f62,f66,f72,f78,f84",
                "pz": "100",
            }
            url = "https://push2.eastmoney.com/api/qt/clist/get"
            total_pages = 30
            for page in range(1, total_pages + 1):
                query = dict(base_query)
                query["pn"] = str(page)
                payload = _get_json(url, query)
                data = payload.get("data") or {}
                rows = data.get("diff") or []
                if page == 1 and data.get("total"):
                    total_pages = min(60, int((int(data["total"]) + 99) / 100))
                for row in rows:
                    if row.get("f12") != code:
                        continue
                    values = {
                        "main_inflow": _safe_float(row.get("f62")),
                        "super_inflow": _safe_float(row.get("f66")),
                        "big_inflow": _safe_float(row.get("f72")),
                        "mid_inflow": _safe_float(row.get("f78")),
                        "small_inflow": _safe_float(row.get("f84")),
                    }
                    if any(value is not None for value in values.values()):
                        return {
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            **{key: value or 0.0 for key, value in values.items()},
                        }
                    return None
            return None

        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, lambda: _get_json(self.MONEY_FLOW_URL, params))
        except Exception as e:
            logger.info(f"[{symbol}] 资金流向历史数据获取失败，尝试最新资金流: {e}")
            data = {}

        raw = data.get("data", {}) or {}
        klines = raw.get("klines", [])
        result = []
        def parse_line(line: str) -> Optional[dict]:
            parts = line.split(",")
            if len(parts) >= 6:
                try:
                    return {
                        "date": parts[0],
                        "main_inflow": float(parts[1]),   # 主力净流入
                        "small_inflow": float(parts[2]),   # 小单净流入
                        "mid_inflow": float(parts[3]),     # 中单净流入
                        "big_inflow": float(parts[4]),     # 大单净流入
                        "super_inflow": float(parts[5]),   # 超大单净流入
                    }
                except (TypeError, ValueError):
                    return None
            return None

        for line in klines:
            item = parse_line(line)
            if item:
                result.append(item)

        try:
            latest_params = dict(params)
            latest_params["lmt"] = "1"
            latest_data = await loop.run_in_executor(
                None, lambda: _get_json(self.MONEY_FLOW_LATEST_URL, latest_params)
            )
            for line in ((latest_data.get("data") or {}).get("klines") or []):
                item = parse_line(line)
                if not item:
                    continue
                result = [row for row in result if row.get("date") != item["date"]]
                result.append(item)
        except Exception:
            pass

        today = datetime.now().strftime("%Y-%m-%d")
        if not any(row.get("date") == today for row in result):
            try:
                current = await loop.run_in_executor(None, _fetch_rank_current)
                if current:
                    result = [row for row in result if row.get("date") != current["date"]]
                    result.append(current)
            except Exception as e:
                logger.warning(f"[{symbol}] 资金流向排行兜底获取失败: {e}")

        return result[-limit:]

    async def fetch_stock_news(self, symbol: str, limit: int = 15) -> list[dict]:
        """获取个股相关新闻"""
        secid = self._to_em_security(symbol)
        params = {
            "secid": secid,
            "page": "1",
            "size": str(limit),
            "ut": "fa5fd1943c7b386f172d6893dbfd32bb",
        }
        session = await self._get_session()
        async with session.get(
            "https://push2.eastmoney.com/api/qt/stock/news/get",
            params=params,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        items = []
        raw = data.get("data", {}) or {}
        news_list = raw.get("list", []) or []
        for item in news_list:
            title = item.get("title", "")
            summary = item.get("digest", "") or item.get("summary", "")
            source = item.get("source", "")
            url = item.get("url", "")
            publish_time = item.get("showTime", "") or item.get("publishTime", "")
            # 只保留有标题的有效新闻
            if title:
                items.append({
                    "title": title,
                    "summary": summary,
                    "source": source,
                    "url": url,
                    "publish_time": publish_time,
                })
            if len(items) >= limit:
                break
        return items

    async def fetch_announcements(self, symbol: str, limit: int = 20) -> list[dict]:
        """获取个股公告 (东方财富公告API)"""
        secid = self._to_em_security(symbol)
        params = {
            "secid": secid,
            "page": "1",
            "size": str(limit),
            "type": "1",  # 全部公告
            "ut": "fa5fd1943c7b386f172d6893dbfd32bb",
        }
        session = await self._get_session()
        async with session.get(
            "https://push2.eastmoney.com/api/qt/stock/notice/get",
            params=params,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        items = []
        raw = data.get("data", {}) or {}
        notice_list = raw.get("list", []) or []
        for item in notice_list:
            title = item.get("title", "") or item.get("notice_title", "")
            if not title:
                continue
            items.append({
                "title": title,
                "summary": item.get("digest", "") or item.get("summary", ""),
                "content_url": item.get("url", "") or item.get("pdf_url", ""),
                "announce_date": item.get("notice_date", "") or item.get("date", ""),
                "category": item.get("column_name", "") or item.get("category", "临时公告"),
            })
        return items[:limit]

    async def fetch_market_news(self, limit: int = 30) -> list[dict]:
        """获取A股市场要闻 (全市场级别)"""
        params = {
            "page": "1",
            "size": str(limit),
            "type": "8194",  # A股要闻
            "ut": "fa5fd1943c7b386f172d6893dbfd32bb",
        }
        session = await self._get_session()
        async with session.get(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            params=params,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return []

    async def health_check(self) -> bool:
        """东方财富健康检查：请求上证指数行情"""
        try:
            await self.fetch_realtime_quote("000001.SH")
            return True
        except Exception as e:
            logger.warning(f"东方财富健康检查失败: {e}")
            return False
