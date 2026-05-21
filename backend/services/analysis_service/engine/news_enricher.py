"""Nightly news-impact agent for the daily observation pool."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from backend.shared.auth import decrypt_api_key
from backend.shared.database import SessionLocal
from backend.shared.models import ResearchObservation
from backend.services.analysis_service.engine.ai_client import ai_client
from backend.services.analysis_service.engine.news_signal_aggregator import (
    aggregate_news_signals,
    build_enriched_news_context,
)
from backend.services.analysis_service.engine.observation_action_generator import generate_observation_actions
from backend.services.analysis_service.engine.tier_classifier import classify_tiers

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "grok-420-fast"
SECONDARY_MODEL_ID = "glm-5"
NEWS_ENRICH_MODEL_NAME = os.getenv("NEWS_ENRICH_MODEL_NAME", DEFAULT_MODEL_NAME)
NEWS_ENRICH_MODEL_ID = os.getenv("NEWS_ENRICH_MODEL_ID", NEWS_ENRICH_MODEL_NAME)
NEWS_ENRICH_PROVIDER = os.getenv("NEWS_ENRICH_PROVIDER", "openai")
NEWS_COUNT = 5
NEWS_ENRICH_LIMIT = int(os.getenv("NEWS_ENRICH_LIMIT", "80"))
NEWS_IMPACT_FACTOR = "news_impact_agent"
NEWS_PREFILTER_ENABLED = os.getenv("NEWS_PREFILTER_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
NEWS_PREFILTER_MODEL = os.getenv("NEWS_PREFILTER_MODEL", "glm-5")
NEWS_PREFILTER_TIMEOUT = float(os.getenv("NEWS_PREFILTER_TIMEOUT", "45"))
NEWS_PREFILTER_MAX_RETRIES = int(os.getenv("NEWS_PREFILTER_MAX_RETRIES", "0"))
NEWS_PREFILTER_BASE_URL = (
    os.getenv("NEWS_PREFILTER_BASE_URL")
    or os.getenv("GLM_BASE_URL")
    or os.getenv("SILICONFLOW_BASE_URL")
    or "https://openai.chatnewai.com"
)
NEWS_PREFILTER_API_KEY = os.getenv("NEWS_PREFILTER_API_KEY") or os.getenv("GLM_API_KEY") or os.getenv("SILICONFLOW_API_KEY")
NEWS_ENRICH_BASE_URL = (
    os.getenv("NEWS_ENRICH_BASE_URL")
    or os.getenv("GROK_BASE_URL")
    or os.getenv("GLM_BASE_URL")
    or NEWS_PREFILTER_BASE_URL
)
NEWS_ENRICH_API_KEY = (
    os.getenv("NEWS_ENRICH_API_KEY")
    or os.getenv("GROK_API_KEY")
    or os.getenv("GLM_API_KEY")
    or NEWS_PREFILTER_API_KEY
)
NEWS_ENRICH_REQUEST_TIMEOUT = float(os.getenv("NEWS_ENRICH_REQUEST_TIMEOUT", "90"))
NEWS_ENRICH_MAX_RETRIES = int(os.getenv("NEWS_ENRICH_MAX_RETRIES", "0"))
GLM_MODEL_ID = os.getenv("GLM_MODEL_ID", SECONDARY_MODEL_ID)
GLM_BASE_URL = os.getenv("GLM_BASE_URL") or NEWS_PREFILTER_BASE_URL
GLM_API_KEY = os.getenv("GLM_API_KEY") or NEWS_PREFILTER_API_KEY
GLM_REQUEST_TIMEOUT = float(os.getenv("GLM_REQUEST_TIMEOUT", "45"))


def _news_enrich_env_model() -> dict | None:
    api_key = (NEWS_ENRICH_API_KEY or "").strip()
    if not api_key:
        return None
    return {
        "name": NEWS_ENRICH_MODEL_NAME,
        "provider": NEWS_ENRICH_PROVIDER,
        "model_id": NEWS_ENRICH_MODEL_ID,
        "api_key": api_key,
        "api_base_url": NEWS_ENRICH_BASE_URL,
        "config": {
            "temperature": 0.1,
            "max_tokens": 1200,
            "timeout": NEWS_ENRICH_REQUEST_TIMEOUT,
            "max_retries": NEWS_ENRICH_MAX_RETRIES,
        },
    }


def _glm_env_model() -> dict | None:
    api_key = (GLM_API_KEY or "").strip()
    if not api_key:
        return None
    return {
        "name": SECONDARY_MODEL_ID,
        "provider": "openai",
        "model_id": GLM_MODEL_ID,
        "api_key": api_key,
        "api_base_url": GLM_BASE_URL,
        "config": {"temperature": 0.2, "max_tokens": 1000, "timeout": GLM_REQUEST_TIMEOUT, "max_retries": 0},
    }


def _build_virtual_model(model: dict, *, name: str, model_id: str) -> dict:
    virtual = dict(model)
    virtual["name"] = name
    virtual["model_id"] = model_id
    return virtual


def _find_model(models: list[dict], *, name: str, model_id: str) -> dict | None:
    return next(
        (
            model for model in models
            if model.get("name") == name or model.get("model_id") == model_id
        ),
        None,
    )


def _dedupe_models(models: list[dict | None]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for model in models:
        if not model:
            continue
        key = (str(model.get("name") or ""), str(model.get("model_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(model)
    return result


def _fetch_candidate_models() -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT id, name, provider, model_id, api_base_url, api_key_encrypted, config
                FROM ai_models
                WHERE is_active = true
                ORDER BY sort_order, id
            """)
        ).fetchall()
        models = []
        for row in rows:
            models.append(
                {
                    "id": row[0],
                    "name": row[1],
                    "provider": row[2],
                    "model_id": row[3],
                    "api_base_url": row[4],
                    "api_key": decrypt_api_key(row[5]),
                    "config": row[6] or {},
                }
            )
        primary_model = (
            _find_model(models, name=NEWS_ENRICH_MODEL_NAME, model_id=NEWS_ENRICH_MODEL_ID)
            or _news_enrich_env_model()
        )
        glm_model = (
            _find_model(models, name=SECONDARY_MODEL_ID, model_id=GLM_MODEL_ID)
            or _glm_env_model()
        )
        return _dedupe_models([primary_model, glm_model])
    finally:
        db.close()


