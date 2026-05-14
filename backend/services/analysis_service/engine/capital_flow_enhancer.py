"""AKShare 资金流第三层验证：可选、非阻塞地增强每日观察池候选股。"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from backend.services.data_crawler.sources.akshare_source import AKShareSource

logger = logging.getLogger(__name__)

CONCURRENCY = 4
FLOW_LIMIT = 20


async def enhance_candidates_with_capital_flow(
    candidates: list[dict],
    trade_date: str | None = None,
) -> tuple[list[dict], dict]:
    if not candidates:
        return candidates, {"status": "skipped", "reason": "no_candidates", "checked": 0}

    if os.getenv("AKSHARE_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        for item in candidates:
            _attach_unavailable(item, "disabled", ["akshare_money_flow_disabled"])
        return candidates, {"status": "skipped", "reason": "disabled", "checked": 0}

    source = AKShareSource()
    if not getattr(source, "_akshare_available", False):
        for item in candidates:
            _attach_unavailable(item, "unavailable", ["akshare_money_flow_source_error"])
        return candidates, {"status": "unavailable", "reason": "akshare_not_installed", "checked": 0}

    semaphore = asyncio.Semaphore(CONCURRENCY)
    summary = {
        "status": "ok",
        "checked": 0,
        "confirming": 0,
        "contradicting": 0,
        "neutral": 0,
        "unavailable": 0,
        "warnings": 0,
    }

    async def enrich_one(item: dict) -> None:
        async with semaphore:
            try:
                rows = await source.fetch_money_flow(item.get("symbol", ""), limit=FLOW_LIMIT)
                features = summarize_capital_flow(rows, trade_date)
                item["capital_flow_features"] = features
                item["capital_flow_status"] = features["signal"]
                item["capital_flow_warnings"] = features.get("warnings", [])
            except Exception as e:
                logger.warning("AKShare money flow failed for %s: %s", item.get("symbol"), e)
                _attach_unavailable(item, "unavailable", ["akshare_money_flow_source_error"])

    await asyncio.gather(*(enrich_one(item) for item in candidates))

    for item in candidates:
        signal = item.get("capital_flow_status") or "unavailable"
        summary["checked"] += 1
        if signal in {"confirming", "contradicting", "neutral", "unavailable"}:
            summary[signal] += 1
        if item.get("capital_flow_warnings"):
            summary["warnings"] += 1

    if summary["unavailable"] == summary["checked"]:
        summary["status"] = "unavailable"
    elif summary["unavailable"] or summary["warnings"]:
        summary["status"] = "partial"

    return candidates, summary


def summarize_capital_flow(rows: list[dict], trade_date: str | None = None) -> dict:
    usable = [row for row in rows if row.get("date")]
    if trade_date:
        usable = [row for row in usable if str(row.get("date"))[:10] <= trade_date]
    usable.sort(key=lambda row: str(row.get("date")))

    if not usable:
        return {
            "source": "akshare",
            "signal": "unavailable",
            "latest_date": None,
            "latest_main_inflow": None,
            "main_inflow_3d": None,
            "main_inflow_5d": None,
            "positive_days": 0,
            "warnings": ["akshare_money_flow_empty"],
        }

    latest = usable[-1]
    latest_main = _to_float(latest.get("main_inflow"))
    last_3 = usable[-3:]
    last_5 = usable[-5:]
    main_3d = sum(_to_float(row.get("main_inflow")) for row in last_3)
    main_5d = sum(_to_float(row.get("main_inflow")) for row in last_5)
    positive_days = sum(1 for row in usable if _to_float(row.get("main_inflow")) > 0)

    if latest_main > 0 and main_3d > 0:
        signal = "confirming"
    elif latest_main < 0 and main_3d < 0:
        signal = "contradicting"
    else:
        signal = "neutral"

    warnings = []
    if not any(_to_float(latest.get(key)) for key in ("small_inflow", "mid_inflow", "big_inflow", "super_inflow")):
        warnings.append("akshare_money_flow_partial_schema")

    return {
        "source": "akshare",
        "signal": signal,
        "latest_date": str(latest.get("date"))[:10],
        "latest_main_inflow": round(latest_main, 2),
        "main_inflow_3d": round(main_3d, 2),
        "main_inflow_5d": round(main_5d, 2),
        "positive_days": positive_days,
        "sample_size": len(usable),
        "warnings": warnings,
        "updated_at": datetime.now().isoformat(),
    }


def build_capital_flow_score_item(item: dict) -> dict:
    features = item.get("capital_flow_features") or {}
    signal = features.get("signal") or item.get("capital_flow_status") or "unavailable"
    delta = 2 if signal == "confirming" else -3 if signal == "contradicting" else 0
    label = "资金流验证"

    if signal == "confirming":
        message = "AKShare主力资金流确认趋势信号"
    elif signal == "contradicting":
        message = "AKShare主力资金流与趋势信号背离"
    elif signal == "neutral":
        message = "AKShare主力资金流方向不明确"
    else:
        message = "AKShare资金流数据不可用"

    return {
        "key": "capital_flow",
        "delta": delta,
        "label": label,
        "message": message,
        "source": "akshare",
        "status": signal,
        "features": features,
    }


def apply_capital_flow_risk_light(item: dict, risk_lights: dict) -> None:
    if item.get("capital_flow_status") != "contradicting":
        return
    risk_lights["capital_flow_divergence"] = {
        "level": "yellow",
        "type": "capital_flow_divergence",
        "message": "AKShare主力资金流与趋势信号背离，仅作为软风险提示",
    }


def _attach_unavailable(item: dict, status: str, warnings: list[str]) -> None:
    item["capital_flow_features"] = {
        "source": "akshare",
        "signal": "unavailable",
        "status": status,
        "warnings": warnings,
    }
    item["capital_flow_status"] = "unavailable"
    item["capital_flow_warnings"] = warnings


def _to_float(value) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
