"""观察动作生成器 — 为每只观察池股票生成操作建议和触发/失效条件。"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from backend.services.analysis_service.engine.ai_client import ai_client
from backend.shared.auth import decrypt_api_key
from backend.shared.database import SessionLocal
from sqlalchemy import text

logger = logging.getLogger(__name__)

SECONDARY_MODEL_ID = "glm-5"
GLM_MODEL_ID = os.getenv("GLM_MODEL_ID", SECONDARY_MODEL_ID)
GLM_BASE_URL = os.getenv("GLM_BASE_URL") or os.getenv("NEWS_PREFILTER_BASE_URL")
GLM_API_KEY = os.getenv("GLM_API_KEY") or os.getenv("NEWS_PREFILTER_API_KEY")
GLM_REQUEST_TIMEOUT = float(os.getenv("GLM_REQUEST_TIMEOUT", "45"))


def _glm_env_model() -> dict | None:
    api_key = (GLM_API_KEY or "").strip()
    if not api_key:
        return None
    return {
        "id": None,
        "name": SECONDARY_MODEL_ID,
        "provider": "openai",
        "model_id": GLM_MODEL_ID,
        "api_base_url": GLM_BASE_URL,
        "api_key": api_key,
        "config": {"temperature": 0.2, "max_tokens": 300, "timeout": GLM_REQUEST_TIMEOUT, "max_retries": 0},
    }

# 观察动作类型
ACTION_PULLBACK = "回踩承接"
ACTION_BREAKOUT = "放量突破"
ACTION_CONSOLIDATE = "缩量企稳"
ACTION_WATCH_ONLY = "只看不追"
ACTION_NEWS_VERIFY = "消息验证"


def _get_ai_models() -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT id, name, provider, model_id, api_base_url, api_key_encrypted, config
                FROM ai_models WHERE is_active = true ORDER BY sort_order, id
            """)
        ).fetchall()
        models = [
            {
                "id": r[0], "name": r[1], "provider": r[2], "model_id": r[3],
                "api_base_url": r[4], "api_key": decrypt_api_key(r[5]), "config": r[6] or {},
            }
            for r in rows
        ]
        has_glm = any(model.get("name") == SECONDARY_MODEL_ID or model.get("model_id") == GLM_MODEL_ID for model in models)
        glm_model = _glm_env_model()
        if glm_model and not has_glm:
            models.insert(1 if models else 0, glm_model)
        return models
    finally:
        db.close()


def _extract_score_dim(score_breakdown: list | dict | None, key: str) -> float:
    if not score_breakdown:
        return 0.0
    if isinstance(score_breakdown, dict):
        return float(score_breakdown.get(key, 0) or 0)
    for item in score_breakdown:
        if isinstance(item, dict) and item.get("key") == key:
            # pipeline 输出格式用 "delta" 存分值
            return float(item.get("delta") or item.get("value") or 0)
    return 0.0


def _rule_based_action(rec: dict) -> str:
    """规则层：根据评分模式和追高状态决定动作类型。"""
    # 追高惩罚过的 → 只看不追
    if rec.get("chase_high_penalty"):
        return ACTION_WATCH_ONLY

    # 有明确资讯催化剂但技术面不明 → 消息验证
    evidence_chain = rec.get("evidence_chain") or []
    has_catalyst = False
    for item in evidence_chain:
        if isinstance(item, dict) and item.get("factor") == "news_impact_agent":
            value = item.get("value", {})
            catalyst_type = value.get("catalyst_type", "none")
            if catalyst_type in ("announcement", "industry_policy", "news_positive"):
                has_catalyst = True
            break

    score_breakdown = rec.get("score_breakdown")
    # pipeline score_breakdown key: trend / volume_price / safety
    trend_score = _extract_score_dim(score_breakdown, "trend")
    vol_price_score = _extract_score_dim(score_breakdown, "volume_price")
    safety_score = _extract_score_dim(score_breakdown, "safety")

    # 消息驱动但技术面弱 → 消息验证
    if has_catalyst and trend_score < 15:
        return ACTION_NEWS_VERIFY

    # 波动收窄 + 缩量 → 缩量企稳
    if safety_score >= 18 and vol_price_score < 12:
        return ACTION_CONSOLIDATE

    # 强趋势 + 量价好 + 距离 MA20 较远 → 放量突破
    if trend_score >= 22 and vol_price_score >= 15:
        return ACTION_BREAKOUT

    # 趋势好 + 近 MA20 + 量能温和 → 回踩承接
    if trend_score >= 18 and safety_score >= 18:
        return ACTION_PULLBACK

    # 默认：回踩承接
    return ACTION_PULLBACK


