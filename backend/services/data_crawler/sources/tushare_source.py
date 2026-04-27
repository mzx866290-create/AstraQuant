"""
Tushare数据源 - 专业A股数据源 (需Token)
pip install tushare
提供: K线 / 行情 / 财务 / 资金流向 / 龙虎榜
"""
import logging
from datetime import datetime
from typing import Optional

from .base import BaseDataSource

logger = logging.getLogger(__name__)


class TushareSource(BaseDataSource):
    """
    Tushare Pro 数据源 (付费备用源)
    - 需要 Token (积分制)
    - 数据质量高，字段规范
    - 作为付费备用源使用
    """

    def __init__(self, token: str = ""):
        super().__init__(name="Tushare", priority=3)
        self._token = token
        self._ts_available = False
        self._api = None
        self._check_import()

    def _check_import(self):
        try:
            import tushare as ts  # noqa
            self._ts_available = True
        except ImportError:
            logger.warning("tushare 未安装 (pip install tushare)")

    def _get_api(self):
        if not self._ts_available:
            raise RuntimeError("tushare 未安装")
        if self._api is None:
            import tushare as ts
            if self._token:
                ts.set_token(self._token)
            self._api = ts.pro_api()
        return self._api

    async def fetch_daily_kline(
        self, symbol: str, start_date: str = "", end_date: str = "", adjust: str = ""
    ) -> list[dict]:
        """获取日K线"""
        api = self._get_api()
        loop = self._get_event_loop()
        ts_code = f"{symbol[:6]}.{self._get_market(symbol)}"

        params = {
            "ts_code": ts_code,
            "start_date": start_date.replace("-", "") if start_date else "20000101",
            "end_date": end_date.replace("-", "") if end_date else "20500101",
        }
        if adjust:
            params["adj"] = {"qfq": "qfq", "hfq": "hfq"}.get(adjust, "")

        df = await loop.run_in_executor(
            None, lambda: api.daily(**params)
        )

        if df is None or df.empty:
            return []

        records = []
        for _, row in df.iterrows():
            records.append({
                "date": str(row.get("trade_date", "")),
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": int(row.get("vol", 0)),
                "turnover": float(row.get("amount", 0)),
                "change_pct": float(row.get("pct_chg", 0)),
            })
        return records

    async def fetch_realtime_quote(self, symbol: str) -> dict:
        """
        Tushare没有真正的实时行情接口
        使用每日数据模拟 (盘后可用)
        """
        api = self._get_api()
        loop = self._get_event_loop()
        ts_code = f"{symbol[:6]}.{self._get_market(symbol)}"

        df = await loop.run_in_executor(
            None, lambda: api.daily(trade_date=datetime.now().strftime("%Y%m%d"), ts_code=ts_code)
        )

        if df is None or df.empty:
            # 尝试最近交易日
            df = await loop.run_in_executor(
                None, lambda: api.daily(ts_code=ts_code)
            )

        if df is None or df.empty:
            raise RuntimeError(f"Tushare 获取 {symbol} 失败")

        row = df.iloc[0]
        return {
            "symbol": symbol,
            "name": "",
            "price": float(row.get("close", 0)),
            "change": float(row.get("change", 0)),
            "change_pct": float(row.get("pct_chg", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "open": float(row.get("open", 0)),
            "volume": int(row.get("vol", 0)),
            "turnover": float(row.get("amount", 0)),
            "timestamp": datetime.now().isoformat(),
        }

    async def search_stocks(self, query: str) -> list[dict]:
        """搜索股票"""
        api = self._get_api()
        loop = self._get_event_loop()

        # 获取全部A股列表
        df = await loop.run_in_executor(
            None,
            lambda: api.stock_basic(list_status="L"),
        )

        if df is None or df.empty:
            return []

        mask = df["symbol"].str.contains(query, na=False) | df["name"].str.contains(query, na=False)
        matches = df[mask].head(20)

        return [
            {
                "symbol": row["ts_code"],
                "name": row["name"],
                "market": row["ts_code"].split(".")[-1],
            }
            for _, row in matches.iterrows()
        ]

    def _get_event_loop(self):
        import asyncio
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.new_event_loop()

    async def health_check(self) -> bool:
        if not self._ts_available or not self._token:
            return False
        try:
            api = self._get_api()
            loop = self._get_event_loop()
            df = await loop.run_in_executor(
                None, lambda: api.daily(trade_date=datetime.now().strftime("%Y%m%d"))
            )
            return df is not None
        except Exception as e:
            logger.warning(f"Tushare健康检查失败: {e}")
            return False
