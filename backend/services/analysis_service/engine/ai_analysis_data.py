from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import os

from backend.shared.database import SessionLocal
from backend.services.analysis_service.engine.data_quality import is_valid_number
from backend.services.analysis_service.engine.industry_event_impact import IndustryEventImpactEngine

logger = logging.getLogger(__name__)


def clean_symbol(symbol: str) -> str:
    return symbol[:6] if len(symbol) >= 6 else symbol


async def get_stock_data(symbol: str, include_news: bool = True, include_profile: bool = True) -> dict:
    from backend.shared.models import CompanyAnnouncement, FinancialReport, Stock, StockNews

    code = clean_symbol(symbol)
    db = SessionLocal()
    try:
        stock = db.query(Stock).filter(Stock.symbol.like(f"{code}%")).first()

        quote_data = await fetch_quote(symbol)
        public_profile = await fetch_public_profile(code, quote_data) if include_profile else {}
        quote_name = (quote_data or {}).get("name") or ""
        name = (stock.name if stock and stock.name and stock.name != code else "") or public_profile.get("name") or quote_name or symbol
        sector = (stock.sector if stock and stock.sector else "") or public_profile.get("sector", "")
        if stock and ((not stock.sector and sector) or (stock.name in ("", code, symbol) and name)):
            if not stock.sector and sector:
                stock.sector = sector
            if stock.name in ("", code, symbol) and name:
                stock.name = name
            db.commit()

        kline_data, kline_source = await fetch_kline(symbol, code)
        indicators = build_indicators(kline_data)

        latest_price = float(quote_data.get("price") or 0) if quote_data else 0.0
        if not is_valid_number(latest_price) and kline_data:
            latest_price = float(kline_data[-1]["close"])
            quote_data = {
                **(quote_data or {}),
                "price": latest_price,
                "source": "synthetic-from-kline",
                "synthetic": True,
                "kline_source": kline_source,
                "timestamp": kline_data[-1].get("date"),
            }
        change_pct = resolve_change_pct(quote_data, kline_data, latest_price)

        fin_items = (
            db.query(FinancialReport)
            .filter(FinancialReport.stock_symbol == code)
            .order_by(FinancialReport.report_date.desc())
            .limit(4)
            .all()
        )
        financial_data = map_financial(fin_items[0], quote_data) if fin_items else {}

        ann_items = (
            db.query(CompanyAnnouncement)
            .filter(CompanyAnnouncement.stock_symbol == code)
            .order_by(CompanyAnnouncement.announce_date.desc())
            .limit(6)
            .all()
        )
        announcements = [
            {
                "title": item.title,
                "summary": (item.summary or "")[:160],
                "announce_date": item.announce_date.isoformat() if item.announce_date else "",
                "category": item.category or "公告",
                "source": item.source or "",
                "url": item.content_url or "",
            }
            for item in ann_items
        ]

        news_data = []
        news_sentiment = {}
        industry_event_context = {
            "available": False,
            "sector": sector,
            "themes": [],
            "warnings": ["news_disabled" if not include_news else "industry_event_news_missing"],
            "note": "未启用新闻分析或未取得市场/行业新闻。",
        }
        if include_news:
            news_items = (
                db.query(StockNews)
                .filter(StockNews.stock_symbol == code)
                .order_by(StockNews.publish_time.desc())
                .limit(20)
                .all()
            )
            news_data = [
                {
                    "title": item.title,
                    "summary": (item.summary or "")[:160],
                    "source": item.source,
                    "url": item.url or "",
                    "publish_time": item.publish_time.isoformat() if item.publish_time else "",
                    "sentiment": item.sentiment,
                    "sentiment_score": item.sentiment_score,
                    "impact_level": item.impact_level,
                    "event_category": item.event_category,
                }
                for item in news_items[:6]
            ]
            if news_items:
                from backend.services.analysis_service.engine.news_sentiment import NewsSentimentEngine

                sent_engine = NewsSentimentEngine()
                news_sentiment = sent_engine.summarize_sentiment(
                    [
                        {
                            "title": item.title,
                            "summary": item.summary or "",
                            "source": item.source,
                            "publish_time": item.publish_time,
                            "sentiment": item.sentiment,
                            "sentiment_score": item.sentiment_score,
                            "impact_level": item.impact_level,
                            "event_category": item.event_category,
                        }
                        for item in news_items
                    ],
                    days=7,
                )
            market_rows = (
                db.query(StockNews)
                .filter(StockNews.stock_symbol != code)
                .order_by(StockNews.publish_time.desc())
                .limit(120)
                .all()
            )
            market_news = IndustryEventImpactEngine.filter_market_news(list(market_rows) + list(news_items), limit=80)
            industry_event_context = IndustryEventImpactEngine.analyze(name, sector, market_news)

        return {
            "name": name,
            "sector": sector,
            "price": latest_price,
            "change_pct": change_pct,
            "quote": quote_data,
            "quote_source": quote_data.get("source") if quote_data else "",
            "kline_source": kline_source,
            "kline_data": kline_data,
            "indicators": indicators,
            "news": news_data,
            "financial": financial_data,
            "announcements": announcements,
            "news_sentiment": news_sentiment,
            "industry_event_context": industry_event_context,
        }
    except Exception as exc:
        logger.warning("failed to build stock data for %s: %s", symbol, exc)
        return {
            "name": symbol,
            "sector": "",
            "price": 0.0,
            "change_pct": 0.0,
            "quote": {},
            "quote_source": "",
            "kline_source": "",
            "kline_data": [],
            "indicators": {},
            "news": [],
            "financial": {},
            "announcements": [],
            "news_sentiment": {},
            "industry_event_context": {
                "available": False,
                "sector": "",
                "themes": [],
                "warnings": ["stock_data_build_failed"],
                "note": str(exc)[:200],
            },
        }
    finally:
        db.close()


