"""盘前摘要生成器 — 为整个观察池生成每日概览。"""
from __future__ import annotations

import logging
from collections import Counter

logger = logging.getLogger(__name__)


def generate_pool_summary(recommendations: list[dict], market_regime: dict | None = None) -> dict:
    """
    基于观察池内容生成盘前摘要（纯规则，不调用 AI）。

    返回：
        pool_style: 观察池整体风格描述
        recommended_strategy: 当日策略建议
        biggest_risk: 最大风险提示
        tier_counts: {A: n, B: n, C: n}
        action_counts: 各动作类型数量
        highlight_symbols: A档前3只股票
    """
    if not recommendations:
        return {
            "pool_style": "观察池暂无数据",
            "recommended_strategy": "等待数据更新",
            "biggest_risk": "数据缺失，请稍后刷新",
            "tier_counts": {"A": 0, "B": 0, "C": 0},
            "action_counts": {},
            "highlight_symbols": [],
        }

    # 分层统计
    tier_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    for rec in recommendations:
        t = rec.get("tier", "C")
        tier_counts[t] = tier_counts.get(t, 0) + 1

    # 动作统计
    action_counts: Counter = Counter()
    for rec in recommendations:
        action = rec.get("observation_action") or "其他"
        action_counts[action] += 1

    # A档前3只
    a_tier = [r for r in recommendations if r.get("tier") == "A"]
    highlight_symbols = [
        {"symbol": r.get("symbol", ""), "name": r.get("name", ""), "action": r.get("observation_action", "")}
        for r in a_tier[:3]
    ]

    # 市场风格
    regime = (market_regime or {}).get("regime", "unknown")
    pool_style = _derive_pool_style(tier_counts, action_counts, regime)

    # 策略建议
    recommended_strategy = _derive_strategy(tier_counts, action_counts, regime)

    # 最大风险
    biggest_risk = _derive_biggest_risk(recommendations, regime)

    return {
        "pool_style": pool_style,
        "recommended_strategy": recommended_strategy,
        "biggest_risk": biggest_risk,
        "tier_counts": tier_counts,
        "action_counts": dict(action_counts),
        "highlight_symbols": highlight_symbols,
        "optimizer": _derive_optimizer_summary(recommendations, market_regime),
    }


def _derive_optimizer_summary(recommendations: list[dict], market_regime: dict | None = None) -> dict:
    optimizer_rows = [
        rec.get("pool_optimizer")
        for rec in recommendations
        if isinstance(rec.get("pool_optimizer"), dict)
    ]
    if not optimizer_rows:
        return {
            "status": "not_applied",
            "regime": (market_regime or {}).get("regime", "unknown"),
            "adjusted": 0,
        }

    news_rows = [row.get("news") or {} for row in optimizer_rows if isinstance(row.get("news"), dict)]
    with_news = sum(1 for item in news_rows if item.get("has_news"))
    fresh = sum(1 for item in news_rows if float(item.get("freshness_score") or 0) >= 0.65)
    stale = sum(1 for item in news_rows if item.get("has_news") and float(item.get("freshness_score") or 0) < 0.65)
    adjusted = sum(1 for row in optimizer_rows if row.get("adjustments"))
    tier_changes = sum(1 for row in optimizer_rows if row.get("tier_before") != row.get("tier_after"))
    priority_changes = sum(1 for row in optimizer_rows if row.get("priority_before") != row.get("priority_after"))
    return {
        "status": "ok",
        "version": optimizer_rows[0].get("version"),
        "mode": optimizer_rows[0].get("mode"),
        "regime": optimizer_rows[0].get("regime") or (market_regime or {}).get("regime", "unknown"),
        "regime_confidence": optimizer_rows[0].get("regime_confidence"),
        "processed": len(optimizer_rows),
        "adjusted": adjusted,
        "tier_changes": tier_changes,
        "priority_changes": priority_changes,
        "news_quality": {
            "with_news": with_news,
            "fresh": fresh,
            "stale": stale,
        },
        "diversification": {
            "penalties_applied": sum(1 for rec in recommendations if rec.get("diversification_penalty")),
            "max_industry_count": max(
                Counter(
                    rec.get("industry_name") or rec.get("sector") or "UNKNOWN"
                    for rec in recommendations
                ).values(),
                default=0,
            ),
        },
    }