def latest_observation_trade_date() -> str | None:
    db = SessionLocal()
    try:
        row = (
            db.query(ResearchObservation.snapshot_date)
            .order_by(ResearchObservation.snapshot_date.desc(), ResearchObservation.id.desc())
            .first()
        )
        if not row or not row[0]:
            return None
        return row[0].date().isoformat()
    finally:
        db.close()


def news_impact_stats(trade_date: str) -> dict:
    db = SessionLocal()
    try:
        target_day = date.fromisoformat(trade_date)
        start = datetime.combine(target_day, time.min)
        end = start + timedelta(days=1)
        base_query = db.query(ResearchObservation).filter(
            ResearchObservation.snapshot_date >= start,
            ResearchObservation.snapshot_date < end,
        )
        formal_query = base_query.filter(ResearchObservation.strategy_id != "snapshot_fast_recovery")
        query = formal_query if formal_query.first() is not None else base_query
        rows = (
            query.with_entities(ResearchObservation.evidence_chain_json)
            .all()
        )
        enriched = 0
        for row in rows:
            chain = row[0] or []
            if isinstance(chain, str):
                try:
                    chain = json.loads(chain)
                except Exception:
                    chain = []
            if any(isinstance(item, dict) and item.get("factor") == NEWS_IMPACT_FACTOR for item in chain):
                enriched += 1
        return {"trade_date": trade_date, "total": len(rows), "enriched": enriched}
    finally:
        db.close()


def _fetch_today_observations(trade_date: str) -> list[dict]:
    db = SessionLocal()
    try:
        target_day = date.fromisoformat(trade_date)
        start = datetime.combine(target_day, time.min)
        end = start + timedelta(days=1)
        base_query = db.query(ResearchObservation).filter(
            ResearchObservation.snapshot_date >= start,
            ResearchObservation.snapshot_date < end,
        )
        formal_query = base_query.filter(ResearchObservation.strategy_id != "snapshot_fast_recovery")
        query = formal_query if formal_query.first() is not None else base_query
        rows = (
            query.with_entities(
                ResearchObservation.id,
                ResearchObservation.symbol,
                ResearchObservation.evidence_chain_json,
            )
            .order_by(ResearchObservation.score.desc())
            .limit(NEWS_ENRICH_LIMIT)
            .all()
        )
        return [{"id": r[0], "symbol": r[1], "evidence_chain": r[2]} for r in rows]
    finally:
        db.close()


