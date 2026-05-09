"""
AKShare数据源 - 免费开源A股数据全覆盖
pip install akshare
提供: K线 / 实时行情 / 财务数据 / 板块数据 / 龙虎榜
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from .base import BaseDataSource

logger = logging.getLogger(__name__)


class AKShareSource(BaseDataSource):
    """
    AKShare 数据源 (备用免费源)
    - 完全免费开源
    - 覆盖广：A股/港股/期货/基金/宏观
    - 数据返回pandas DataFrame格式
    """

    def __init__(self):
        super().__init__(name="AKShare", priority=2)
        self._akshare_available = False
        self._check_import()

    def _check_import(self):
        try:
            import akshare as ak  # noqa
            self._akshare_available = True
        except ImportError:
            logger.warning("akshare 未安装，AKShare数据源不可用 (pip install akshare)")

    def _get_ak(self):
        """惰性导入akshare"""
        if not self._akshare_available:
            raise RuntimeError("akshare 未安装，请执行 pip install akshare")
        import akshare as ak
        return ak

    def _to_ak_symbol(self, symbol: str) -> str:
        """转AKShare代码格式: 600519 → 600519"""
        return symbol[:6]

    def _to_em_symbol(self, symbol: str) -> str:
        """转AKShare东方财富财报代码格式: 600519 → SH600519"""
        code = symbol[:6]
        if code.startswith(("6", "9", "5")):
            return f"SH{code}"
        if code.startswith(("0", "1", "2", "3")):
            return f"SZ{code}"
        if code.startswith(("4", "8", "920")):
            return f"BJ{code}"
        return code

    def _cninfo_stock_param(self, code: str) -> str:
        """Build CNINFO stock query param: code,orgId."""
        if code.startswith(("6", "9")):
            return f"{code},gssh0{code}"

        org_id = self._lookup_cninfo_org_id(code)
        if org_id:
            return f"{code},{org_id}"

        if code.startswith(("0", "2", "3")):
            return f"{code},gssz0{code}"
        if code.startswith(("4", "8", "920")):
            return f"{code},gfbj0{code}"
        return f"{code},"

    def _lookup_cninfo_org_id(self, code: str) -> str:
        """Resolve CNINFO orgId for SZ/BJ stocks from public static lists."""
        import requests

        list_name = "bj_stock.json" if code.startswith(("4", "8", "920")) else "szse_stock.json"
        url = f"http://www.cninfo.com.cn/new/data/{list_name}"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        for item in (resp.json().get("stockList") or []):
            if item.get("code") == code:
                return item.get("orgId", "")
        return ""

    def _parse_cninfo_time(self, raw) -> str:
        if raw in (None, ""):
            return ""
        try:
            value = int(raw)
            if value > 10_000_000_000:
                value = value / 1000
            return datetime.fromtimestamp(value).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            return str(raw)[:10]

    def _classify_notice(self, title: str) -> str:
        if any(word in title for word in ("季报", "年报", "半年报", "年度报告", "季度报告", "第一季度", "第三季度")):
            return "定期报告"
        if any(word in title for word in ("业绩预告", "业绩快报", "预增", "预减", "预亏", "预盈")):
            return "业绩预告"
        if any(word in title for word in ("分红", "派息", "权益分派", "利润分配")):
            return "分红送转"
        if any(word in title for word in ("减持", "增持", "回购", "解除限售", "质押")):
            return "股东变动"
        if any(word in title for word in ("重组", "收购", "并购", "重大资产", "定向增发")):
            return "重大事项"
        return "临时公告"

    async def fetch_daily_kline(
        self, symbol: str, start_date: str = "", end_date: str = "", adjust: str = ""
    ) -> list[dict]:
        """
        获取A股日K线 (前复权)
        """
        import pandas as pd
        ak = self._get_ak()
        code = self._to_ak_symbol(symbol)

        loop = self._get_event_loop()
        try:
            df = await loop.run_in_executor(
                None,
                lambda: ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start_date.replace("-", "") if start_date else "20000101",
                    end_date=end_date.replace("-", "") if end_date else "20500101",
                    adjust="qfq",  # 前复权
                ),
            )
        except Exception:
            # 如果前复权失败，尝试不复权
            df = await loop.run_in_executor(
                None,
                lambda: ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start_date.replace("-", "") if start_date else "20000101",
                    end_date=end_date.replace("-", "") if end_date else "20500101",
                    adjust="",
                ),
            )

        if df is None or df.empty:
            return []

        # 标准化输出
        if "日期" in df.columns:
            df = df.rename(columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "turnover",
                "振幅": "amplitude",
                "涨跌幅": "change_pct",
                "涨跌额": "change",
                "换手率": "turnover_rate",
            })

        records = []
        for _, row in df.iterrows():
            item = {
                "date": str(row.get("date", "")),
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": int(float(row.get("volume", 0))),
                "turnover": float(row.get("turnover", 0)),
                "change_pct": float(row.get("change_pct", 0)),
            }
            # A股特有字段
            for extra in ("turnover_rate", "amplitude", "change"):
                if extra in row:
                    item[extra] = float(row[extra])
            records.append(item)

        return records

    async def fetch_realtime_quote(self, symbol: str) -> dict:
        """获取A股实时行情"""
        import pandas as pd
        ak = self._get_ak()
        code = self._to_ak_symbol(symbol)

        loop = self._get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: ak.stock_zh_a_spot_em(),
        )

        if df is None or df.empty:
            raise RuntimeError(f"AKShare 实时行情获取失败: {symbol}")

        # 筛选目标股票
        mask = df["代码"] == code
        match = df[mask]
        if match.empty:
            raise RuntimeError(f"股票 {symbol} 未找到")

        row = match.iloc[0]
        return {
            "symbol": symbol,
            "name": row.get("名称", ""),
            "price": float(row.get("最新价", 0)),
            "change": float(row.get("涨跌额", 0)),
            "change_pct": float(row.get("涨跌幅", 0)),
            "high": float(row.get("最高", 0)),
            "low": float(row.get("最低", 0)),
            "open": float(row.get("今开", 0)),
            "volume": int(float(row.get("成交量", 0))),
            "turnover": float(row.get("成交额", 0)),
            "turnover_rate": float(row.get("换手率", 0)),
            "pe_ttm": float(row.get("市盈率-动态", 0)),
            "total_mv": float(row.get("总市值", 0)),
            "circ_mv": float(row.get("流通市值", 0)),
            "timestamp": datetime.now().isoformat(),
        }

    async def search_stocks(self, query: str) -> list[dict]:
        """搜索A股股票"""
        ak = self._get_ak()

        loop = self._get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: ak.stock_zh_a_spot_em(),
        )

        if df is None or df.empty:
            return []

        # 按代码或名称模糊搜索
        mask = df["代码"].str.contains(query, na=False) | df["名称"].str.contains(query, na=False)
        matches = df[mask].head(20)

        result = []
        for _, row in matches.iterrows():
            code = row["代码"]
            result.append({
                "symbol": code,
                "name": row["名称"],
                "market": "SH" if code.startswith(("6", "9")) else "SZ",
            })
        return result

    async def fetch_stock_master(self, **_kwargs) -> list[dict]:
        """获取A股股票主数据，作为东方财富分页接口失败时的备用源。"""
        ak = self._get_ak()
        loop = self._get_event_loop()
        df = await loop.run_in_executor(None, lambda: ak.stock_info_a_code_name())
        if df is None or df.empty:
            return []

        code_col = "code" if "code" in df.columns else "代码"
        name_col = "name" if "name" in df.columns else "名称"
        rows = []
        for _, row in df.iterrows():
            code = str(row.get(code_col) or "").zfill(6)[:6]
            rows.append({
                "symbol": code,
                "name": row.get(name_col) or "",
                "market": self._get_market(code),
                "sector": "",
            })
        return rows

    async def fetch_sector_list(self) -> list[dict]:
        """获取行业板块列表 (AKShare特色)"""
        ak = self._get_ak()
        loop = self._get_event_loop()
        df = await loop.run_in_executor(None, lambda: ak.stock_board_industry_name_em())
        if df is None or df.empty:
            return []
        return [
            {
                "name": row["板块名称"],
                "code": row["板块代码"],
                "count": int(row.get("股票数量", 0)),
            }
            for _, row in df.iterrows()
        ]

    async def fetch_dragon_tiger(self, date: str = "") -> list[dict]:
        """获取龙虎榜数据 (AKShare特色)"""
        ak = self._get_ak()
        loop = self._get_event_loop()
        trade_date = date.replace("-", "") if date else datetime.now().strftime("%Y%m%d")
        try:
            df = await loop.run_in_executor(
                None,
                lambda: ak.stock_lhb_detail_em(start_date=trade_date, end_date=trade_date),
            )
            if df is None or df.empty:
                return []
            return df.to_dict("records")
        except Exception as e:
            logger.warning(f"龙虎榜获取失败: {e}")
            return []

    async def fetch_stock_dragon_tiger(self, symbol: str, days: int = 30) -> list[dict]:
        """获取个股最近一段时间的龙虎榜历史"""
        ak = self._get_ak()
        loop = self._get_event_loop()
        code = self._to_ak_symbol(symbol)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=max(1, min(days, 365)))
        try:
            df = await loop.run_in_executor(
                None,
                lambda: ak.stock_lhb_detail_em(
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                ),
            )
            if df is None or df.empty:
                return []
            code_column = "代码" if "代码" in df.columns else "股票代码" if "股票代码" in df.columns else None
            if code_column:
                df = df[df[code_column].astype(str).str.zfill(6) == code]
            return df.to_dict("records")
        except Exception as e:
            logger.warning(f"{symbol} 龙虎榜历史获取失败: {e}")
            return []

    async def fetch_stock_notices(self, symbol: str, limit: int = 20) -> list[dict]:
        """Fetch stock announcements from CNINFO public disclosure API."""
        import requests

        loop = self._get_event_loop()
        code = symbol[:6]

        def _request_cninfo():
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
            }
            form = {
                "pageNum": "1",
                "pageSize": str(limit),
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": self._cninfo_stock_param(code),
                "searchkey": "",
                "secid": "",
                "category": "",
                "trade": "",
                "seDate": "",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            resp = requests.post(
                "http://www.cninfo.com.cn/new/hisAnnouncement/query",
                data=form,
                headers=headers,
                timeout=12,
            )
            resp.raise_for_status()
            return resp.json()

        try:
            data = await loop.run_in_executor(None, _request_cninfo)
        except Exception as e:
            logger.warning(f"[{symbol}] 公告获取失败: {e}")
            return []

        items = []
        for row in data.get("announcements") or []:
            if row.get("secCode") and row.get("secCode") != code:
                continue
            title = str(row.get("announcementTitle") or "").replace("<em>", "").replace("</em>", "")
            adjunct_url = str(row.get("adjunctUrl") or "")
            content_url = f"http://static.cninfo.com.cn/{adjunct_url}" if adjunct_url else ""
            items.append({
                "title": title,
                "summary": str(row.get("secName") or ""),
                "content_url": content_url,
                "announce_date": self._parse_cninfo_time(row.get("announcementTime")),
                "category": self._classify_notice(title),
            })
            if len(items) >= limit:
                break
        return items

    async def fetch_financial_abstract(self, symbol: str) -> dict:
        """获取财务摘要指标 - ak.stock_financial_abstract_ths()"""
        ak = self._get_ak()
        loop = self._get_event_loop()
        code = symbol[:6]
        try:
            df = await loop.run_in_executor(
                None, lambda: ak.stock_financial_abstract_ths(symbol=code)
            )
        except Exception as e:
            logger.warning(f"[{symbol}] 财务摘要获取失败: {e}")
            return {"indicators": [], "reports": []}
        if df is None or df.empty:
            return {"indicators": [], "reports": []}
        return {"raw": df.to_dict("records")}

    async def fetch_balance_sheet(self, symbol: str, date: str = "") -> list[dict]:
        """获取资产负债表 - ak.stock_balance_sheet_by_report_em()"""
        ak = self._get_ak()
        loop = self._get_event_loop()
        code = symbol[:6]
        try:
            df = await loop.run_in_executor(
                None, lambda: ak.stock_balance_sheet_by_report_em(symbol=self._to_em_symbol(code))
            )
        except Exception as e:
            logger.warning(f"[{symbol}] 资产负债表获取失败: {e}")
            return []
        if df is None or df.empty:
            return []
        return df.to_dict("records")

    async def fetch_profit_sheet(self, symbol: str, date: str = "") -> list[dict]:
        """获取利润表 - ak.stock_profit_sheet_by_report_em()"""
        ak = self._get_ak()
        loop = self._get_event_loop()
        code = symbol[:6]
        try:
            df = await loop.run_in_executor(
                None, lambda: ak.stock_profit_sheet_by_report_em(symbol=self._to_em_symbol(code))
            )
        except Exception as e:
            logger.warning(f"[{symbol}] 利润表获取失败: {e}")
            return []
        if df is None or df.empty:
            return []
        return df.to_dict("records")

    async def fetch_cash_flow_sheet(self, symbol: str, date: str = "") -> list[dict]:
        """获取现金流量表 - ak.stock_cash_flow_sheet_by_report_em()"""
        ak = self._get_ak()
        loop = self._get_event_loop()
        code = symbol[:6]
        try:
            df = await loop.run_in_executor(
                None, lambda: ak.stock_cash_flow_sheet_by_report_em(symbol=self._to_em_symbol(code))
            )
        except Exception as e:
            logger.warning(f"[{symbol}] 现金流量表获取失败: {e}")
            return []
        if df is None or df.empty:
            return []
        return df.to_dict("records")

    def _get_event_loop(self):
        import asyncio
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.new_event_loop()

    async def health_check(self) -> bool:
        """AKShare健康检查"""
        if not self._akshare_available:
            return False
        try:
            import akshare as ak
            loop = self._get_event_loop()
            await loop.run_in_executor(None, lambda: ak.stock_zh_a_spot_em())
            return True
        except Exception as e:
            logger.warning(f"AKShare健康检查失败: {e}")
            return False