def _derive_pool_style(tier_counts: dict, action_counts: Counter, regime: str) -> str:
    total = sum(tier_counts.values()) or 1
    a_ratio = tier_counts.get("A", 0) / total
    c_ratio = tier_counts.get("C", 0) / total

    top_action = action_counts.most_common(1)[0][0] if action_counts else "回踩承接"

    if regime == "strong_trend":
        if a_ratio >= 0.4:
            return "强趋势池，A档占比高，突破型机会为主"
        return "强趋势市，但共振信号分散，注意选股"
    elif regime == "weak_market":
        return "弱市防守池，以只看不追为主，严控风险"
    else:
        if a_ratio >= 0.3:
            return "温和趋势池，回踩承接机会为主" if "回踩承接" in top_action else f"震荡池，{top_action}为主"
        if c_ratio >= 0.5:
            return "观察池质量偏低，多数仅基础达标，建议降低预期"
        return "震荡市观察池，信号分散，谨慎操作"


def _derive_strategy(tier_counts: dict, action_counts: Counter, regime: str) -> str:
    total = sum(tier_counts.values()) or 1
    a_count = tier_counts.get("A", 0)
    watch_only_count = action_counts.get("只看不追", 0)

    if regime == "weak_market":
        return "弱市不追高，观察为主，等待市场企稳信号"

    if watch_only_count / total >= 0.3:
        return "池内追高类较多，优先关注 A 档低吸机会，不追涨"

    if a_count == 0:
        return "A 档暂无共振信号，降低操作频率，等待更强信号"

    top_action = action_counts.most_common(1)[0][0] if action_counts else "回踩承接"
    if top_action == "回踩承接":
        return f"优先关注 A 档{a_count}只，策略：等回踩确认后低吸，不追高开"
    elif top_action == "放量突破":
        return f"优先关注 A 档{a_count}只，策略：等放量突破确认，避免假突破"
    elif top_action == "消息验证":
        return f"消息驱动较多，先验证资讯真实性，严控仓位"
    else:
        return f"优先关注 A 档{a_count}只{top_action}机会，仓位控制在 30% 以内"


def _derive_biggest_risk(recommendations: list[dict], regime: str) -> str:
    if regime == "weak_market":
        return "弱市环境下观察池整体承压，若指数持续低迷，A 档也建议降级观察"

    # 统计 bear_case 关键词
    risk_keywords = Counter()
    risk_map = {
        "回落": "高开回落", "追高": "追高受套", "量能不足": "量能不足",
        "失效": "技术位失效", "退潮": "题材退潮", "减持": "大股东减持风险",
        "亏损": "基本面恶化", "集采": "行业政策风险", "低开": "低开承压",
    }
    for rec in recommendations:
        bear_case = rec.get("bear_case") or []
        for bc in bear_case:
            bc_text = str(bc)
            for kw, label in risk_map.items():
                if kw in bc_text:
                    risk_keywords[label] += 1

    if risk_keywords:
        top_risk, count = risk_keywords.most_common(1)[0]
        if count >= 3:
            return f"警惕{top_risk}（{count}只股票提示该风险）"
        return f"主要风险：{top_risk}，操作前确认技术面信号"

    # 检查追高惩罚
    penalized = sum(1 for r in recommendations if r.get("chase_high_penalty"))
    if penalized >= 3:
        return f"池内{penalized}只股票有追高惩罚，整体注意追高风险，优先等回踩"

    return "整体风险可控，注意开盘前 15 分钟竞价确认，避免快速高开低走"
