"""推荐摘要生成器 — pipeline 完成后为每只推荐股生成一句话自然语言总结"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date
from typing import Optional

from sqlalchemy import text

from backend.shared.auth import decrypt_api_key
from backend.shared.database import SessionLocal
from backend.services.analysis_service.engine.ai_client import ai_client

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "kimi-k2.5"
SECONDARY_MODEL_ID = "glm-5"
SUMMARY_MODEL_NAME = os.getenv("SUMMARY_MODEL_NAME", DEFAULT_MODEL_NAME)
GLM_MODEL_ID = os.getenv("GLM_MODEL_ID", SECONDARY_MODEL_ID)
GLM_BASE_URL = os.getenv("GLM_BASE_URL") or os.getenv("NEWS_PREFILTER_BASE_URL")
GLM_API_KEY = os.getenv("GLM_API_KEY") or os.getenv("NEWS_PREFILTER_API_KEY")
GLM_REQUEST_TIMEOUT = float(os.getenv("GLM_REQUEST_TIMEOUT", "45"))


def _glm_env_model() -> dict | None:
    api_key = (GLM_API_KEY or "").strip()
    if not api_key:
        return None
    return {
        "name": SECONDARY_MODEL_ID,
        "provider": "openai",
        "model_id": GLM_MODEL_ID,
        "api_base_url": GLM_BASE_URL,
        "api_key": api_key,
        "config": {"temperature": 0.2, "max_tokens": 800, "timeout": GLM_REQUEST_TIMEOUT, "max_retries": 0},
    }


def _build_virtual_model(model: dict, *, name: str, model_id: str) -> dict:
    virtual = dict(model)
    virtual["name"] = name
    virtual["model_id"] = model_id
    return virtual


def _load_candidate_models() -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT name, provider, model_id, api_base_url, api_key_encrypted, config
                FROM ai_models
                WHERE is_active = true
                ORDER BY sort_order, id
            """)
        ).fetchall()
        models = []
        for row in rows:
            models.append(
                {
                    "name": row[0],
                    "provider": row[1],
                    "model_id": row[2],
                    "api_base_url": row[3],
                    "api_key": decrypt_api_key(row[4]),
                    "config": row[5] or {},
                }
            )
        preferred = next((model for model in models if model.get("name") == SUMMARY_MODEL_NAME), None)
        has_glm = any(model.get("name") == SECONDARY_MODEL_ID or model.get("model_id") == GLM_MODEL_ID for model in models)
        if not has_glm:
            glm_model = _glm_env_model()
            if not glm_model and preferred:
                glm_model = _build_virtual_model(preferred, name=SECONDARY_MODEL_ID, model_id=SECONDARY_MODEL_ID)
            if glm_model:
                models.insert(1 if models else 0, glm_model)
        return models
    finally:
        db.close()


def _build_prompt(rec: dict) -> str:
    name = rec.get("name") or rec["symbol"]
    symbol = rec["symbol"]
    score = rec.get("final_score") or rec.get("score", 0)
    change_pct = rec.get("change_pct")
    industry = rec.get("industry_name") or rec.get("sector") or "未知行业"
    industry_health = rec.get("industry_health_score")
    bull_cases = rec.get("bull_case", [])
    bear_cases = rec.get("bear_case", [])

    bull_text = "；".join(
        b.get("argument", "") for b in bull_cases[:2] if b.get("argument")
    )
    bear_text = "；".join(
        b.get("argument", "") for b in bear_cases[:1] if b.get("argument")
    )

    change_str = f"今日{'上涨' if (change_pct or 0) >= 0 else '下跌'}{abs(change_pct or 0):.1f}%，" if change_pct is not None else ""
    industry_str = f"所属行业{industry}（健康度{industry_health}分）" if industry_health else f"所属行业{industry}"

    prompt = (
        f"股票：{name}（{symbol}），综合评分{score:.1f}分，{change_str}{industry_str}。\n"
        f"看多依据：{bull_text or '暂无'}。\n"
        f"主要风险：{bear_text or '暂无'}。\n\n"
        f"请用一段话（60字以内）为普通散户总结该股票的投资信号，"
        f"语言简洁直白，不要出现专业术语，不要加免责声明，直接给出核心判断。"
    )
    return prompt


async def _generate_with_model_pool(
    *,
    models: list[dict],
    failed_model_names: set[str],
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, str | None, list[str]]:
    errors: list[str] = []
    for model in models:
        name = str(model.get("name") or model.get("model_id") or "unknown")
        if name in failed_model_names:
            continue
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
            summary = (result.get("content") or "").strip()
            if not summary:
                raise RuntimeError("empty model response")
            return summary, name, errors
        except Exception as exc:
            message = str(exc)
            logger.warning("Summary model failed, trying next model: %s (%s)", name, message[:160])
            failed_model_names.add(name)
            errors.append(f"{name}: {message[:180]}")
    return "", None, errors


async def generate_summaries(
    recommendations: list[dict],
    trade_date: Optional[str] = None,
) -> dict:
    """
    为推荐股列表生成自然语言摘要，写入 research_observations.summary_text。
    返回 {"generated": int, "skipped": int, "errors": int}
    """
    if not recommendations:
        return {"generated": 0, "skipped": 0, "errors": 0}

    models = _load_candidate_models()
    if not models:
        logger.warning("Summary model '%s' not found, skipping summary generation", SUMMARY_MODEL_NAME)
        return {"generated": 0, "skipped": len(recommendations), "errors": 0, "reason": "no_model"}
    logger.info(
        "Summary model pool: %s",
        ", ".join(f"{model.get('name')}({model.get('model_id')})" for model in models),
    )

    if trade_date is None:
        trade_date = date.today().isoformat()

    generated = skipped = errors = 0
    failed_model_names: set[str] = set()
    model_usage: dict[str, int] = {}

    for rec in recommendations:
        symbol = rec.get("symbol")
        if not symbol:
            skipped += 1
            continue

        try:
            user_prompt = _build_prompt(rec)
            summary, used_model, model_errors = await _generate_with_model_pool(
                models=models,
                failed_model_names=failed_model_names,
                system_prompt="你是一位专业的A股投资分析师，用简洁中文为普通投资者解读股票信号。",
                user_prompt=user_prompt,
            )
            errors += len(model_errors)
            if used_model:
                model_usage[used_model] = model_usage.get(used_model, 0) + 1
            if not summary:
                skipped += 1
                continue

            _save_summary(symbol, trade_date, summary)
            generated += 1
            logger.debug("Summary generated for %s: %s", symbol, summary[:40])

        except Exception as e:
            logger.error("Summary generation failed for %s: %s", symbol, e)
            errors += 1

        await asyncio.sleep(0.5)

    logger.info(
        "Summary generation done: generated=%d, skipped=%d, errors=%d model_usage=%s",
        generated, skipped, errors, model_usage,
    )
    return {
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
        "model_usage": model_usage,
        "failed_models": sorted(failed_model_names),
    }


def _save_summary(symbol: str, trade_date: str, summary: str) -> None:
    db = SessionLocal()
    try:
        db.execute(
            text("""
                UPDATE research_observations
                SET summary_text = :summary
                WHERE symbol = :symbol AND snapshot_date::date = :td
            """),
            {"summary": summary, "symbol": symbol, "td": trade_date},
        )
        db.commit()
    except Exception as e:
        logger.error("Failed to save summary for %s: %s", symbol, e)
        db.rollback()
    finally:
        db.close()
