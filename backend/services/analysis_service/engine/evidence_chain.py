from __future__ import annotations

from typing import Any

from backend.services.analysis_service.engine.data_quality import DataQualityBuilder, is_valid_number


def _dimension_for_key(key: str) -> str:
    if key.startswith("risk_"):
        return "risk"
    mapping = {
        "base": "baseline",
        "retail_affordability": "retail_affordability",
        "market_cap": "market_cap",
        "data_quality": "data_quality",
        "technical": "technical",
        "volume": "technical",
        "valuation": "valuation",
        "financial": "financial_quality",
        "financial_revenue": "financial_quality",
        "financial_profit": "financial_quality",
        "financial_cashflow": "financial_quality",
        "news_sentiment": "sentiment",
        "industry_events": "industry_theme",
        "risk_lights": "risk",
        "capital_flow": "capital_flow",
    }
    return mapping.get(key, "general")


def _source_meta_for_dimension(data_quality: dict, dimension: str) -> tuple[str, str, str]:
    mapping = {
        "valuation": "valuation",
        "technical": "kline",
        "financial_quality": "financial",
        "sentiment": "news",
        "industry_theme": "industry_events",
        "data_quality": "quote",
        "retail_affordability": "quote",
        "market_cap": "quote",
        "risk": "quote",
        "capital_flow": "capital_flow",
        "baseline": "quote",
        "general": "quote",
    }
    key = mapping.get(dimension, "quote")
    meta = data_quality.get(key) or {}
    return (
        str(meta.get("source") or ""),
        str(meta.get("freshness") or "unknown"),
        str(meta.get("confidence") or "low"),
    )


def _value_threshold_for_key(stock_data: dict, key: str) -> tuple[Any, str]:
    quote = stock_data.get("quote") or {}
    financial = stock_data.get("financial") or {}
    if key == "retail_affordability":
        return stock_data.get("price"), "5 <= price <= 35 preferred"
    if key == "market_cap":
        return financial.get("total_mv") or quote.get("total_mv"), "30亿 <= total_mv <= 500亿 preferred"
    if key == "valuation":
        pe = financial.get("pe_ttm") or quote.get("pe_ttm")
        pb = financial.get("pb") or quote.get("pb")
        return {"pe_ttm": pe, "pb": pb}, "PE <= 35 and PB <= 5 preferred"
    if key == "financial_revenue":
        return financial.get("revenue_yoy"), "revenue_yoy > 0"
    if key == "financial_profit":
        return financial.get("net_profit_yoy"), "net_profit_yoy > 0"
    if key == "financial_cashflow":
        return financial.get("operating_cf"), "operating_cf >= 0 preferred"
    if key == "news_sentiment":
        return (stock_data.get("news_sentiment") or {}).get("weighted_dominant_sentiment"), "positive preferred"
    if key == "industry_events":
        return [item.get("theme") for item in ((stock_data.get("industry_event_context") or {}).get("themes") or [])[:3]], "theme evidence available"
    if key == "capital_flow":
        features = stock_data.get("capital_flow_features") or {}
        return {
            "signal": features.get("signal"),
            "latest_date": features.get("latest_date"),
            "latest_main_inflow": features.get("latest_main_inflow"),
            "main_inflow_3d": features.get("main_inflow_3d"),
        }, "capital flow should not materially contradict trend signal"
    if key.startswith("risk_"):
        light_key = key.replace("risk_", "", 1)
        return (stock_data.get("risk_lights") or {}).get(light_key), "no red light preferred"
    return None, ""


def build_evidence_chain(
    stock_data: dict,
    risk_lights: dict,
    strategy: dict,
    score_breakdown: list[dict] | None = None,
) -> list[dict]:
    score_breakdown = list(score_breakdown or [])
    data_quality = stock_data.get("data_quality") or DataQualityBuilder.from_stock_data(stock_data)
    evidence: list[dict] = []

    for item in score_breakdown:
        key = str(item.get("key") or "")
        dimension = _dimension_for_key(key)
        source, freshness, confidence = _source_meta_for_dimension(data_quality, dimension)
        value, threshold = _value_threshold_for_key({**stock_data, "risk_lights": risk_lights}, key)
        delta = int(float(item.get("delta") or 0))
        evidence.append(
            {
                "factor": key,
                "dimension": dimension,
                "label": item.get("label") or key,
                "value": value,
                "threshold": threshold,
                "source": source,
                "freshness": freshness,
                "confidence": confidence,
                "impact": delta,
                "direction": "positive" if delta > 0 else "negative" if delta < 0 else "neutral",
                "explanation": item.get("message") or "",
                "strategy_id": strategy.get("id"),
            }
        )

    return evidence