def _build_action_context(rec: dict) -> str:
    """构建给 AI 的上下文信息。"""
    symbol = rec.get("symbol", "")
    name = rec.get("name", "")
    price = rec.get("price") or rec.get("close_price", 0)
    change_pct = rec.get("change_pct", 0)
    score = rec.get("score", 0)
    tier = rec.get("tier", "")
    action = rec.get("observation_action", "")

    parts = [f"股票：{name}（{symbol}）｜当前价：{price}｜今日涨跌：{change_pct:.2f}%｜综合得分：{score}｜分层：{tier}档｜规则推荐动作：{action}"]

    # 评分维度
    breakdown = rec.get("score_breakdown")
    if breakdown:
        if isinstance(breakdown, dict):
            dims = [f"趋势{breakdown.get('trend_quality',0)}", f"安全边际{breakdown.get('safety_margin',0)}",
                    f"量价{breakdown.get('volume_price',0)}", f"技术位{breakdown.get('technical_position',0)}"]
        else:
            dims = [f"{b.get('key','')}:{b.get('value',0)}" for b in breakdown if isinstance(b, dict)]
        parts.append("评分维度：" + " | ".join(dims[:4]))

    # 主要证据
    evidence = rec.get("evidence_chain") or []
    for ev in evidence[:3]:
        if isinstance(ev, dict):
            explanation = ev.get("explanation") or ev.get("label", "")
            if explanation:
                parts.append(f"证据：{explanation[:80]}")

    # 多空观点
    bull = rec.get("bull_case") or []
    bear = rec.get("bear_case") or []
    if bull:
        parts.append(f"看多：{bull[0][:60] if isinstance(bull[0], str) else str(bull[0])[:60]}")
    if bear:
        parts.append(f"看空：{bear[0][:60] if isinstance(bear[0], str) else str(bear[0])[:60]}")

    # 失效条件（已有）
    falsification = rec.get("falsification") or []
    if falsification:
        parts.append(f"已有失效条件：{falsification[0][:60] if isinstance(falsification[0], str) else str(falsification[0])[:60]}")

    return "\n".join(parts)


