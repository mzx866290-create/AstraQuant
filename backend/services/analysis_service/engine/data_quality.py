from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_valid_number(value: Any) -> bool:
    try:
        return value is not None and float(value) != 0.0
    except (TypeError, ValueError):
        return False


QUOTE_KLINE_FALLBACK_SOURCES = {"synthetic-from-kline", "local-fallback", "eastmoney-kline", "akshare-kline"}
KLINE_FALLBACK_SOURCES = {"local-fallback"}


def quote_abnormal_reason(stock_data: dict) -> str:
    quote = stock_data.get("quote") or {}
    price = stock_data.get("price")
    if str(quote.get("name") or stock_data.get("name") or "").endswith("退"):
        return "delisting_or_delisted_stock_name"
    if is_valid_number(price) and not any(is_valid_number(quote.get(k)) for k in ("open", "high", "low", "volume", "turnover")):
        return "quote_trade_fields_missing_or_zero"
    return ""


def is_usable_quote(stock_data: dict) -> bool:
    return is_valid_number(stock_data.get("price")) and not quote_abnormal_reason(stock_data)


def build_data_grade(stock_data: dict) -> dict:
    financial = stock_data.get("financial") or {}
    quote = stock_data.get("quote") or {}
    quote_abnormal = quote_abnormal_reason(stock_data)
    has_quote = is_usable_quote(stock_data)
    has_kline = bool(stock_data.get("kline_data"))
    has_financial = bool(financial)
    has_announcements = bool(stock_data.get("announcements"))
    has_news = bool(stock_data.get("news"))
    industry_event = stock_data.get("industry_event_context") or {}
    has_industry_events = bool(industry_event.get("available") and industry_event.get("themes"))
    has_valuation = (
        is_valid_number(financial.get("pe_ttm") or quote.get("pe_ttm"))
        and is_valid_number(financial.get("pb") or quote.get("pb"))
    )

    if quote_abnormal:
        grade = "D"
        label = "行情异常或退市风险"
        analysis_scope = "行情字段异常或股票存在退市风险，只能提示数据与交易风险，不应判断正常短线趋势或估值。"
    elif not has_quote:
        grade = "D"
        label = "行情不可用"
        analysis_scope = "只能说明数据缺口，不能判断价格、技术面或估值。"
    elif has_quote and has_kline and has_financial and has_announcements and has_news:
        grade = "A"
        label = "数据较完整"
        analysis_scope = "可以做行情、技术面、基本面、公告和消息面的综合分析。"
    elif has_quote and has_kline and (has_financial or has_announcements or has_news or has_industry_events or has_valuation):
        grade = "B"
        label = "数据部分完整"
        analysis_scope = "可以分析行情和技术面；基本面、公告、个股新闻或行业事件只能基于已有数据谨慎判断。"
    elif has_quote and has_kline:
        grade = "C"
        label = "仅行情技术可用"
        analysis_scope = "只能分析行情和K线，基本面、公告、消息面暂不可判断。"
    else:
        grade = "D"
        label = "关键数据不足"
        analysis_scope = "关键行情或K线不足，只能给出数据缺口提示。"

    return {
        "grade": grade,
        "label": label,
        "analysis_scope": analysis_scope,
        "has_quote": has_quote,
        "quote_abnormal": quote_abnormal,
        "has_kline": has_kline,
        "has_financial": has_financial,
        "has_announcements": has_announcements,
        "has_news": has_news,
        "has_industry_events": has_industry_events,
        "has_valuation": has_valuation,
    }


@dataclass
class DataQualityItem:
    source: str = ""
    updated_at: str | None = None
    freshness: str = "unknown"
    confidence: str = "low"
    is_fallback: bool = False
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "updated_at": self.updated_at,
            "freshness": self.freshness,
            "confidence": self.confidence,
            "is_fallback": self.is_fallback,
            "warnings": self.warnings,
        }


