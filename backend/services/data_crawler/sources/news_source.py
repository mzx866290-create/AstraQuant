"""
多源实时新闻采集 — 个股新闻 + 财联社电报 + 新浪财经
复用降级链模式：东方财富 → 新浪 → AKShare 电报
"""
import logging
import re
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

FINANCE_SOURCES = [
    ("东方财富", "https://finance.eastmoney.com"),
    ("新浪财经", "https://finance.sina.com.cn"),
    ("同花顺", "https://www.10jqka.com.cn"),
    ("中金在线", "https://www.cnfol.com"),
]

FINANCE_KEYWORDS = [
    "股票", "A股", "沪指", "深指", "创业板", "科创板", "央行", "货币政策",
    "人民币", "汇率", "GDP", "通胀", "财报", "业绩", "板块", "涨停", "跌停",
    "指数", "基金", "ETF", "分红", "配股", "IPO", "上市", "退市", "并购",
    "重组", "定增", "融资", "融券", "减持", "增持", "回购",
]

SKIP_WORDS = [
    "首页", "最新", "热门", "关于", "联系", "登录", "注册", "收藏", "分享",
    "评论", "关闭", "打开", "更多", "导航", "菜单", "相关", "推荐",
    "财经新闻", "资讯", "实时要闻", "查看详情", "点击查看", "阅读更多",
]


class NewsBaseSource(BaseDataSource):
    """新闻源基类，复用熔断器但不要求实现行情接口"""

    async def fetch_daily_kline(
        self, symbol: str, start_date: str = "", end_date: str = "", adjust: str = ""
    ) -> list[dict]:
        raise NotImplementedError

    async def fetch_realtime_quote(self, symbol: str) -> dict:
        raise NotImplementedError

    async def search_stocks(self, query: str) -> list[dict]:
        raise NotImplementedError

    async def close(self):
        session = getattr(self, "_session", None)
        if session is not None and not session.closed:
            await session.close()


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
        seen_titles = set()
        all_news = []
        for source in self._sources:
            items = await self._try_source(source, "fetch_stock_news", symbol, limit=limit)
            if items:
                for item in items:
                    url = item.get("url", "")
                    title_key = _normalize_title(item.get("title", ""))
                    if not title_key:
                        continue
                    if url and url not in seen_urls and title_key not in seen_titles:
                        seen_urls.add(url)
                        seen_titles.add(title_key)
                        all_news.append(item)
                    elif not url and title_key not in seen_titles:
                        seen_titles.add(title_key)
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

    async def close(self):
        for source in self._sources:
            close_fn = getattr(source, "close", None)
            if close_fn:
                try:
                    await close_fn()
                except Exception:
                    pass


class EastMoneyNewsSource(NewsBaseSource):
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
            data = await resp.json(content_type=None)

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


class AKShareNewsSource(NewsBaseSource):
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


class SinaNewsSource(NewsBaseSource):
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
            raw = await resp.read()
            text = raw.decode(_detect_encoding(resp.headers.get("Content-Type", "")) or "gb2312", errors="replace")

        items = []
        pattern = re.compile(
            r"(\d{4}-\d{2}-\d{2})&nbsp;(\d{2}:\d{2}).{0,80}?"
            r"<a\s+target=['\"]_blank['\"]\s+href=['\"](.*?)['\"]>(.*?)</a>",
            re.DOTALL,
        )
        matches = pattern.findall(text)
        for date_str, time_str, url, title in matches:
            title = _clean_title(title)
            if not title or any(sw in title for sw in SKIP_WORDS):
                continue
            items.append({
                "title": title,
                "summary": "",
                "source": "新浪财经",
                "url": url if url.startswith("http") else f"https://vip.stock.finance.sina.com.cn{url}",
                "publish_time": f"{date_str} {time_str}",
                "keywords": [],
            })
            if len(items) >= limit:
                break
        return items

    async def fetch_telegraph(self, _symbol: str = "", limit: int = 30) -> list[dict]:
        return []

    async def health_check(self) -> bool:
        try:
            news = await self.fetch_stock_news("600519", limit=1)
            return True
        except Exception:
            return False


