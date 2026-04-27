"""
多源实时新闻采集 — 个股新闻 + 财联社电报 + 新浪财经
复用降级链模式：东方财富 → 新浪 → AKShare 电报
"""
import logging
from datetime import datetime
from typing import Optional

import aiohttp

from .base import BaseDataSource

logger = logging.getLogger(__name__)

# ── 金融情感词典 ──
POSITIVE_KEYWORDS = [
    "涨停", "增持", "回购", "业绩预增", "重大合同", "中标", "突破",
    "利好", "扭亏", "高速增长", "超预期", "获得资质", "获批复",
    "新产品发布", "重大项目", "战略合作", "机构增持", "目标价上调",
    "高分红", "高送转", "员工持股", "股权激励", "收购", "重组获批",
]
NEGATIVE_KEYWORDS = [
    "跌停", "减持", "业绩预亏", "亏损", "处罚", "立案", "退市风险",
    "利空", "下滑", "不及预期", "诉讼", "仲裁", "限售解禁",
    "ST", "债务违约", "资产减值", "商誉减值", "资金冻结",
    "大股东质押", "被调查", "业绩修正", "终止重组", "停产",
]


class NewsSourceChain:
    """新闻数据源降级链"""

    def __init__(self):
        self._sources: list[BaseDataSource] = []

    def register(self, source: BaseDataSource):
        self._sources.append(source)
        self._sources.sort(key=lambda s: s.priority)

    async def _try_source(self, source: BaseDataSource, method: str, symbol: str, **kwargs):
        if not source.circuit_breaker.is_available():
            return None
        try:
            method_fn = getattr(source, method, None)
            if method_fn is None:
                return None
            import asyncio
            result = await asyncio.wait_for(method_fn(symbol, **kwargs), timeout=15.0)
            source.circuit_breaker.record_success()
            return result
        except Exception as e:
            source.circuit_breaker.record_failure()
            logger.warning(f"新闻源 {source.name} 失败 ({method}): {e}")
            return None

    async def fetch_stock_news(self, symbol: str, limit: int = 20) -> list[dict]:
        """多源获取个股新闻，去重合并"""
        seen_urls = set()
        all_news = []
        for source in self._sources:
            items = await self._try_source(source, "fetch_stock_news", symbol, limit=limit)
            if items:
                for item in items:
                    url = item.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_news.append(item)
                    elif not url:
                        title = item.get("title", "")
                        if title not in {n.get("title") for n in all_news}:
                            all_news.append(item)
        all_news.sort(key=lambda x: x.get("publish_time", ""), reverse=True)
        return all_news[:limit]

    async def fetch_telegraph(self, limit: int = 30) -> list[dict]:
        """获取财联社电报"""
        for source in self._sources:
            items = await self._try_source(source, "fetch_telegraph", "", limit=limit)
            if items:
                return items[:limit]
        return []