class DataQualityBuilder:
    """Build consistent quality metadata for AI context and readiness."""

    @staticmethod
    def from_stock_data(stock_data: dict) -> dict:
        quote = stock_data.get("quote") or {}
        financial = stock_data.get("financial") or {}
        sentiment = stock_data.get("news_sentiment") or {}

        price = stock_data.get("price")
        quote_source = stock_data.get("quote_source") or quote.get("source") or ""
        quote_warnings = []
        if not is_valid_number(price):
            quote_warnings.append("latest_price_missing_or_zero")
        abnormal = quote_abnormal_reason(stock_data)
        if abnormal:
            quote_warnings.append(abnormal)
        if quote_source in QUOTE_KLINE_FALLBACK_SOURCES or quote.get("synthetic"):
            quote_warnings.append("quote_from_kline_fallback")

        kline = stock_data.get("kline_data") or []
        kline_warnings = []
        if not kline:
            kline_warnings.append("kline_missing")
        elif len(kline) < 20:
            kline_warnings.append("kline_less_than_20_days")
        kline_source = stock_data.get("kline_source") or ""
        if kline_source.endswith("-secondary"):
            kline_warnings.append("kline_secondary_source_used")
        elif kline_source == "source-unavailable":
            kline_warnings.append("kline_source_unavailable")

        valuation_warnings = []
        pe = financial.get("pe_ttm") or quote.get("pe_ttm")
        pb = financial.get("pb") or quote.get("pb")
        if not is_valid_number(pe):
            valuation_warnings.append("pe_ttm_missing")
        if not is_valid_number(pb):
            valuation_warnings.append("pb_missing")

        financial_warnings = []
        if not financial:
            financial_warnings.append("financial_missing")
        else:
            for key in ("revenue", "net_profit", "operating_cf"):
                if financial.get(key) is None:
                    financial_warnings.append(f"{key}_missing")

        ann = stock_data.get("announcements") or []
        ann_warnings = [] if ann else ["announcements_missing"]

        news = stock_data.get("news") or []
        news_warnings = [] if news else ["news_missing"]
        if sentiment and sentiment.get("validation_note"):
            news_warnings.append(str(sentiment.get("validation_note")))

        industry_event = stock_data.get("industry_event_context") or {}
        industry_warnings = list(industry_event.get("warnings") or [])
        if not industry_event.get("available"):
            industry_warnings = industry_warnings or ["industry_event_context_missing"]
        industry_evidence = []
        for theme in industry_event.get("themes") or []:
            industry_evidence.extend(theme.get("evidence") or [])

        has_financial_valuation = is_valid_number(financial.get("pe_ttm")) or is_valid_number(financial.get("pb"))
        valuation_source = financial.get("valuation_source")
        if not valuation_source and has_financial_valuation:
            valuation_source = financial.get("source") or ""
        elif not valuation_source:
            valuation_source = quote_source or financial.get("source") or ""

        return {
            "quote": DataQualityItem(
                source=quote_source,
                updated_at=str(quote.get("timestamp") or _now_iso()),
                freshness="realtime_or_latest",
                confidence="high" if quote and not quote_warnings else "medium",
                is_fallback=quote_source in QUOTE_KLINE_FALLBACK_SOURCES or bool(quote.get("synthetic")),
                warnings=quote_warnings,
            ).as_dict(),
            "kline": DataQualityItem(
                source=kline_source,
                updated_at=str(kline[-1].get("date")) if kline else None,
                freshness="latest_trading_day" if kline else "missing",
                confidence="high" if len(kline) >= 20 else ("medium" if kline else "low"),
                is_fallback=kline_source.endswith("-secondary") or kline_source in KLINE_FALLBACK_SOURCES,
                warnings=kline_warnings,
            ).as_dict(),
            "valuation": DataQualityItem(
                source=valuation_source,
                updated_at=str(quote.get("timestamp") or financial.get("report_date") or _now_iso()),
                freshness="realtime_or_latest",
                confidence="high" if not valuation_warnings else "low",
                is_fallback=valuation_source in QUOTE_KLINE_FALLBACK_SOURCES or valuation_source in KLINE_FALLBACK_SOURCES,
                warnings=valuation_warnings,
            ).as_dict(),
            "financial": DataQualityItem(
                source=financial.get("source") or "",
                updated_at=financial.get("report_date"),
                freshness="latest_report" if financial else "missing",
                confidence="high" if financial and len(financial_warnings) <= 1 else "low",
                is_fallback=False,
                warnings=financial_warnings,
            ).as_dict(),
            "announcements": DataQualityItem(
                source="cninfo/db" if ann else "",
                updated_at=ann[0].get("announce_date") if ann else None,
                freshness="latest_disclosure" if ann else "missing",
                confidence="high" if ann else "low",
                is_fallback=False,
                warnings=ann_warnings,
            ).as_dict(),
            "news": DataQualityItem(
                source="news/db" if news else "",
                updated_at=news[0].get("publish_time") if news else None,
                freshness="recent_7d" if news else "missing",
                confidence="medium" if news else "low",
                is_fallback=False,
                warnings=news_warnings,
            ).as_dict(),
            "industry_events": DataQualityItem(
                source="news/db/industry-rule-engine" if industry_event.get("available") else "",
                updated_at=industry_evidence[0].get("publish_time") if industry_evidence else None,
                freshness="recent_market_news" if industry_event.get("available") else "missing",
                confidence="medium" if industry_event.get("available") else "low",
                is_fallback=False,
                warnings=industry_warnings,
            ).as_dict(),
        }