def _fetch_stock_name(symbol: str) -> str:
    db = SessionLocal()
    try:
        code = symbol.split(".")[0]
        row = db.execute(text("SELECT name FROM stocks WHERE symbol = :s"), {"s": code}).fetchone()
        return row[0] if row else symbol
    finally:
        db.close()


def _fetch_news(symbol: str) -> list[str]:
    try:
        import akshare as ak
        code = symbol.split(".")[0]
        df = ak.stock_news_em(symbol=code)
        if df is None or len(df) == 0:
            return []
        title_col = "新闻标题" if "新闻标题" in df.columns else df.columns[0]
        titles = df[title_col].tolist()[:NEWS_COUNT]
        return [str(t) for t in titles]
    except Exception as e:
        logger.debug("News fetch failed for %s: %s", symbol, e)
        return []


def _coerce_json_object(raw: str) -> dict:
    text_value = (raw or "").strip()
    if text_value.startswith("```"):
        text_value = text_value.strip("`").strip()
        if text_value.lower().startswith("json"):
            text_value = text_value[4:].strip()
    if "</think>" in text_value:
        text_value = text_value.split("</think>", 1)[1].strip()
    try:
        value = json.loads(text_value)
        return value if isinstance(value, dict) else {}
    except Exception:
        start = text_value.find("{")
        end = text_value.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text_value[start:end + 1])
                return value if isinstance(value, dict) else {}
            except Exception:
                pass
        return {"summary": text_value}


def _direction_from_payload(payload: dict) -> str:
    direction = str(payload.get("direction") or payload.get("impact_direction") or "").lower()
    if direction in {"positive", "bullish", "看多", "利好"}:
        return "positive"
    if direction in {"negative", "bearish", "看空", "利空"}:
        return "negative"
    return "neutral"


def _impact_score(direction: str, relevance: str, confidence: str) -> int:
    sign = 1 if direction == "positive" else -1 if direction == "negative" else 0
    relevance_weight = {"high": 3, "medium": 2, "low": 1}.get(relevance, 1)
    confidence_weight = {"high": 2, "medium": 1, "low": 0}.get(confidence, 1)
    return sign * (relevance_weight + confidence_weight)


def _keyword_fallback_payload(news_titles: list[str], reason: str) -> dict:
    text_value = " ".join(news_titles)
    positive_keywords = ["增持", "回购", "中标", "订单", "增长", "预增", "扭亏", "合作", "收购", "扩产", "分红"]
    negative_keywords = ["减持", "亏损", "预亏", "下滑", "处罚", "立案", "诉讼", "终止", "风险", "监管", "警示", "解禁"]
    positive_hits = sum(1 for word in positive_keywords if word in text_value)
    negative_hits = sum(1 for word in negative_keywords if word in text_value)
    if positive_hits > negative_hits:
        direction = "positive"
        summary = "公开标题偏利好，AI模型不可用时按关键词降级评估，需结合开盘资金面复核。"
    elif negative_hits > positive_hits:
        direction = "negative"
        summary = "公开标题偏利空，AI模型不可用时按关键词降级评估，需警惕开盘承压。"
    else:
        direction = "neutral"
        summary = "公开标题未见强方向信号，AI模型不可用时按关键词降级评估，观察开盘确认。"
    hits = positive_hits + negative_hits
    relevance = "medium" if hits >= 2 else "low"
    return {
        "direction": direction,
        "relevance": relevance,
        "confidence": "low",
        "impact_horizon": "short_term",
        "price_reflected": "unknown",
        "summary": summary,
        "watch_points": ["开盘竞价强弱", "首小时成交额变化", "标题对应公告或新闻正文真实性"],
        "analysis_mode": "keyword_fallback",
        "fallback_reason": reason,
    }


def _prefilter_model() -> dict | None:
    api_key = (NEWS_PREFILTER_API_KEY or "").strip()
    if not NEWS_PREFILTER_ENABLED or not api_key:
        return None
    return {
        "name": NEWS_PREFILTER_MODEL,
        "provider": "openai",
        "model_id": NEWS_PREFILTER_MODEL,
        "api_key": api_key,
        "api_base_url": NEWS_PREFILTER_BASE_URL,
        "config": {
            "temperature": 0.1,
            "max_tokens": 160,
            "timeout": NEWS_PREFILTER_TIMEOUT,
            "max_retries": NEWS_PREFILTER_MAX_RETRIES,
        },
    }