async def _ai_generate_conditions(rec: dict, models: list[dict]) -> dict | None:
    """用 AI 生成具体的触发/失效/风险条件。"""
    context = _build_action_context(rec)
    action = rec.get("observation_action", "回踩承接")
    price = rec.get("price") or rec.get("close_price", 0)

    system_prompt = (
        "你是A股交易辅助 Agent，负责为观察池股票生成次日具体的操作条件。"
        "根据技术面数据和评分结果，用简洁的中文描述触发条件、失效条件和追高风险提示。"
        "条件必须具体，尽量包含价格参考。输出严格 JSON，不要 Markdown。"
    )
    user_prompt = (
        f"{context}\n\n"
        f"当前股价约 {price}。观察动作为：{action}。\n\n"
        "请生成次日盘前操作条件，输出 JSON，字段：\n"
        "trigger_condition（触发条件，1-2句话，含价格参考），\n"
        "invalidation_condition（失效条件，1-2句话，含价格参考），\n"
        "risk_warning（追高风险提示，1句话）。\n"
        "要求：具体可操作，不要模糊表述如'视情况而定'。"
    )

    for model in models[:3]:  # 最多尝试 3 个模型
        try:
            result = await ai_client.analyze(
                provider=model["provider"],
                model_id=model["model_id"],
                api_key=model["api_key"],
                api_base_url=model["api_base_url"],
                config={**model["config"], "max_tokens": 200, "temperature": 0.3},
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            raw = (result.get("content") or "").strip()
            if not raw:
                continue
            # 解析 JSON
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("trigger_condition"):
                return payload
        except Exception as e:
            logger.debug("AI condition generation failed for %s with %s: %s", rec.get("symbol"), model.get("name"), e)

    return None


def _rule_based_conditions(rec: dict) -> dict:
    """规则层兜底：生成通用条件描述（不含具体价位）。"""
    action = rec.get("observation_action", "回踩承接")
    change_pct = abs(float(rec.get("change_pct") or 0))

    if action == ACTION_PULLBACK:
        trigger = "开盘后回踩企稳，30 分钟内守住昨日收盘价附近，量能温和放大"
        invalidation = "跌破昨日收盘价且半小时内无法收回"
        risk = "若高开超过 3%，等回踩确认后再考虑，不追高"
    elif action == ACTION_BREAKOUT:
        trigger = "放量突破近期高点，首小时成交额明显放大，突破后不快速回落"
        invalidation = "突破后快速回落至高点下方，或量能明显萎缩"
        risk = f"今日已涨{change_pct:.1f}%，若继续高开须谨慎，量能不足不追"
    elif action == ACTION_CONSOLIDATE:
        trigger = "缩量横盘在均线附近企稳，无明显抛压，等待量能温和放大"
        invalidation = "出现明显放量下跌，跌破均线支撑"
        risk = "若开盘直接大幅低开，可能是换手筑底信号弱化"
    elif action == ACTION_WATCH_ONLY:
        trigger = "当日已有一定涨幅，仅观察，不参与追高"
        invalidation = "不适用（只看不追模式）"
        risk = f"今日涨幅{change_pct:.1f}%，追高风险较高，等下一个低吸机会"
    elif action == ACTION_NEWS_VERIFY:
        trigger = "开盘后资讯兑现确认，量能配合放大，股价稳步拉升"
        invalidation = "消息证伪或开盘高开低走，半小时内回落超 2%"
        risk = "消息驱动不确定性高，严控仓位，开盘竞价观察"
    else:
        trigger = "开盘后观察走势确认"
        invalidation = "跌破昨日收盘价"
        risk = "注意控制仓位和风险"

    return {
        "trigger_condition": trigger,
        "invalidation_condition": invalidation,
        "risk_warning": risk,
    }


async def generate_observation_actions(recommendations: list[dict], use_ai: bool = True) -> list[dict]:
    """
    为观察池每只股票生成观察动作和触发/失效条件。

    先用规则层确定动作类型，再用 AI 层生成具体价位条件。
    如果 AI 不可用，回退到规则层兜底描述。
    """
    models = _get_ai_models() if use_ai else []

    for rec in recommendations:
        # 规则层决定动作类型
        rec["observation_action"] = _rule_based_action(rec)

        # AI 生成具体条件
        conditions: dict | None = None
        if models:
            try:
                import asyncio
                conditions = await asyncio.wait_for(
                    _ai_generate_conditions(rec, models),
                    timeout=20,
                )
            except Exception as e:
                logger.debug("AI condition generation timed out for %s: %s", rec.get("symbol"), e)

        # 兜底
        if not conditions or not conditions.get("trigger_condition"):
            conditions = _rule_based_conditions(rec)

        rec["trigger_condition"] = conditions.get("trigger_condition", "")
        rec["invalidation_condition"] = conditions.get("invalidation_condition", "")
        rec["risk_warning"] = conditions.get("risk_warning", "")

    logger.info("Observation actions generated for %d stocks", len(recommendations))
    return recommendations