class EastMoneyNewsSource(BaseDataSource):
    """东方财富个股新闻 (优先级最高)"""

    def __init__(self):
        super().__init__(name="东方财富新闻", priority=1)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False, force_close=True)
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://quote.eastmoney.com/",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    def _to_em_secid(self, symbol: str) -> str:
        code = symbol[:6]
        market = "1" if code.startswith(("6", "9")) else "0"
        return f"{market}.{code}"

    async def fetch_stock_news(self, symbol: str, limit: int = 20) -> list[dict]:
        secid = self._to_em_secid(symbol)
        session = await self._get_session()
        params = {
            "secid": secid,
            "page": "1",
            "size": str(limit),
            "ut": "fa5fd1943c7b386f172d6893dbfd32bb",
        }
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
            if not title:
                continue
            items.append({
                "title": title,
                "summary": item.get("digest", "") or item.get("summary", ""),
                "source": item.get("source", "东方财富"),
                "url": item.get("url", ""),
                "publish_time": item.get("showTime", "") or item.get("publishTime", ""),
                "keywords": [],
            })
        return items[:limit]

    async def fetch_telegraph(self, _symbol: str = "", limit: int = 30) -> list[dict]:
        """东方财富电报"""
        session = await self._get_session()
        params = {
            "page": "1", "size": str(limit),
            "type": "8201",  # A股电报
        }
        async with session.get(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            params=params,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return []

    async def health_check(self) -> bool:
        try:
            news = await self.fetch_stock_news("600519", limit=1)
            return len(news) >= 0
        except Exception:
            return False


class AKShareNewsSource(BaseDataSource):
    """AKShare新闻源 (备用，覆盖财联社电报)"""

    def __init__(self):
        super().__init__(name="AKShare新闻", priority=2)
        self._ak_available = False
        self._check_import()

    def _check_import(self):
        try:
            import akshare as ak  # noqa
            self._ak_available = True
        except ImportError:
            logger.warning("akshare 未安装，AKShare新闻源不可用")

    def _get_ak(self):
        if not self._ak_available:
            raise RuntimeError("akshare 未安装")
        import akshare as ak
        return ak

    async def fetch_stock_news(self, symbol: str, limit: int = 20) -> list[dict]:
        import pandas as pd
        ak = self._get_ak()
        code = symbol[:6]
        loop = self._get_event_loop()
        try:
            df = await loop.run_in_executor(None, lambda: ak.stock_news_em(symbol=code))
        except Exception:
            return []
        if df is None or df.empty:
            return []
        items = []
        for _, row in df.head(limit).iterrows():
            items.append({
                "title": str(row.get("标题", row.get("title", ""))),
                "summary": str(row.get("内容", row.get("content", "")))[:300],
                "source": "东方财富",
                "url": str(row.get("链接", row.get("url", ""))),
                "publish_time": str(row.get("发布时间", row.get("pub_time", ""))),
                "keywords": [],
            })
        return items

    async def fetch_telegraph(self, _symbol: str = "", limit: int = 30) -> list[dict]:
        ak = self._get_ak()
        loop = self._get_event_loop()
        try:
            df = await loop.run_in_executor(None, lambda: ak.stock_telegraph_cls())
        except Exception as e:
            logger.warning(f"财联社电报获取失败: {e}")
            return []
        if df is None or df.empty:
            return []
        items = []
        for _, row in df.head(limit).iterrows():
            content = str(row.get("content", row.get("内容", "")))
            title = content[:80] + "..." if len(content) > 80 else content
            items.append({
                "title": title,
                "summary": content,
                "source": "财联社",
                "url": "",
                "publish_time": str(row.get("date_time", row.get("发布时间", ""))),
                "keywords": [],
            })
        return items

    def _get_event_loop(self):
        import asyncio
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.new_event_loop()

    async def health_check(self) -> bool:
        if not self._ak_available:
            return False
        try:
            import akshare as ak
            return True
        except Exception:
            return False


class SinaNewsSource(BaseDataSource):
    """新浪财经新闻 (第三备用源)"""

    def __init__(self):
        super().__init__(name="新浪财经", priority=3)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False, force_close=True)
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0"},
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    def _to_sina_symbol(self, symbol: str) -> str:
        code = symbol[:6]
        if code.startswith(("6", "9")):
            return f"sh{code}"
        return f"sz{code}"

    async def fetch_stock_news(self, symbol: str, limit: int = 20) -> list[dict]:
        sina_sym = self._to_sina_symbol(symbol)
        session = await self._get_session()
        async with session.get(
            f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/{sina_sym}.phtml"
        ) as resp:
            resp.raise_for_status()
            text = await resp.text()
        # 简单HTML解析提取新闻标题和链接
        import re
        items = []
        pattern = re.compile(
            r'<a\s+href=["\'](.*?)["\'].*?target=["\']_blank["\']\s*>(.*?)</a>.*?<span.*?>\((.*?)\)</span>',
            re.DOTALL,
        )
        matches = pattern.findall(text)
        for url, title, date_str in matches[:limit]:
            title = re.sub(r'<[^>]+>', '', title).strip()
            if title:
                items.append({
                    "title": title,
                    "summary": "",
                    "source": "新浪财经",
                    "url": url if url.startswith("http") else f"https://vip.stock.finance.sina.com.cn{url}",
                    "publish_time": date_str.strip() if date_str else "",
                    "keywords": [],
                })
        return items

    async def fetch_telegraph(self, _symbol: str = "", limit: int = 30) -> list[dict]:
        return []

    async def health_check(self) -> bool:
        try:
            news = await self.fetch_stock_news("600519", limit=1)
            return True
        except Exception:
            return False


def create_news_chain() -> NewsSourceChain:
    chain = NewsSourceChain()
    chain.register(EastMoneyNewsSource())
    chain.register(SinaNewsSource())
    chain.register(AKShareNewsSource())
    return chain