class JinaFinanceNewsSource(NewsBaseSource):
    """
    财经站点聚合兜底源。

    参考 hot-news-monitor 的做法：优先走 r.jina.ai 提取正文文本，
    被限流或失败时退回直接 HTML 抓取。该源只保留包含股票代码或股票名称的
    标题，避免把全市场新闻误当成个股新闻。
    """

    def __init__(self):
        super().__init__(name="财经聚合", priority=4)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False, force_close=True)
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={"User-Agent": "Mozilla/5.0 (compatible; StockPlatform/2.0)"},
                timeout=aiohttp.ClientTimeout(total=12),
            )
        return self._session

    async def fetch_stock_news(self, symbol: str, limit: int = 20) -> list[dict]:
        code = symbol[:6]
        stock_name = _lookup_stock_name(code)
        terms = [code]
        if stock_name:
            terms.append(stock_name)

        result = []
        seen_titles = set()
        for source_name, url in FINANCE_SOURCES:
            items = await self._fetch_single_source(source_name, url, terms, limit=limit)
            for item in items:
                title_key = _normalize_title(item.get("title", ""))
                if title_key and title_key not in seen_titles:
                    seen_titles.add(title_key)
                    result.append(item)
                    if len(result) >= limit:
                        return result
        return result

    async def _fetch_single_source(
        self,
        source_name: str,
        url: str,
        terms: list[str],
        limit: int,
    ) -> list[dict]:
        session = await self._get_session()
        items = []

        try:
            jina_url = f"https://r.jina.ai/{url}"
            async with session.get(
                jina_url,
                headers={"Accept": "text/plain", "X-Return-Format": "text"},
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    if "RateLimitTriggeredError" not in text:
                        items = _extract_finance_lines(text, source_name, url, terms, limit)
        except Exception as e:
            logger.debug(f"{source_name} Jina 新闻提取失败: {e}")

        if items:
            return items

        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                raw = await resp.read()
                encoding = _detect_encoding(resp.headers.get("Content-Type", ""))
                text = raw.decode(encoding, errors="replace")
                return _extract_html_links(text, source_name, url, terms, limit)
        except Exception as e:
            logger.debug(f"{source_name} 直接新闻提取失败: {e}")
            return []

    async def fetch_telegraph(self, _symbol: str = "", limit: int = 30) -> list[dict]:
        return []

    async def health_check(self) -> bool:
        try:
            items = await self.fetch_stock_news("600519", limit=1)
            return len(items) >= 0
        except Exception:
            return False


def _lookup_stock_name(code: str) -> str:
    try:
        from backend.shared.database import SessionLocal
        from backend.shared.models import Stock

        db = SessionLocal()
        try:
            stock = db.query(Stock).filter(Stock.symbol.like(f"{code}%")).first()
            return stock.name if stock else ""
        finally:
            db.close()
    except Exception:
        return ""


def _normalize_title(title: str) -> str:
    title = re.sub(r"\s+", "", title or "")
    title = re.sub(r"[#*【】\[\]（）()]", "", title)
    return title[:120]


def _clean_title(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = re.sub(r"[#*🎯💼🔥🎓💰🔍🚀]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("-_丨|·")
    return text


def _looks_relevant(title: str, terms: list[str]) -> bool:
    if not title or len(title) < 6 or len(title) > 250:
        return False
    if any(sw in title for sw in SKIP_WORDS):
        return False
    return any(term and term in title for term in terms)


def _extract_finance_lines(
    text: str,
    source_name: str,
    source_url: str,
    terms: list[str],
    limit: int,
) -> list[dict]:
    items = []
    seen = set()
    for line in text.splitlines():
        title = _clean_title(line)
        if not _looks_relevant(title, terms):
            continue
        if not any(kw in title for kw in FINANCE_KEYWORDS + terms):
            continue
        title_key = _normalize_title(title)
        if title_key in seen:
            continue
        seen.add(title_key)
        items.append({
            "title": title[:150],
            "summary": "",
            "source": source_name,
            "url": source_url,
            "publish_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "keywords": [term for term in terms if term and term in title][:4],
        })
        if len(items) >= limit:
            break
    return items


def _extract_html_links(
    html: str,
    source_name: str,
    source_url: str,
    terms: list[str],
    limit: int,
) -> list[dict]:
    items = []
    seen = set()
    pattern = re.compile(r'<a[^>]+href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', re.I | re.S)
    for href, label in pattern.findall(html):
        title = _clean_title(label)
        if not _looks_relevant(title, terms):
            continue
        title_key = _normalize_title(title)
        if title_key in seen:
            continue
        seen.add(title_key)
        full_url = href if href.startswith("http") else source_url
        items.append({
            "title": title[:150],
            "summary": "",
            "source": source_name,
            "url": full_url,
            "publish_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "keywords": [term for term in terms if term and term in title][:4],
        })
        if len(items) >= limit:
            break
    return items


def _detect_encoding(content_type: str) -> str:
    match = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if match:
        encoding = match.group(1).lower()
        if encoding in ("gb2312", "gbk", "gb18030"):
            return "gb18030"
        return encoding
    return "utf-8"


def create_news_chain() -> NewsSourceChain:
    chain = NewsSourceChain()
    chain.register(EastMoneyNewsSource())
    chain.register(SinaNewsSource())
    chain.register(AKShareNewsSource())
    chain.register(JinaFinanceNewsSource())
    return chain