def build_readiness(stock_data: dict, models_count: int, quota_ready: bool, quota_message: str) -> dict:
    data_quality = DataQualityBuilder.from_stock_data(stock_data)
    data_grade = build_data_grade(stock_data)
    sentiment = stock_data.get("news_sentiment") or {}
    financial = stock_data.get("financial") or {}
    quote = stock_data.get("quote") or {}

    items = {
        "ai_model": {
            "ready": models_count > 0,
            "label": "AI model",
            "count": models_count,
            "message": "model configured" if models_count > 0 else "no active model",
        },
        "quota": {
            "ready": quota_ready,
            "label": "quota",
            "message": "quota available" if quota_ready else quota_message,
        },
        "quote": {
            "ready": is_usable_quote(stock_data),
            "label": "quote",
            "count": 1 if is_usable_quote(stock_data) else 0,
            "message": "valid latest price" if is_usable_quote(stock_data) else (quote_abnormal_reason(stock_data) or "latest price missing or zero"),
            "quality": data_quality["quote"],
        },
        "kline": {
            "ready": bool(stock_data.get("kline_data")),
            "label": "K-line",
            "count": len(stock_data.get("kline_data") or []),
            "message": "K-line available" if stock_data.get("kline_data") else "K-line missing",
            "quality": data_quality["kline"],
        },
        "valuation": {
            "ready": is_valid_number(financial.get("pe_ttm") or quote.get("pe_ttm")) and is_valid_number(financial.get("pb") or quote.get("pb")),
            "label": "valuation",
            "message": "PE/PB available" if not data_quality["valuation"]["warnings"] else "PE/PB missing or incomplete",
            "quality": data_quality["valuation"],
        },
        "financial": {
            "ready": bool(financial),
            "label": "financial",
            "count": 1 if financial else 0,
            "latest_at": financial.get("report_date"),
            "message": "financial report available" if financial else "financial report missing",
            "quality": data_quality["financial"],
        },
        "announcements": {
            "ready": bool(stock_data.get("announcements")),
            "label": "announcements",
            "count": len(stock_data.get("announcements") or []),
            "message": "announcements available" if stock_data.get("announcements") else "announcements missing",
            "quality": data_quality["announcements"],
        },
        "news": {
            "ready": bool(stock_data.get("news")),
            "label": "news",
            "count": len(stock_data.get("news") or []),
            "message": "news available" if stock_data.get("news") else "news missing",
            "quality": data_quality["news"],
        },
        "sentiment": {
            "ready": bool(sentiment and sentiment.get("total", 0) > 0),
            "label": "sentiment",
            "message": sentiment.get("validation_note") or "sentiment unavailable",
            "quality": data_quality["news"],
        },
        "industry_events": {
            "ready": bool((stock_data.get("industry_event_context") or {}).get("available")),
            "label": "industry/social events",
            "count": len((stock_data.get("industry_event_context") or {}).get("themes") or []),
            "message": (stock_data.get("industry_event_context") or {}).get("note") or "industry event context unavailable",
            "quality": data_quality["industry_events"],
        },
    }
    blocking = [k for k in ("ai_model", "quota") if not items[k]["ready"]]
    missing_context = [k for k in ("quote", "kline", "valuation", "financial", "announcements", "news", "industry_events") if not items[k]["ready"]]
    return {
        "ready": len(blocking) == 0,
        "quality": "complete" if not missing_context else "usable_with_gaps",
        "blocking": blocking,
        "missing_context": missing_context,
        "items": items,
        "data_quality": data_quality,
        "data_grade": data_grade,
    }
