"""多维资讯信号聚合器 — 整合个股新闻、公司公告、行业事件和财联社电报。"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import akshare as ak
from sqlalchemy import text

from backend.shared.database import SessionLocal
from backend.services.analysis_service.engine.industry_event_impact import IndustryEventImpactEngine

logger = logging.getLogger(__name__)

# 近期新闻时间窗口（天）
NEWS_LOOKBACK_DAYS = 3
ANNOUNCEMENT_LOOKBACK_DAYS = 7
TELEGRAPH_LIMIT = 50


def _fetch_stock_news_from_db(symbol: str, lookback_days: int = NEWS_LOOKBACK_DAYS) -> list[dict]:
    """从 stock_news 表读取个股近期新闻。"""
    db = SessionLocal()
    try:
        code = symbol.split(".")[0]
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        rows = db.execute(
            text("""
                SELECT title, summary, source, publish_time, sentiment, impact_level,
                       event_category, related_sector
                FROM stock_news
                WHERE stock_symbol = :sym AND publish_time >= :cutoff
                ORDER BY publish_time DESC
                LIMIT 10
            """),
            {"sym": code, "cutoff": cutoff},
        ).fetchall()
        return [
            {
                "title": r[0] or "",
                "summary": r[1] or "",
                "source": r[2] or "",
                "publish_time": r[3].isoformat() if isinstance(r[3], datetime) else str(r[3] or ""),
                "sentiment": r[4] or "",
                "impact_level": r[5] or "",
                "event_category": r[6] or "",
                "related_sector": r[7] or "",
            }
            for r in rows
        ]
    except Exception as e:
        logger.debug("DB news fetch failed for %s: %s", symbol, e)
        return []
    finally:
        db.close()


def _fetch_announcements_from_db(symbol: str, lookback_days: int = ANNOUNCEMENT_LOOKBACK_DAYS) -> list[dict]:
    """从 company_announcements 表读取个股近期公告。"""
    db = SessionLocal()
    try:
        code = symbol.split(".")[0]
        cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
        rows = db.execute(
            text("""
                SELECT title, summary, category, announce_date, source
                FROM company_announcements
                WHERE stock_symbol = :sym AND announce_date >= :cutoff
                ORDER BY announce_date DESC
                LIMIT 8
            """),
            {"sym": code, "cutoff": cutoff},
        ).fetchall()
        return [
            {
                "title": r[0] or "",
                "summary": r[1] or "",
                "category": r[2] or "",
                "announce_date": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3] or ""),
                "source": r[4] or "",
            }
            for r in rows
        ]
    except Exception as e:
        logger.debug("DB announcement fetch failed for %s: %s", symbol, e)
        return []
    finally:
        db.close()


def _fetch_akshare_news(symbol: str, count: int = 5) -> list[str]:
    """通过 akshare 实时拉取东财个股新闻标题（兜底用）。"""
    try:
        code = symbol.split(".")[0]
        df = ak.stock_news_em(symbol=code)
        if df is None or len(df) == 0:
            return []
        col = "新闻标题" if "新闻标题" in df.columns else df.columns[0]
        return [str(t) for t in df[col].tolist()[:count]]
    except Exception as e:
        logger.debug("Akshare news fetch failed for %s: %s", symbol, e)
        return []


def _fetch_telegraph_signals() -> list[dict]:
    """拉取财联社电报，用于行业/政策信号。"""
    try:
        df = ak.stock_telegraph_cls()
        if df is None or len(df) == 0:
            return []
        records = []
        for _, row in df.head(TELEGRAPH_LIMIT).iterrows():
            title = str(row.get("content") or row.get("标题") or row.get("title") or "")
            if title:
                records.append({"title": title, "source": "财联社电报", "event_category": "市场"})
        return records
    except Exception as e:
        logger.debug("Telegraph fetch failed: %s", e)
        return []


def _fetch_market_news_from_db(lookback_days: int = 2) -> list[dict]:
    """从 stock_news 表读取市场级别/行业级别新闻。"""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        rows = db.execute(
            text("""
                SELECT title, summary, source, publish_time, sentiment,
                       event_category, related_sector, stock_symbol
                FROM stock_news
                WHERE publish_time >= :cutoff
                  AND (event_category IN ('政策', '市场') OR related_sector IS NOT NULL)
                ORDER BY publish_time DESC
                LIMIT 100
            """),
            {"cutoff": cutoff},
        ).fetchall()
        return [
            {
                "title": r[0] or "",
                "summary": r[1] or "",
                "source": r[2] or "",
                "publish_time": r[3].isoformat() if isinstance(r[3], datetime) else str(r[3] or ""),
                "sentiment": r[4] or "",
                "event_category": r[5] or "",
                "related_sector": r[6] or "",
                "stock_symbol": r[7] or "",
            }
            for r in rows
        ]
    except Exception as e:
        logger.debug("DB market news fetch failed: %s", e)
        return []
    finally:
        db.close()


async def aggregate_news_signals(
    symbol: str,
    stock_name: str,
    sector: str | None = None,
) -> dict[str, Any]:
    """
    聚合多维资讯信号，返回结构化信号包。

    返回：
        stock_news_titles: 个股新闻标题列表（用于 AI 分析）
        announcements: 近期公司公告列表
        high_impact_announcements: 重要公告（分红、业绩预告、股东变动等）
        industry_events: 行业/政策事件（IndustryEventImpactEngine 结果）
        telegraph_highlights: 财联社电报相关条目
        has_catalyst: 是否存在明确资讯催化剂
        catalyst_type: 催化剂类型
    """
    loop = asyncio.get_event_loop()

    # 并行拉取多源数据
    db_news_task = loop.run_in_executor(None, _fetch_stock_news_from_db, symbol)
    db_ann_task = loop.run_in_executor(None, _fetch_announcements_from_db, symbol)
    market_news_task = loop.run_in_executor(None, _fetch_market_news_from_db)

    db_news, db_announcements, market_news = await asyncio.gather(
        db_news_task, db_ann_task, market_news_task, return_exceptions=True
    )

    db_news = db_news if isinstance(db_news, list) else []
    db_announcements = db_announcements if isinstance(db_announcements, list) else []
    market_news = market_news if isinstance(market_news, list) else []

    # 个股新闻标题：优先用 DB 缓存，无则实时拉取
    if db_news:
        stock_news_titles = [n["title"] for n in db_news if n.get("title")][:8]
    else:
        stock_news_titles = await loop.run_in_executor(None, _fetch_akshare_news, symbol, 5)

    # 重要公告分类
    important_categories = {"业绩预告", "定期报告", "股东变动", "分红送转", "重大事项"}
    high_impact_announcements = [
        a for a in db_announcements if a.get("category") in important_categories
    ]

    # 行业/政策事件
    all_market_items = market_news
    industry_analysis = IndustryEventImpactEngine.analyze(
        stock_name=stock_name,
        sector=sector,
        market_news=IndustryEventImpactEngine.filter_market_news(all_market_items),
    )

    # 财联社电报（异步，失败不影响主流程）
    telegraph_signals: list[dict] = []
    try:
        raw_telegraph = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_telegraph_signals),
            timeout=8,
        )
        # 只保留与该股行业相关的电报
        sector_kw = sector or ""
        for item in raw_telegraph:
            title = item.get("title", "")
            if sector_kw and sector_kw in title:
                telegraph_signals.append(item)
            elif any(kw in title for kw in IndustryEventImpactEngine.MARKET_WIDE_KEYWORDS):
                telegraph_signals.append(item)
        telegraph_signals = telegraph_signals[:5]
    except Exception:
        pass

    # 判断催化剂
    catalyst_type, has_catalyst = _classify_catalyst(
        stock_news_titles=stock_news_titles,
        announcements=db_announcements,
        industry_themes=industry_analysis.get("themes", []),
        telegraph=telegraph_signals,
    )

    return {
        "stock_news_titles": stock_news_titles,
        "announcements": db_announcements,
        "high_impact_announcements": high_impact_announcements,
        "industry_events": industry_analysis,
        "telegraph_highlights": telegraph_signals,
        "has_catalyst": has_catalyst,
        "catalyst_type": catalyst_type,
        "sector": sector or "",
    }


def _classify_catalyst(
    stock_news_titles: list[str],
    announcements: list[dict],
    industry_themes: list[dict],
    telegraph: list[dict],
) -> tuple[str, bool]:
    """判断催化剂类型。返回 (catalyst_type, has_catalyst)。"""
    # 公告类催化剂（最强信号）
    important_categories = {"业绩预告", "重大事项", "股东变动", "分红送转"}
    if any(a.get("category") in important_categories for a in announcements):
        return "announcement", True

    # 行业/政策催化剂
    high_conf_themes = [t for t in industry_themes if t.get("confidence") in ("high", "medium")]
    if high_conf_themes:
        return "industry_policy", True

    # 个股新闻关键词
    news_text = " ".join(stock_news_titles)
    news_positive = ["中标", "订单", "合作", "增持", "回购", "收购", "扩产", "业绩增长", "超预期"]
    news_negative = ["减持", "亏损", "预亏", "处罚", "立案", "诉讼", "解禁"]
    if any(kw in news_text for kw in news_positive):
        return "news_positive", True
    if any(kw in news_text for kw in news_negative):
        return "news_negative", True

    # 财联社电报政策/市场信号
    if telegraph:
        return "market_signal", True

    return "none", False


def build_enriched_news_context(signals: dict[str, Any]) -> str:
    """将聚合信号转为 AI prompt 用的文本块。"""
    parts: list[str] = []

    titles = signals.get("stock_news_titles", [])
    if titles:
        parts.append("【个股新闻标题】\n" + "\n".join(f"- {t}" for t in titles))

    hi_anns = signals.get("high_impact_announcements", [])
    if hi_anns:
        ann_lines = [f"- [{a.get('category','')}] {a.get('title','')} ({a.get('announce_date','')})" for a in hi_anns[:4]]
        parts.append("【重要公司公告】\n" + "\n".join(ann_lines))

    themes = signals.get("industry_events", {}).get("themes", [])
    if themes:
        theme_lines = [f"- {t['theme']}（{t['direction']}，置信度:{t['confidence']}）: {t['note']}" for t in themes[:3]]
        parts.append("【行业/政策事件】\n" + "\n".join(theme_lines))

    telegraph = signals.get("telegraph_highlights", [])
    if telegraph:
        tel_lines = [f"- {item['title']}" for item in telegraph[:3]]
        parts.append("【财联社电报】\n" + "\n".join(tel_lines))

    catalyst_type = signals.get("catalyst_type", "none")
    if catalyst_type != "none":
        parts.append(f"【催化剂类型】{catalyst_type}")

    return "\n\n".join(parts) if parts else "暂无近期重要资讯。"