async def _prefilter_news(stock_name: str, symbol: str, news_titles: list[str]) -> dict | None:
    model = _prefilter_model()
    if not model:
        return None
    news_text = "\n".join(f"- {title}" for title in news_titles[:NEWS_COUNT])
    try:
        result = await ai_client.analyze(
            provider=model["provider"],
            model_id=model["model_id"],
            api_key=model["api_key"],
            api_base_url=model["api_base_url"],
            config=model["config"],
            system_prompt=(
                "你是A股新闻预筛 Agent。只根据标题做粗筛，不编造事实。"
                "输出严格 JSON，不要 Markdown。"
            ),
            user_prompt=(
                f"股票：{stock_name}（{symbol}）\n"
                f"新闻标题：\n{news_text}\n\n"
                "请预筛这些标题。输出 JSON 字段："
                "direction(positive/negative/neutral), key_events(数组最多3条), "
                "risk_flags(数组最多3条), needs_strong_review(true/false), summary(不超过40字)。"
            ),
        )
        raw = (result.get("content") or "").strip()
        if not raw:
            return None
        payload = _coerce_json_object(raw)
        payload["model_name"] = model["name"]
        return payload
    except Exception as exc:
        logger.warning("News prefilter failed for %s with %s: %s", symbol, model["name"], str(exc)[:160])
        return None