async def fetch_quote(symbol: str) -> dict:
    for source_name in ("sina_tencent", "eastmoney", "akshare"):
        try:
            if source_name == "sina_tencent":
                from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource

                result = await SinaTencentSource().fetch_realtime_quote(symbol)
            elif source_name == "eastmoney":
                from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource

                em = EastMoneySource()
                try:
                    result = await em.fetch_realtime_quote(symbol)
                finally:
                    await em.close()
            else:
                from backend.services.data_crawler.sources.akshare_source import AKShareSource

                result = await AKShareSource().fetch_realtime_quote(symbol)
            if result and is_valid_number(result.get("price")):
                result.setdefault("source", source_name)
                return result
        except Exception as exc:
            logger.debug("quote source %s failed: %s", source_name, exc)
    return {}


async def fetch_public_profile(code: str, quote_data: dict | None = None) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fetch_public_profile_sync(code, quote_data or {}))


def fetch_public_profile_sync(code: str, quote_data: dict) -> dict:
    profile = {
        "code": code,
        "name": quote_data.get("name") or "",
        "sector": "",
        "list_date": None,
        "source": "quote" if quote_data.get("name") else "",
    }

    try:
        import akshare as ak

        df = ak.stock_individual_info_em(symbol=code)
        if df is not None and not df.empty:
            raw = {str(row.get("item", "")): row.get("value") for _, row in df.iterrows()}
            profile.update(
                {
                    "name": str(raw.get("股票简称") or raw.get("简称") or profile["name"] or ""),
                    "sector": str(raw.get("行业") or raw.get("所属行业") or ""),
                    "list_date": parse_profile_date(raw.get("上市时间") or raw.get("上市日期")),
                    "source": "akshare",
                }
            )
            if profile.get("sector") or profile.get("name"):
                return profile
    except Exception as exc:
        logger.debug("akshare public profile failed for %s: %s", code, exc)

    try:
        import requests

        em_code = f"{'SH' if code.startswith(('6', '9')) else 'SZ'}{code}"
        resp = requests.get(
            "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax",
            params={"code": em_code},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://emweb.securities.eastmoney.com/",
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        base = (payload.get("jbzl") or [{}])[0]
        issue = (payload.get("fxxg") or [{}])[0]
        profile.update(
            {
                "name": base.get("SECURITY_NAME_ABBR") or profile["name"],
                "sector": (base.get("EM2016") or "").split("-")[0] or profile["sector"],
                "list_date": parse_profile_date(issue.get("LISTING_DATE")) or profile.get("list_date"),
                "source": "eastmoney",
            }
        )
    except Exception as exc:
        logger.debug("eastmoney public profile failed for %s: %s", code, exc)
    return profile


def parse_profile_date(value) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return text[:10] if text else None


async def fetch_kline(symbol: str, code: str) -> tuple[list[dict], str]:
    try:
        from clickhouse_driver import Client

        ch_host = os.getenv("CLICKHOUSE_HOST", "localhost")
        client = Client(host=ch_host, port=9000, user="default")
        rows = client.execute(
            "SELECT trade_date, open, high, low, close, volume "
            "FROM stock_daily WHERE symbol = %(s)s ORDER BY trade_date DESC LIMIT 60",
            {"s": f"{code}.{'SH' if code.startswith(('6', '9')) else 'SZ'}"},
        )
        data = [
            {
                "date": str(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            for row in rows
        ]
        if data:
            return list(reversed(data)), "clickhouse-primary"
    except Exception:
        pass

    for source_name in ("sina", "eastmoney"):
        try:
            if source_name == "sina":
                from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource

                data = await SinaTencentSource().fetch_daily_kline(symbol)
            else:
                from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource

                em = EastMoneySource()
                try:
                    data = await em.fetch_daily_kline(symbol)
                finally:
                    await em.close()
            if data:
                return data[-60:], f"{source_name}-secondary"
        except Exception as exc:
            logger.debug("kline source %s failed: %s", source_name, exc)
    return [], "source-unavailable"


def build_indicators(kline_data: list[dict]) -> dict:
    if not kline_data:
        return {}
    closes = [float(item["close"]) for item in kline_data if item.get("close") is not None]
    return {
        "MA5": round(sum(closes[-5:]) / 5, 2) if len(closes) >= 5 else "N/A",
        "MA20": round(sum(closes[-20:]) / 20, 2) if len(closes) >= 20 else "N/A",
        "MA60": round(sum(closes[-60:]) / 60, 2) if len(closes) >= 60 else "N/A",
        "latest_price": closes[-1] if closes else "N/A",
    }


def resolve_change_pct(quote_data: dict, kline_data: list[dict], latest_price: float) -> float:
    if quote_data and quote_data.get("change_pct") is not None:
        try:
            return round(float(quote_data.get("change_pct") or 0), 2)
        except (TypeError, ValueError):
            pass
    if len(kline_data) > 1:
        prev_price = float(kline_data[-2]["close"])
        return round((latest_price - prev_price) / prev_price * 100, 2) if prev_price else 0.0
    return 0.0


def map_financial(latest, quote_data: dict) -> dict:
    data = {
        "report_date": latest.report_date.isoformat() if latest.report_date else "",
        "report_type": latest.report_type or "",
        "revenue": latest.revenue,
        "revenue_yoy": latest.revenue_yoy,
        "net_profit": latest.net_profit,
        "net_profit_yoy": latest.net_profit_yoy,
        "gross_margin": latest.gross_margin,
        "net_margin": latest.net_margin,
        "eps": latest.eps,
        "bvps": latest.bvps,
        "roe": latest.roe,
        "roa": latest.roa,
        "total_assets": latest.total_assets,
        "total_liabilities": latest.total_liabilities,
        "total_equity": latest.total_equity,
        "operating_cf": latest.operating_cf,
        "pe_ttm": latest.pe_ttm,
        "pb": latest.pb,
        "source": latest.source or "akshare",
    }
    data_pe_missing = not is_valid_number(data.get("pe_ttm"))
    data_pb_missing = not is_valid_number(data.get("pb"))
    quote_pe = quote_data.get("pe_ttm") if quote_data else None
    quote_pb = quote_data.get("pb") if quote_data else None
    if quote_data:
        if data_pe_missing and is_valid_number(quote_pe):
            data["pe_ttm"] = quote_pe
        if data_pb_missing and is_valid_number(quote_pb):
            data["pb"] = quote_pb
        data["total_mv"] = quote_data.get("total_mv")
        data["circ_mv"] = quote_data.get("circ_mv")
        if (data_pe_missing and is_valid_number(quote_pe)) or (data_pb_missing and is_valid_number(quote_pb)):
            data["valuation_source"] = quote_data.get("source", "quote")
    if is_valid_number(data.get("pe_ttm")) or is_valid_number(data.get("pb")):
        data.setdefault("valuation_source", data["source"])
    return data
