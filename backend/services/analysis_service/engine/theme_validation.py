from __future__ import annotations

from typing import Any


BUSINESS_KEYWORDS = (
    "收入",
    "营收",
    "订单",
    "合同",
    "产能",
    "客户",
    "项目",
    "中标",
    "交付",
    "量产",
    "扩产",
    "利润",
    "现金流",
)

CHAIN_STAGE_KEYWORDS = {
    "upstream": ("原材料", "资源", "煤炭", "石油", "有色", "钢铁", "化工", "芯片", "元件", "设备"),
    "midstream": ("制造", "加工", "组件", "零部件", "设备", "软件", "系统", "平台", "数据中心", "算力"),
    "downstream": ("消费", "零售", "旅游", "酒店", "汽车", "家电", "应用", "服务", "运营", "客户"),
}


def _text_of(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ("title", "summary", "content", "category", "related_sector"))


def _latest_items(items: list[dict[str, Any]], limit: int = 3) -> list[dict[str, str]]:
    result = []
    for item in items[:limit]:
        result.append(
            {
                "title": str(item.get("title") or "")[:120],
                "source": str(item.get("source") or item.get("category") or "")[:40],
                "date": str(item.get("publish_time") or item.get("announce_date") or "")[:30],
            }
        )
    return result


def _chain_stage(sector: str, themes: list[dict[str, Any]]) -> str:
    text = f"{sector} " + " ".join(str(theme.get("theme") or "") for theme in themes)
    scores = {
        stage: sum(1 for keyword in keywords if keyword in text)
        for stage, keywords in CHAIN_STAGE_KEYWORDS.items()
    }
    best_stage, best_score = max(scores.items(), key=lambda item: item[1])
    return best_stage if best_score > 0 else "unknown"


def _verification_evidence(stock_data: dict) -> tuple[list[dict[str, str]], list[str]]:
    evidence: list[dict[str, str]] = []
    signals: list[str] = []

    for item in stock_data.get("announcements") or []:
        item = item if isinstance(item, dict) else {}
        text = _text_of(item)
        matched = [keyword for keyword in BUSINESS_KEYWORDS if keyword in text]
        if matched:
            evidence.append(
                {
                    "type": "announcement",
                    "title": str(item.get("title") or "")[:120],
                    "source": str(item.get("category") or "announcement")[:40],
                    "date": str(item.get("announce_date") or "")[:30],
                    "matched": ",".join(matched[:4]),
                }
            )
            signals.extend(matched)
        if len(evidence) >= 3:
            break

    financial = stock_data.get("financial") or {}
    for key, label in (
        ("revenue_yoy", "revenue_yoy_positive"),
        ("net_profit_yoy", "profit_yoy_positive"),
        ("operating_cf", "operating_cf_positive"),
    ):
        value = financial.get(key)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            evidence.append(
                {
                    "type": "financial",
                    "title": label,
                    "source": "financial_report",
                    "date": str(financial.get("report_date") or "")[:30],
                    "matched": key,
                }
            )
            signals.append(label)

    return evidence[:5], sorted(set(signals))


def build_theme_validation(stock_data: dict, strategy: dict | None = None) -> dict:
    industry = stock_data.get("industry_event_context") or {}
    themes = [theme for theme in (industry.get("themes") or []) if isinstance(theme, dict)]
    sector = str(stock_data.get("sector") or industry.get("sector") or "")
    strategy_id = str((strategy or {}).get("id") or "")

    if not themes:
        return {
            "status": "no_theme",
            "theme_heat": {"level": "none", "themes": []},
            "chain_position": {"stage": "unknown", "sector": sector},
            "business_relevance": {"level": "unknown", "reason": "no industry theme matched"},
            "verification": {"level": "missing", "evidence": [], "signals": []},
            "concept_risk": {"level": "unknown", "warnings": ["theme_evidence_missing"]},
            "strategy_id": strategy_id,
        }

    theme_names = [str(theme.get("theme") or "") for theme in themes[:3] if theme.get("theme")]
    high_confidence = sum(1 for theme in themes if theme.get("confidence") == "high")
    medium_confidence = sum(1 for theme in themes if theme.get("confidence") == "medium")
    heat_level = "high" if high_confidence >= 1 and len(themes) >= 2 else "medium" if high_confidence or medium_confidence else "low"
    stage = _chain_stage(sector, themes)
    evidence, signals = _verification_evidence(stock_data)

    related = any(theme.get("confidence") in {"high", "medium"} for theme in themes)
    relevance_level = "direct" if related and sector else "indirect" if related else "weak"
    verification_level = "verified" if evidence else "unverified"
    risk_warnings = []
    if verification_level == "unverified":
        risk_warnings.append("theme_without_company_business_evidence")
    if heat_level == "high" and verification_level == "unverified":
        risk_warnings.append("hot_theme_may_be_concept_hype")

    concept_level = "low" if verification_level == "verified" and relevance_level == "direct" else "medium" if related else "high"
    return {
        "status": "ok",
        "theme_heat": {
            "level": heat_level,
            "themes": theme_names,
            "evidence": _latest_items([item for theme in themes for item in (theme.get("evidence") or [])], limit=3),
        },
        "chain_position": {
            "stage": stage,
            "sector": sector,
            "reason": "sector and theme keyword mapping",
        },
        "business_relevance": {
            "level": relevance_level,
            "reason": "sector/theme matched" if related else "theme exists but sector match is weak",
        },
        "verification": {
            "level": verification_level,
            "evidence": evidence,
            "signals": signals,
        },
        "concept_risk": {
            "level": concept_level,
            "warnings": risk_warnings,
        },
        "strategy_id": strategy_id,
    }