def _build_news_impact_evidence(payload: dict, news_titles: list[str], signals: dict | None = None) -> dict:
    direction = _direction_from_payload(payload)
    relevance = str(payload.get("relevance") or "medium").lower()
    confidence = str(payload.get("confidence") or "medium").lower()
    summary = str(payload.get("summary") or payload.get("reason") or "资讯影响待复核").strip()
    value: dict = {
        "direction": direction,
        "relevance": relevance,
        "confidence": confidence,
        "impact_horizon": payload.get("impact_horizon") or "short_term",
        "price_reflected": payload.get("price_reflected") or "unknown",
        "summary": summary,
        "watch_points": payload.get("watch_points") or [],
        "top_news": news_titles[:NEWS_COUNT],
        "analysis_mode": payload.get("analysis_mode") or "ai_agent",
        "model_name": payload.get("model_name"),
        "prefilter": payload.get("prefilter"),
        "fallback_reason": payload.get("fallback_reason"),
        "external_search_used": payload.get("external_search_used"),
        "external_search_notes": payload.get("external_search_notes"),
        # 新增多维字段
        "catalyst_type": payload.get("catalyst_type") or (signals.get("catalyst_type") if signals else None),
        "catalyst_strength": payload.get("catalyst_strength"),
        "sector_sentiment": payload.get("sector_sentiment"),
        "macro_alignment": payload.get("macro_alignment"),
        "has_announcement": bool(signals and signals.get("high_impact_announcements")),
        "has_industry_signal": bool(signals and signals.get("industry_events", {}).get("themes")),
        "has_telegraph": bool(signals and signals.get("telegraph_highlights")),
    }
    return {
        "factor": NEWS_IMPACT_FACTOR,
        "dimension": "news_impact",
        "label": "资讯影响 Agent",
        "value": value,
        "source": "nightly_news_impact_agent",
        "freshness": "overnight",
        "confidence": confidence,
        "direction": direction,
        "impact": _impact_score(direction, relevance, confidence),
        "explanation": summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _update_evidence_chain(obs_id: int, evidence_item: dict) -> None:
    db = SessionLocal()
    try:
        row = db.query(ResearchObservation).filter(ResearchObservation.id == obs_id).first()
        if not row:
            return
        chain = row.evidence_chain_json or []
        if isinstance(chain, str):
            chain = json.loads(chain or "[]")
        chain = [
            item for item in chain
            if not (isinstance(item, dict) and item.get("factor") == NEWS_IMPACT_FACTOR)
        ]
        chain.append(evidence_item)
        row.evidence_chain_json = chain
        db.commit()
    except Exception as e:
        logger.error("Failed to update evidence chain for obs %d: %s", obs_id, e)
        db.rollback()
    finally:
        db.close()


async def _refresh_tier_and_action(trade_date: str) -> None:
    db = SessionLocal()
    try:
        target_day = date.fromisoformat(trade_date)
        start = datetime.combine(target_day, time.min)
        end = start + timedelta(days=1)
        rows = (
            db.query(ResearchObservation)
            .filter(ResearchObservation.snapshot_date >= start)
            .filter(ResearchObservation.snapshot_date < end)
            .filter(ResearchObservation.strategy_id != "snapshot_fast_recovery")
            .all()
        )
        if not rows:
            return

        recs: list[dict] = []
        for row in rows:
            factor_snapshot = row.factor_snapshot_json or {}
            if isinstance(factor_snapshot, str):
                try:
                    factor_snapshot = json.loads(factor_snapshot)
                except Exception:
                    factor_snapshot = {}
            recs.append(
                {
                    "_row_id": row.id,
                    "symbol": row.symbol,
                    "name": "",
                    "score": row.score,
                    "price": row.close_price,
                    "change_pct": None,
                    "score_breakdown": row.score_breakdown_json or [],
                    "evidence_chain": row.evidence_chain_json or [],
                    "veto_result": row.veto_result_json or {},
                    "bull_case": (row.debate_json or {}).get("bull_case", []) if isinstance(row.debate_json, dict) else [],
                    "bear_case": (row.debate_json or {}).get("bear_case", []) if isinstance(row.debate_json, dict) else [],
                    "falsification": (row.debate_json or {}).get("falsification", []) if isinstance(row.debate_json, dict) else [],
                    "capital_flow_status": factor_snapshot.get("capital_flow_status"),
                    "chase_high_penalty": factor_snapshot.get("chase_high_penalty"),
                }
            )

        recs = classify_tiers(recs)
        recs = await generate_observation_actions(recs, use_ai=False)
        by_id = {rec["_row_id"]: rec for rec in recs}

        for row in rows:
            rec = by_id.get(row.id)
            if not rec:
                continue
            factor_snapshot = row.factor_snapshot_json or {}
            if isinstance(factor_snapshot, str):
                try:
                    factor_snapshot = json.loads(factor_snapshot)
                except Exception:
                    factor_snapshot = {}
            factor_snapshot.update(
                {
                    "tier": rec.get("tier"),
                    "tier_reason": rec.get("tier_reason"),
                    "resonance_count": rec.get("resonance_count"),
                    "priority_score": rec.get("priority_score"),
                    "observation_action": rec.get("observation_action"),
                    "trigger_condition": rec.get("trigger_condition"),
                    "invalidation_condition": rec.get("invalidation_condition"),
                    "risk_warning": rec.get("risk_warning"),
                    "chase_high_penalty": rec.get("chase_high_penalty"),
                }
            )
            row.factor_snapshot_json = factor_snapshot
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Failed to refresh tier/action after news enrichment: %s", exc)
    finally:
        db.close()


async def _invalidate_recommendation_cache() -> None:
    try:
        from backend.shared.cache import get_cache_manager

        cache = await get_cache_manager()
        await cache.invalidate_pattern("stock:daily_recommendations:*")
    except Exception as exc:
        logger.debug("Failed to invalidate recommendation cache after news enrichment: %s", exc)


async def _analyze_with_model_pool(
    *,
    models: list[dict],
    system_prompt: str,
    user_prompt: str,
) -> tuple[dict | None, str | None, list[str]]:
    errors: list[str] = []
    for model in models:
        name = str(model.get("name") or model.get("model_id") or "unknown")
        try:
            result = await ai_client.analyze(
                provider=model["provider"],
                model_id=model["model_id"],
                api_key=model["api_key"],
                api_base_url=model["api_base_url"],
                config=model["config"],
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            summary = result.get("content", "").strip() if result else ""
            if not summary:
                raise RuntimeError("empty model response")
            payload = _coerce_json_object(summary)
            payload.setdefault("analysis_mode", "ai_agent")
            payload["model_name"] = name
            return payload, name, errors
        except Exception as exc:
            message = str(exc)
            logger.warning("News enrich model failed, trying next model: %s (%s)", name, message[:160])
            errors.append(f"{name}: {message[:180]}")
    return None, None, errors


async def enrich_with_news(trade_date: Optional[str] = None) -> dict:
    """
    为观察池个股收集新闻并做结构化资讯影响分析。
    返回 {"enriched": int, "skipped": int, "errors": int}
    """
    if trade_date is None:
        trade_date = latest_observation_trade_date()
    if not trade_date:
        return {"enriched": 0, "skipped": 0, "errors": 0, "reason": "no_observations"}

    models = _fetch_candidate_models()
    if not models:
        logger.warning("News enrich model '%s' not found or inactive, using keyword fallback", NEWS_ENRICH_MODEL_NAME)
    else:
        logger.info(
            "News enrich model pool: %s",
            ", ".join(f"{model.get('name')}({model.get('model_id')})" for model in models),
        )

    observations = _fetch_today_observations(trade_date)
    if not observations:
        return {"trade_date": trade_date, "enriched": 0, "skipped": 0, "errors": 0, "reason": "no_observations"}

    enriched = skipped = errors = fallbacks = 0
    failed_model_names: set[str] = set()
    model_usage: dict[str, int] = {}

    for obs in observations:
        symbol = obs["symbol"]
        stock_name = _fetch_stock_name(symbol)

        # 聚合多维资讯信号（个股新闻 + 公告 + 行业事件 + 财联社电报）
        try:
            signals = await asyncio.wait_for(
                aggregate_news_signals(symbol, stock_name),
                timeout=15,
            )
        except Exception as exc:
            logger.warning("Signal aggregation failed for %s: %s", symbol, exc)
            signals = {"stock_news_titles": [], "has_catalyst": False, "catalyst_type": "none",
                       "announcements": [], "high_impact_announcements": [],
                       "industry_events": {}, "telegraph_highlights": []}

        news_titles = signals.get("stock_news_titles", [])

        if not news_titles and not signals.get("high_impact_announcements") and not signals.get("industry_events", {}).get("themes"):
            skipped += 1
            continue

        # 构建多维资讯上下文
        news_context = build_enriched_news_context(signals)
        prefilter = await _prefilter_news(stock_name, symbol, news_titles) if news_titles else None
        prefilter_text = ""
        if prefilter:
            prefilter_text = (
                "\n\n轻量模型预筛结果（仅供参考，最终判断以你为准）：\n"
                f"{json.dumps(prefilter, ensure_ascii=False)}"
            )
        system_prompt = (
            "你是A股资讯影响分析 Agent。根据给定的多维资讯（个股新闻、公司公告、行业/政策事件、财联社电报）"
            "综合判断对该股的影响。若当前模型具备实时搜索或 X 平台资讯能力，可补充检索全球公开资讯与 X 上高相关信号；"
            "不要编造事实，无法核实的传闻只能作为低置信度观察点。输出严格 JSON，不要 Markdown。"
        )
        user_prompt = (
            f"股票：{stock_name}（{symbol}）\n\n"
            f"{news_context}{prefilter_text}\n\n"
            "请综合以上多维资讯，判断对该股进入观察池的影响。输出 JSON，字段：\n"
            "direction(positive/negative/neutral), relevance(high/medium/low), "
            "confidence(high/medium/low), impact_horizon(short_term/medium_term/long_term), "
            "price_reflected(unreflected/partially/mostly/unknown), summary(不超过60字), "
            "watch_points(数组，最多3条), "
            "catalyst_type(announcement/industry_policy/news_positive/news_negative/market_signal/none), "
            "catalyst_strength(high/medium/low/none), "
            "sector_sentiment(positive/negative/neutral/unknown), "
            "macro_alignment(aligned/contradicted/neutral), "
            "external_search_used(true/false), external_search_notes(不超过40字)。"
        )

        payload, used_model, model_errors = await _analyze_with_model_pool(
            models=models,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        for error in model_errors:
            failed_model_names.add(error.split(":", 1)[0])
        if used_model:
            model_usage[used_model] = model_usage.get(used_model, 0) + 1
        if payload and prefilter:
            payload["prefilter"] = prefilter
        if model_errors:
            errors += len(model_errors)
        if not payload:
            fallback_reason = "; ".join(model_errors[-2:]) if model_errors else "ai_model_unavailable"
            payload = _keyword_fallback_payload(news_titles, fallback_reason[:240])
            fallbacks += 1

        if payload:
            evidence_item = _build_news_impact_evidence(payload, news_titles, signals)
            _update_evidence_chain(obs["id"], evidence_item)
            enriched += 1
            logger.info("News impact enriched %s: %s", symbol, evidence_item.get("explanation", "")[:60])

        await asyncio.sleep(1)  # 避免速率限制

    if enriched:
        await _invalidate_recommendation_cache()
        await _refresh_tier_and_action(trade_date)

    logger.info(
        "News enrichment done: trade_date=%s enriched=%d skipped=%d errors=%d fallbacks=%d model_usage=%s",
        trade_date,
        enriched,
        skipped,
        errors,
        fallbacks,
        model_usage,
    )
    return {
        "trade_date": trade_date,
        "enriched": enriched,
        "skipped": skipped,
        "errors": errors,
        "fallbacks": fallbacks,
        "model_usage": model_usage,
        "failed_models": sorted(failed_model_names),
    }
