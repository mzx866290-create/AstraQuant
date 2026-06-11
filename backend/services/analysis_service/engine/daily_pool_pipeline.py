"""每日观察池全流程编排 v3：采集 → 粗筛 → 行业过滤 → 硬否决 → 乘法评分 → 精加工 → 存DB"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timezone
from backend.shared.trading_calendar import now_cn

from backend.services.analysis_service.engine.daily_snapshot_collector import (
    cleanup_market_redundancy,
    collect_market_snapshot,
)
from backend.services.analysis_service.engine.anomaly_screener import screen_anomalies
from backend.services.analysis_service.engine.anomaly_scorer import score_anomalies
from backend.services.analysis_service.engine.market_regime import detect_market_regime
from backend.services.analysis_service.engine.risk_veto import evaluate_risk_veto
from backend.services.analysis_service.engine.evidence_chain import build_evidence_chain
from backend.services.analysis_service.engine.debate_engine import build_debate_view
from backend.services.analysis_service.engine.review_tracker import save_observation_snapshots
from backend.services.analysis_service.engine.capital_flow_enhancer import (
    apply_capital_flow_risk_light,
    build_capital_flow_score_item,
    enhance_candidates_with_capital_flow,
)
from backend.services.analysis_service.engine.industry_collector import collect_industry_snapshot
from backend.services.analysis_service.engine.industry_scorer import score_all_industries
from backend.services.analysis_service.engine.industry_filter import filter_by_industry
from backend.services.analysis_service.engine.hard_veto import batch_hard_veto
from backend.services.analysis_service.engine.multiplier_scorer import apply_multiplier_scoring
from backend.services.analysis_service.engine.chase_high_penalty import apply_chase_high_penalty
from backend.services.analysis_service.engine.tier_classifier import classify_tiers
from backend.services.analysis_service.engine.observation_action_generator import generate_observation_actions
from backend.services.analysis_service.engine.observation_pool_optimizer import (
    fetch_review_feedback_for_symbols,
    optimize_observation_pool,
)
from backend.services.analysis_service.engine.pool_summary_generator import generate_pool_summary
from backend.shared.database import SessionLocal
from backend.shared.models import PipelineRunLog, RejectionLog
from backend.services.analysis_service.engine.pipeline_tracker import PipelineContext, StepResult
from backend.services.analysis_service.engine.pipeline_persistence import (
    create_execution_record,
    complete_execution_record,
    save_traces,
)

logger = logging.getLogger(__name__)


def _track_step(ctx: PipelineContext, step_name: str,
                before: list, after: list, duration_ms: int = 0,
                *, rejected: list | None = None, reason_fn=None):
    """Record step stats and per-stock traces into PipelineContext.

    When ``rejected`` is provided (e.g. hard_veto), only traces from the
    rejected list are written — the before/after diff is skipped to avoid
    duplicate entries for the same stock.
    """
    ctx.add_step_stats(step_name, len(before), len(after), duration_ms)
    if rejected is not None:
        for item in rejected:
            veto = item.get("hard_veto") or {}
            ctx.add_trace(step_name, StepResult(
                stock_code=item.get("symbol", ""),
                stock_name=item.get("name", ""),
                action="filtered",
                reason=veto.get("reason", "hard_veto")[:500],
                detail={"vetoed_by": veto.get("vetoed_by")},
            ))
    else:
        after_symbols = {item.get("symbol") for item in after}
        for item in before:
            sym = item.get("symbol", "")
            if sym in after_symbols:
                continue
            reason = reason_fn(item) if reason_fn else "filtered"
            ctx.add_trace(step_name, StepResult(
                stock_code=sym,
                stock_name=item.get("name", ""),
                action="filtered",
                reason=reason[:500] if reason else "",
            ))

STRATEGY_ID = "trend_momentum"


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 200) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, min_value), max_value)


def _env_float(name: str, default: float, *, min_value: float = 0.0, max_value: float = 100.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, min_value), max_value)


def _top_n() -> int:
    return _env_int("DAILY_POOL_TOP_N", 30, min_value=5, max_value=80)


def _selection_window_size(total: int) -> int:
    return _env_int("DAILY_POOL_SELECTION_WINDOW", total * 4, min_value=total, max_value=500)


def _bucket_caps(total: int) -> dict[str, int]:
    if total <= 0:
        return {}
    trend_cap = _env_int("DAILY_POOL_TREND_BUCKET_CAP", max(1, int(total * 0.55)), min_value=1, max_value=total)
    pullback_cap = _env_int("DAILY_POOL_PULLBACK_BUCKET_CAP", max(1, int(total * 0.30)), min_value=1, max_value=total)
    reversal_cap = _env_int("DAILY_POOL_REVERSAL_BUCKET_CAP", max(1, int(total * 0.15)), min_value=1, max_value=total)
    caps = {
        "trend_strength": trend_cap,
        "pullback_support": pullback_cap,
        "oversold_reversal": reversal_cap,
    }
    cap_sum = sum(caps.values())
    if cap_sum > total:
        # 按比例归一化，保证配比真实生效；余数按 cap 大小降序分配
        scaled = {k: max(1, int(v * total / cap_sum)) for k, v in caps.items()}
        remainder = total - sum(scaled.values())
        for k in sorted(caps, key=caps.get, reverse=True):
            if remainder <= 0:
                break
            scaled[k] += 1
            remainder -= 1
        caps = scaled
    return caps


def _rebalance_by_observation_bucket(candidates: list[dict], total: int) -> tuple[list[dict], dict]:
    if not candidates:
        return [], {"status": "no_candidates"}
    caps = _bucket_caps(total)
    selected: list[dict] = []
    overflow: list[dict] = []
    counts: dict[str, int] = {}
    for item in candidates:
        bucket = str(item.get("observation_bucket") or "trend_strength")
        count = counts.get(bucket, 0)
        if count < caps.get(bucket, total):
            selected.append(item)
            counts[bucket] = count + 1
        else:
            overflow.append(item)
    backfilled = max(0, min(len(selected) + len(overflow), total) - len(selected))
    selected.extend(overflow)
    return selected[:total], {
        "status": "ok",
        "caps": caps,
        "counts": counts,
        "backfilled_from_overflow": backfilled,
        "before": len(candidates),
        "after": min(len(selected), total),
    }


def _pipeline_candidate_cap() -> int:
    return _env_int("DAILY_POOL_CANDIDATE_CAP", 800, min_value=50, max_value=5000)


def _stage_timeout(name: str, default: int) -> int:
    return _env_int(f"DAILY_POOL_{name.upper()}_TIMEOUT_SECONDS", default, min_value=5, max_value=600)


def _strategy_id() -> str:
    return os.getenv("DAILY_POOL_STRATEGY_ID", STRATEGY_ID).strip() or STRATEGY_ID


def _strategy_name(strategy_id: str) -> str:
    names = {
        "trend_momentum": "趋势动量",
        "growth_momentum": "成长动量",
        "retail_small": "小而美观察",
        "value_quality": "价值质量",
        "reversal_watch": "反转观察",
    }
    return names.get(strategy_id, strategy_id)


def _build_stock_data_from_snapshot(item: dict) -> dict:
    """将快照数据转换为 risk_veto / evidence_chain / debate_engine 所需的 stock_data 格式"""
    close = item.get("close") or 0
    return {
        "symbol": item.get("symbol", ""),
        "name": item.get("name", ""),
        "price": close,
        "change_pct": item.get("change_pct"),
        "kline_data": [{
            "close": close,
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "volume": item.get("volume"),
        }],
        "financial": {
            "operating_cf": None,
            "net_profit_yoy": None,
            "revenue_yoy": None,
        },
        "readiness": {
            "data_grade": {
                "grade": "B",
                "label": "数据部分完整",
                "analysis_scope": "可以分析行情和技术面；基本面、公告、个股新闻或行业事件只能基于已有数据谨慎判断。",
            },
        },
        "quote": {
            "turnover_rate": item.get("turnover_rate"),
            "total_mv": item.get("total_mv"),
            "circ_mv": item.get("circ_mv"),
            "volume": item.get("volume"),
        },
        "data_quality": {
            "quote": {
                "source": "akshare-snapshot",
                "freshness": "latest_trading_day",
                "confidence": "medium",
            },
            "kline": {
                "source": "akshare-snapshot",
                "freshness": "latest_trading_day",
                "confidence": "medium",
            },
            "valuation": {
                "source": "",
                "freshness": "missing",
                "confidence": "low",
            },
            "financial": {
                "source": "",
                "freshness": "missing",
                "confidence": "low",
            },
            "news": {
                "source": "",
                "freshness": "missing",
                "confidence": "low",
            },
            "industry_events": {
                "source": "",
                "freshness": "missing",
                "confidence": "low",
            },
            "capital_flow": {
                "source": "akshare",
                "freshness": "latest_trading_day",
                "confidence": "medium",
            },
        },
    }


def _build_risk_lights_from_snapshot(item: dict) -> dict:
    """从快照数据构建简化版 risk_lights"""
    lights = {}
    name = item.get("name") or ""
    if "ST" in name.upper():
        lights["st_stock"] = {"level": "red", "type": "st", "message": "ST股票"}
    if (item.get("volume") or 0) <= 0:
        lights["suspended"] = {"level": "red", "type": "suspended", "message": "停牌"}
    change_pct = item.get("change_pct") or 0
    if change_pct <= -9.9:
        lights["limit_down"] = {"level": "red", "type": "limit_down", "message": "跌停"}
    return lights


def _build_score_breakdown_from_anomaly(item: dict) -> list[dict]:
    """将趋势评分转换为 score_breakdown 格式"""
    breakdown = item.get("score_breakdown") or {}
    result = []
    mapping = {
        "trend_quality": ("趋势质量", "trend"),
        "safety_margin": ("安全边际", "safety"),
        "volume_price": ("量价配合", "volume_price"),
        "technical_position": ("技术位置", "technical"),
        "market_attention": ("市场关注", "attention"),
    }
    for key, (label, factor_key) in mapping.items():
        value = breakdown.get(key, 0)
        result.append({
            "key": factor_key,
            "delta": value,
            "label": label,
            "message": f"{label}: {value}分",
        })
    return result


async def run_daily_pool_pipeline(trade_date: str | None = None) -> dict:
    """
    执行每日观察池全流程。

    1. 采集全市场快照 (~15s)
    2. 趋势筛选 (~100ms)
    3. 评分排序 (~200ms)
    4. 对 top 20：risk_veto + evidence_chain + debate (~5s)
    5. 存入 research_observations
    6. 清理过期快照

    返回 pipeline 执行结果摘要。
    """
    if not trade_date:
        trade_date = now_cn().strftime("%Y-%m-%d")

    logger.info(f"=== Daily pool pipeline started: {trade_date} ===")
    result = {
        "trade_date": trade_date,
        "status": "ok",
        "steps": {},
    }

    run_log = await asyncio.to_thread(_create_run_log, trade_date)

    # 创建管道追踪上下文
    active_strategy_id = _strategy_id()
    ctx = PipelineContext(
        execution_date=trade_date,
        trigger_type="scheduled",
        strategy_id=active_strategy_id,
        market="ALL",
    )
    create_execution_record(ctx)

    import time as _time

    try:
        _t0 = _time.monotonic()
        collect_result = await collect_market_snapshot(trade_date)
        ctx.add_step_stats("collect", 0, collect_result.get("collected", 0),
                           int((_time.monotonic() - _t0) * 1000))
        result["steps"]["collect"] = collect_result
        logger.info(f"Step 1 done: collected {collect_result['collected']} snapshots")
        run_log["total_collected"] = collect_result.get("collected", 0)
    except Exception as e:
        logger.error(f"Pipeline failed at collection: {e}")
        result["status"] = "error"
        result["error"] = f"采集失败: {e}"
        await asyncio.to_thread(_finish_run_log, run_log, "failed", str(e))
        complete_execution_record(ctx, status="failed", error=str(e))
        return result

    # Step 1.5: 行业数据采集（非阻塞，失败不影响主流程，超时60s）
    try:
        industry_result = await asyncio.wait_for(
            collect_industry_snapshot(trade_date), timeout=60
        )
        result["steps"]["industry_collect"] = industry_result
        logger.info("Step 1.5 done: industry snapshot %s", industry_result)
        run_log["industries_collected"] = industry_result.get("collected", 0)
        if industry_result.get("collected", 0) > 0:
            industry_score_result = score_all_industries(trade_date)
            result["steps"]["industry_score"] = industry_score_result
            logger.info("Step 1.5b done: industry health scores %s", industry_score_result)
    except asyncio.TimeoutError:
        logger.warning("Industry collection timed out (60s), skipping")
        result["steps"]["industry_collect"] = {"status": "timeout", "error": "exceeded 60s"}
    except Exception as e:
        logger.warning("Industry collection failed (non-blocking): %s", e)
        result["steps"]["industry_collect"] = {"status": "error_non_blocking", "error": str(e)}

    try:
        _t0 = _time.monotonic()
        candidates = screen_anomalies(trade_date)
        _screen_ms = int((_time.monotonic() - _t0) * 1000)
        ctx.add_step_stats("screen_anomalies", run_log.get("total_collected", 0),
                           len(candidates), _screen_ms)
        for c in candidates:
            ctx.add_trace("screen_anomalies", StepResult(
                stock_code=c.get("symbol", ""),
                stock_name=c.get("name", ""),
                action="passed",
                reason=c.get("anomaly_type", "trend_candidate"),
            ))
        result["steps"]["screen"] = {"candidates": len(candidates)}
        logger.info(f"Step 2 done: {len(candidates)} trend candidates")
        run_log["total_screened"] = len(candidates)
        run_log["after_screening"] = len(candidates)
    except Exception as e:
        logger.error(f"Pipeline failed at screening: {e}")
        result["status"] = "error"
        result["error"] = f"筛选失败: {e}"
        await asyncio.to_thread(_finish_run_log, run_log, "failed", str(e))
        complete_execution_record(ctx, status="failed", error=str(e),
                                  total_input=run_log.get("total_collected", 0))
        return result

    if not candidates:
        result["status"] = "no_data"
        result["steps"]["screen"]["note"] = "无趋势候选股（可能非交易日或数据不足）"
        await asyncio.to_thread(_finish_run_log, run_log, "no_data", None)
        complete_execution_record(ctx, status="no_data", total_output=0,
                                  total_input=run_log.get("total_collected", 0))
        # Clear same-day same-strategy DB observations so stale rows don't resurface
        try:
            save_observation_snapshots(
                snapshot_date=date.fromisoformat(trade_date),
                regime="unknown",
                recommendations=[],
                strategy_id=active_strategy_id,
            )
        except Exception as _db_e:
            logger.warning("Failed to clear DB observations on no_data: %s", _db_e)
        # Clear stale cache so users see "empty" instead of yesterday's pool
        try:
            from backend.shared.cache import get_cache_manager
            _cache = await get_cache_manager()
            await _cache.invalidate_pattern("stock:daily_recommendations:*")
            empty_cache_result = {
                "recommendations": [],
                "count": 0,
                "market": "ALL",
                "status": "ok",
                "pipeline_status": "empty",
                "data_date": trade_date,
                "data_date_note": "current_trading_day",
                "pool_summary": {},
                "active_strategy": {
                    "id": active_strategy_id,
                    "name": _strategy_name(active_strategy_id),
                    "selection_mode": "trend_screening",
                },
                "updated_at": now_cn().isoformat(),
            }
            default_key = "v4:market-ALL:limit-50:max-200:strategy-auto:evidence-1:debate-1:full-0"
            await _cache.set("daily_recommendations", default_key, value=empty_cache_result)
        except Exception as _ce:
            logger.warning("Failed to cache empty pool result: %s", _ce)
        return result

    # Step 2.5: 行业景气度过滤
    try:
        cap = _pipeline_candidate_cap()
        if len(candidates) > cap:
            pre_scored = score_anomalies(candidates, top_n=len(candidates))
            candidates = pre_scored[:cap]
            result["steps"]["candidate_cap"] = {
                "status": "capped",
                "before": len(pre_scored),
                "after": len(candidates),
                "cap": cap,
            }
            logger.info("Step 2.2 done: capped candidates %d -> %d", len(pre_scored), len(candidates))
        else:
            result["steps"]["candidate_cap"] = {
                "status": "skipped",
                "before": len(candidates),
                "after": len(candidates),
                "cap": cap,
            }

        _before_industry = list(candidates)
        _t0 = _time.monotonic()
        candidates, industry_filter_summary = await _run_sync_stage(
            "industry_filter",
            lambda: filter_by_industry(candidates, trade_date),
            timeout_seconds=_stage_timeout("industry_filter", 90),
        )
        _track_step(ctx, "industry_filter", _before_industry, candidates,
                    int((_time.monotonic() - _t0) * 1000),
                    reason_fn=lambda item: (item.get("industry_filter") or {}).get("reasons", ["行业过滤"])[0]
                    if isinstance((item.get("industry_filter") or {}).get("reasons"), list)
                    else "行业景气度不达标")
        result["steps"]["industry_filter"] = industry_filter_summary
        logger.info("Step 2.5 done: industry filter %s", industry_filter_summary)
    except asyncio.TimeoutError:
        logger.warning("Industry filter timed out, continuing without this filter")
        result["steps"]["industry_filter"] = {"status": "timeout_non_blocking"}
    except Exception as e:
        logger.warning("Industry filter failed (non-blocking): %s", e)
        result["steps"]["industry_filter"] = {"status": "error_non_blocking", "error": str(e)}

    # Step 3: 硬否决层（财务恶化 + 龙头联动）
    try:
        _before_veto = list(candidates)
        _t0 = _time.monotonic()
        candidates, hard_rejected, hard_veto_stats = await _run_sync_stage(
            "hard_veto",
            lambda: batch_hard_veto(candidates, trade_date),
            timeout_seconds=_stage_timeout("hard_veto", 90),
        )
        _track_step(ctx, "hard_veto", _before_veto, candidates,
                    int((_time.monotonic() - _t0) * 1000), rejected=hard_rejected)
        result["steps"]["hard_veto"] = hard_veto_stats
        run_log["after_hard_veto"] = hard_veto_stats.get("passed", len(candidates))
        for k, v in hard_veto_stats.get("rejected_by", {}).items():
            run_log[f"vetoed_by_{k}"] = v
        logger.info("Step 3 done: hard veto %s", hard_veto_stats)
    except asyncio.TimeoutError:
        logger.warning("Hard veto timed out, continuing with current candidates")
        result["steps"]["hard_veto"] = {"status": "timeout_non_blocking", "passed": len(candidates)}
        run_log["after_hard_veto"] = len(candidates)
    except Exception as e:
        logger.warning("Hard veto failed (non-blocking): %s", e)
        result["steps"]["hard_veto"] = {"status": "error_non_blocking", "error": str(e)}

    # Step 3.5: 趋势评分（base_score，100分制加法）
    try:
        _t0 = _time.monotonic()
        scored_candidates = score_anomalies(candidates, top_n=len(candidates))
        ctx.add_step_stats("base_score", len(candidates), len(scored_candidates),
                           int((_time.monotonic() - _t0) * 1000))
        result["steps"]["base_score"] = {"scored": len(scored_candidates)}
        logger.info(f"Step 3.5 done: {len(scored_candidates)} base-scored")
        run_log["total_scored"] = len(scored_candidates)
    except Exception as e:
        logger.error(f"Pipeline failed at scoring: {e}")
        result["status"] = "error"
        result["error"] = f"评分失败: {e}"
        await asyncio.to_thread(_finish_run_log, run_log, "failed", str(e))
        complete_execution_record(ctx, status="failed", error=str(e),
                                  total_input=run_log.get("total_collected", 0))
        return result

    # Step 4: 乘法评分（base × industry × fundamental × momentum）
    try:
        selection_window = _selection_window_size(_top_n())
        _t0 = _time.monotonic()
        top_candidates, almost_candidates, mul_summary = await _run_sync_stage(
            "multiplier_score",
            lambda: apply_multiplier_scoring(
                scored_candidates,
                trade_date,
                top_n=selection_window,
                almost_band=_env_float("DAILY_POOL_ALMOST_SCORE_BAND", 8.0, min_value=0, max_value=30),
                almost_min=_env_int("DAILY_POOL_ALMOST_MIN", 10, min_value=0, max_value=200),
                industry_cap=_env_int("DAILY_POOL_MAX_PER_INDUSTRY", 4, min_value=0, max_value=20),
            ),
            timeout_seconds=_stage_timeout("multiplier_score", 90),
        )
        ctx.add_step_stats("multiplier_score", len(scored_candidates), len(top_candidates),
                           int((_time.monotonic() - _t0) * 1000))
        for item in top_candidates:
            ctx.add_trace("multiplier_score", StepResult(
                stock_code=item.get("symbol", ""),
                stock_name=item.get("name", ""),
                action="passed",
                score_before=item.get("base_score"),
                score_after=item.get("final_score"),
                reason=f"industry={item.get('industry_mul', 1.0):.2f} fund={item.get('fundamental_mul', 1.0):.2f} mom={item.get('momentum_mul', 1.0):.2f}",
            ))
        result["steps"]["multiplier_score"] = mul_summary
        run_log["after_scoring"] = len(top_candidates)
        logger.info("Step 4 done: multiplier scoring %s", mul_summary)

        rebalance_candidates = top_candidates + [
            item for item in almost_candidates
            if item.get("symbol") not in {top_item.get("symbol") for top_item in top_candidates}
        ]
        top_candidates, bucket_summary = _rebalance_by_observation_bucket(rebalance_candidates, _top_n())
        bucket_summary["selection_window"] = selection_window
        result["steps"]["bucket_rebalance"] = bucket_summary
        logger.info("Step 4.1 done: observation bucket rebalance %s", bucket_summary)

        # 记录近选名单
        await asyncio.to_thread(_save_almost_list, almost_candidates, trade_date)
    except asyncio.TimeoutError:
        logger.warning("Multiplier scoring timed out, falling back to base score")
        result["steps"]["multiplier_score"] = {"status": "timeout_fallback"}
        scored_candidates.sort(key=lambda x: x.get("anomaly_score", 0), reverse=True)
        top_candidates, bucket_summary = _rebalance_by_observation_bucket(scored_candidates, _top_n())
        almost_candidates = [c for c in scored_candidates if c not in top_candidates]
        result["steps"]["bucket_rebalance"] = bucket_summary
    except Exception as e:
        logger.warning("Multiplier scoring failed, falling back to base score: %s", e)
        result["steps"]["multiplier_score"] = {"status": "error_fallback", "error": str(e)}
        scored_candidates.sort(key=lambda x: x.get("anomaly_score", 0), reverse=True)
        top_candidates, bucket_summary = _rebalance_by_observation_bucket(scored_candidates, _top_n())
        almost_candidates = [c for c in scored_candidates if c not in top_candidates]
        result["steps"]["bucket_rebalance"] = bucket_summary

    try:
        top_candidates, capital_flow_summary = await asyncio.wait_for(
            enhance_candidates_with_capital_flow(top_candidates, trade_date),
            timeout=_stage_timeout("capital_flow", 75),
        )
        result["steps"]["capital_flow"] = capital_flow_summary
        logger.info("Step 3.5 done: capital flow validation %s", capital_flow_summary)
    except asyncio.TimeoutError:
        logger.warning("Capital flow enhancement timed out non-blocking")
        result["steps"]["capital_flow"] = {"status": "timeout_non_blocking"}
    except Exception as e:
        logger.warning("Capital flow enhancement failed non-blocking: %s", e)
        result["steps"]["capital_flow"] = {"status": "error_non_blocking", "error": str(e)}

    try:
        market_regime = await detect_market_regime()
    except Exception:
        market_regime = {"regime": "unknown"}

    # Step 3.6: 追高惩罚 — 对涨幅 >6% 降权，>9% 移出主池
    try:
        _before_chase = list(top_candidates)
        top_candidates, high_risk_bucket = apply_chase_high_penalty(top_candidates)
        backfilled_count = 0
        if len(top_candidates) < len(_before_chase):
            shortfall = len(_before_chase) - len(top_candidates)
            in_pool = {c.get("symbol") for c in top_candidates} | {c.get("symbol") for c in high_risk_bucket}
            reserve = [c for c in almost_candidates if c.get("symbol") not in in_pool]
            # 候补也要过追高检查，避免补进同样过热的标的
            reserve_pass, _ = apply_chase_high_penalty(reserve)
            backfill = reserve_pass[:shortfall]
            backfilled_count = len(backfill)
            for item in backfill:
                ctx.add_trace("chase_high_penalty", StepResult(
                    stock_code=item.get("symbol", ""),
                    stock_name=item.get("name", ""),
                    action="backfilled",
                    reason="追高移出后从近选名单补位",
                ))
            top_candidates.extend(backfill)
        ctx.add_step_stats("chase_high_penalty", len(_before_chase), len(top_candidates), 0)
        for item in high_risk_bucket:
            ctx.add_trace("chase_high_penalty", StepResult(
                stock_code=item.get("symbol", ""),
                stock_name=item.get("name", ""),
                action="filtered",
                reason=item.get("high_risk_reason", "涨幅过高"),
            ))
        for item in top_candidates:
            penalty = item.get("chase_high_penalty")
            if penalty:
                ctx.add_trace("chase_high_penalty", StepResult(
                    stock_code=item.get("symbol", ""),
                    stock_name=item.get("name", ""),
                    action="demoted",
                    score_before=penalty.get("original_score"),
                    score_after=penalty.get("penalized_score"),
                    reason=penalty.get("reason", "追高降权"),
                ))
        result["steps"]["chase_high_penalty"] = {
            "main_pool": len(top_candidates),
            "high_risk_bucket": len(high_risk_bucket),
            "backfilled": backfilled_count,
        }
        logger.info("Step 3.6 done: chase-high penalty, main=%d high_risk=%d", len(top_candidates), len(high_risk_bucket))
    except Exception as e:
        logger.warning("Chase-high penalty failed (non-blocking): %s", e)
        result["steps"]["chase_high_penalty"] = {"status": "error_non_blocking", "error": str(e)}
        high_risk_bucket = []

    active_strategy_id = ctx.strategy_id
    regime_label = str(market_regime.get("regime") or "unknown")
    strategy_payload = {
        "id": active_strategy_id,
        "name": _strategy_name(active_strategy_id),
        "selection_mode": "trend_screening",
        "selection_reason": "基于线性趋势确认 + 量价质量评分 + 过热过滤",
    }

    recommendations = []
    for item in top_candidates:
        try:
            stock_data = _build_stock_data_from_snapshot(item)
            stock_data["capital_flow_features"] = item.get("capital_flow_features")
            stock_data["data_quality"]["capital_flow"] = {
                "source": "akshare",
                "freshness": "latest" if item.get("capital_flow_status") in {"confirming", "contradicting", "neutral"} else "missing",
                "confidence": "medium" if item.get("capital_flow_status") in {"confirming", "contradicting"} else "low",
            }
            risk_lights = _build_risk_lights_from_snapshot(item)
            apply_capital_flow_risk_light(item, risk_lights)
            score_breakdown = _build_score_breakdown_from_anomaly(item)
            score_breakdown.append(build_capital_flow_score_item(item))

            veto_result = evaluate_risk_veto(stock_data, risk_lights, strategy_payload)
            if not veto_result.get("passed", True):
                ctx.add_trace("risk_veto", StepResult(
                    stock_code=item.get("symbol", ""),
                    stock_name=item.get("name", ""),
                    action="filtered",
                    score_after=item.get("final_score"),
                    reason="; ".join(veto_result.get("reasons", ["risk_veto"])),
                ))
                continue

            ctx.add_trace("risk_veto", StepResult(
                stock_code=item.get("symbol", ""),
                stock_name=item.get("name", ""),
                action="passed",
                score_after=item.get("final_score"),
            ))

            evidence_chain = build_evidence_chain(stock_data, risk_lights, strategy_payload, score_breakdown=score_breakdown)
            debate_view = build_debate_view(stock_data, evidence_chain, veto_result, strategy_payload)

            rec = {
                "symbol": item["symbol"],
                "name": item.get("name", ""),
                "market": item.get("market", ""),
                "price": item.get("close"),
                "change_pct": item.get("change_pct"),
                "score": item.get("final_score") or item.get("anomaly_score", 0),
                "base_score": item.get("base_score") or item.get("anomaly_score", 0),
                "final_score": item.get("final_score") or item.get("anomaly_score", 0),
                "industry_mul": item.get("industry_mul", 1.0),
                "fundamental_mul": item.get("fundamental_mul", 1.0),
                "momentum_mul": item.get("momentum_mul", 1.0),
                "strategy_id": active_strategy_id,
                "anomaly_reasons": item.get("anomaly_reasons", []),
                "score_breakdown": score_breakdown,
                "evidence_chain": evidence_chain,
                "veto_result": veto_result,
                "bull_case": debate_view.get("bull_case") or [],
                "bear_case": debate_view.get("bear_case") or [],
                "key_disagreement": debate_view.get("key_disagreement") or [],
                "falsification": debate_view.get("falsification") or [],
                "turnover_rate": item.get("turnover_rate"),
                "vol_ratio_5d": item.get("vol_ratio_5d"),
                "total_mv": item.get("total_mv"),
                "sector": item.get("sector"),
                "industry_name": item.get("industry_name"),
                "capital_flow_features": item.get("capital_flow_features"),
                "capital_flow_status": item.get("capital_flow_status"),
                "observation_bucket": item.get("observation_bucket"),
                "observation_bucket_label": item.get("observation_bucket_label"),
                "industry_filter": item.get("industry_filter"),
                "multiplier_detail": item.get("multiplier_detail"),
            }
            recommendations.append(rec)
        except Exception as e:
            logger.warning(f"Failed to process {item.get('symbol')}: {e}")
            continue

    result["steps"]["enrich"] = {"passed_veto": len(recommendations)}
    ctx.add_step_stats("risk_veto", len(top_candidates), len(recommendations), 0)
    logger.info(f"Step 4 done: {len(recommendations)} passed risk veto")

    # Step 4.8: A/B/C 分层
    try:
        recommendations = classify_tiers(recommendations)
        tier_counts = {"A": 0, "B": 0, "C": 0}
        for r in recommendations:
            t = r.get("tier", "C")
            tier_counts[t] = tier_counts.get(t, 0) + 1
            ctx.add_trace("tier_classify", StepResult(
                stock_code=r.get("symbol", ""),
                stock_name=r.get("name", ""),
                action="scored",
                score_after=r.get("score"),
                reason=f"tier={t} resonance={r.get('resonance_count', 0)} priority={r.get('priority_score', 0)}",
            ))
        ctx.add_step_stats("tier_classify", len(recommendations), len(recommendations), 0)
        result["steps"]["tier_classify"] = tier_counts
        logger.info("Step 4.8 done: tier classification %s", tier_counts)
    except Exception as e:
        logger.warning("Tier classification failed (non-blocking): %s", e)
        result["steps"]["tier_classify"] = {"status": "error_non_blocking", "error": str(e)}

    # Step 4.9: 观察动作 + 触发/失效条件
    try:
        recommendations = await asyncio.wait_for(
            generate_observation_actions(recommendations),
            timeout=_stage_timeout("observation_actions", 90),
        )
        result["steps"]["observation_actions"] = {"generated": len(recommendations)}
        logger.info("Step 4.9 done: observation actions generated for %d stocks", len(recommendations))
    except asyncio.TimeoutError:
        logger.warning("Observation action generation timed out")
        result["steps"]["observation_actions"] = {"status": "timeout_non_blocking"}
        try:
            recommendations = await generate_observation_actions(recommendations, use_ai=False)
            result["steps"]["observation_actions"]["fallback_generated"] = len(recommendations)
        except Exception as fallback_exc:
            logger.warning("Rule-based observation action fallback failed: %s", fallback_exc)
            result["steps"]["observation_actions"]["fallback_error"] = str(fallback_exc)
    except Exception as e:
        logger.warning("Observation action generation failed (non-blocking): %s", e)
        result["steps"]["observation_actions"] = {"status": "error_non_blocking", "error": str(e)}

    # Step 4.95: 二次优化层（市场环境、资讯时效、行业分散、历史复盘反馈）
    optimizer_summary: dict = {}
    try:
        symbols = [str(item.get("symbol") or "") for item in recommendations]
        review_feedback = await asyncio.to_thread(fetch_review_feedback_for_symbols, symbols)
        recommendations, optimizer_summary = optimize_observation_pool(
            recommendations,
            market_regime,
            mode="base",
            review_feedback=review_feedback,
        )
        for r in recommendations:
            adj = r.get("optimizer_adjustments") or []
            if adj:
                ctx.add_trace("pool_optimizer", StepResult(
                    stock_code=r.get("symbol", ""),
                    stock_name=r.get("name", ""),
                    action="scored",
                    reason="; ".join(adj[:3]),
                    detail={"tier_before": (r.get("pool_optimizer") or {}).get("tier_before"),
                            "tier_after": (r.get("pool_optimizer") or {}).get("tier_after"),
                            "priority_delta": (r.get("pool_optimizer") or {}).get("priority_delta")},
                ))
        ctx.add_step_stats("pool_optimizer", len(recommendations), len(recommendations), 0)
        result["steps"]["pool_optimizer"] = optimizer_summary
        logger.info("Step 4.95 done: pool optimizer %s", optimizer_summary)
    except Exception as e:
        logger.warning("Observation pool optimizer failed (non-blocking): %s", e)
        result["steps"]["pool_optimizer"] = {"status": "error_non_blocking", "error": str(e)}

    pg_save_ok = True
    try:
        saved = save_observation_snapshots(
            snapshot_date=date.fromisoformat(trade_date),
            regime=regime_label,
            recommendations=recommendations,
            strategy_id=active_strategy_id,
        )
        if recommendations and saved < len(recommendations):
            pg_save_ok = False
            logger.error("PG save partial: %d/%d saved", saved, len(recommendations))
        result["steps"]["save"] = {"saved": saved, "expected": len(recommendations)}
    except Exception as e:
        pg_save_ok = False
        logger.error(f"CRITICAL: Failed to save observations to PG: {e}")
        result["steps"]["save"] = {"error": str(e)}

    try:
        from backend.services.analysis_service.engine.summary_generator import generate_summaries
        summary_result = await asyncio.wait_for(
            generate_summaries(recommendations, trade_date),
            timeout=_stage_timeout("summarize", 120),
        )
        result["steps"]["summarize"] = summary_result
        logger.info(f"Step 5.5 done: {summary_result.get('generated', 0)} summaries generated")
    except asyncio.TimeoutError:
        logger.warning("Summary generation timed out")
        result["steps"]["summarize"] = {"status": "timeout_non_blocking"}
    except Exception as e:
        logger.warning(f"Summary generation failed: {e}")
        result["steps"]["summarize"] = {"error": str(e)}

    try:
        result["steps"]["cleanup"] = cleanup_market_redundancy()
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")

    # 盘前摘要生成（纯规则，无 AI 调用）
    pool_summary: dict = {}
    try:
        pool_summary = generate_pool_summary(recommendations, market_regime)
        if optimizer_summary:
            pool_summary["optimizer"] = optimizer_summary
        result["steps"]["pool_summary"] = {"generated": True, "tier_counts": pool_summary.get("tier_counts")}
        logger.info("Pool summary generated: %s", pool_summary.get("pool_style", ""))
        # 单独缓存 pool_summary，使用固定 key，避免请求参数不同导致取不到
        try:
            from backend.shared.cache import get_cache_manager
            _cache = await get_cache_manager()
            _summary_key = f"{trade_date}:{active_strategy_id}:ALL"
            await _cache.set("pool_summary", _summary_key, value=pool_summary)
            await _cache.set("pool_summary", "latest:ALL", value=pool_summary)
        except Exception as _ce:
            logger.warning("Failed to cache pool_summary separately: %s", _ce)
    except Exception as e:
        logger.warning("Pool summary generation failed (non-blocking): %s", e)

    result["recommendations_count"] = len(recommendations)
    result["market_regime"] = market_regime
    result["pool_summary"] = pool_summary

    # Determine final status
    _degraded = [k for k, v in result["steps"].items()
                 if isinstance(v, dict) and v.get("status", "").endswith("_non_blocking")]
    _error_detail: str | None = None
    if not pg_save_ok:
        final_status = "partial"
        result["status"] = "partial"
        save_info = result["steps"].get("save", {})
        _error_detail = save_info.get("error") or f"saved {save_info.get('saved', 0)}/{save_info.get('expected', '?')}"
        result["degraded_reason"] = f"PG save issue: {_error_detail}"
    elif _degraded:
        final_status = "partial"
        result["status"] = "partial"
        result["degraded_steps"] = _degraded
        _error_detail = f"degraded steps: {', '.join(_degraded)}"
    else:
        final_status = "completed"

    logger.info(f"=== Pipeline {final_status}: {len(recommendations)} recommendations ===")

    run_log["final_pool_size"] = len(recommendations)
    await asyncio.to_thread(_finish_run_log, run_log, "success" if final_status == "completed" else "partial", None)

    # 保存管道追踪数据
    try:
        save_traces(ctx)
        if _degraded:
            ctx.step_stats["_degraded"] = _degraded
        complete_execution_record(ctx, status=final_status,
                                  total_input=run_log.get("total_collected", 0),
                                  total_output=len(recommendations),
                                  error=_error_detail)
    except Exception as e:
        logger.warning("Failed to save pipeline traces: %s", e)

    if pg_save_ok:
        await _warm_recommend_cache(recommendations, market_regime, regime_label, trade_date,
                                    pool_summary=pool_summary, strategy_payload=strategy_payload)

    return result


async def _run_sync_stage(name: str, func, *, timeout_seconds: int):
    logger.info("Pipeline stage %s started (timeout=%ss)", name, timeout_seconds)
    try:
        return await asyncio.wait_for(asyncio.to_thread(func), timeout=timeout_seconds)
    finally:
        logger.info("Pipeline stage %s finished or released", name)


def _create_run_log(trade_date: str) -> dict:
    """创建 pipeline 运行记录，返回可变 dict 用于后续更新"""
    log = {
        "run_date": trade_date,
        "start_time": datetime.now(timezone.utc),
        "status": "running",
        "total_collected": 0,
        "total_screened": 0,
        "total_scored": 0,
        "final_pool_size": 0,
        "industries_collected": 0,
        "after_screening": 0,
        "after_hard_veto": 0,
        "after_scoring": 0,
    }
    db = SessionLocal()
    try:
        existing = db.query(PipelineRunLog).filter_by(run_date=trade_date).first()
        if existing:
            existing.start_time = log["start_time"]
            existing.status = "running"
            existing.error_message = None
            existing.end_time = None
            existing.duration_seconds = None
            db.commit()
            log["id"] = existing.id
        else:
            record = PipelineRunLog(**log)
            db.add(record)
            db.commit()
            db.refresh(record)
            log["id"] = record.id
    except Exception as e:
        logger.warning(f"Failed to create run log: {e}")
        db.rollback()
    finally:
        db.close()
    return log


def _finish_run_log(log: dict, status: str, error: str | None) -> None:
    """更新 pipeline 运行记录的最终状态"""
    db = SessionLocal()
    try:
        record = db.query(PipelineRunLog).filter_by(run_date=log["run_date"]).first()
        if record:
            record.end_time = datetime.now(timezone.utc)
            record.status = status
            record.total_collected = log.get("total_collected", 0)
            record.total_screened = log.get("total_screened", 0)
            record.total_scored = log.get("total_scored", 0)
            record.final_pool_size = log.get("final_pool_size", 0)
            record.industries_collected = log.get("industries_collected", 0)
            record.after_screening = log.get("after_screening", 0)
            record.after_hard_veto = log.get("after_hard_veto", 0)
            record.after_scoring = log.get("after_scoring", 0)
            record.vetoed_by_industry = log.get("vetoed_by_industry", 0)
            record.vetoed_by_acceleration = log.get("vetoed_by_acceleration", 0)
            record.vetoed_by_peer = log.get("vetoed_by_peer", 0)
            record.vetoed_by_fundamental = log.get("vetoed_by_fundamental", 0)
            record.vetoed_by_risk = log.get("vetoed_by_risk", 0)
            if record.start_time:
                start_time = record.start_time
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
                elapsed = (record.end_time - start_time).total_seconds()
                record.duration_seconds = int(elapsed)
            record.error_message = error[:500] if error else None
            db.commit()
    except Exception as e:
        logger.warning(f"Failed to finish run log: {e}")
        db.rollback()
    finally:
        db.close()


def has_run_today(trade_date: str | None = None) -> bool:
    """检查今天是否已经成功运行过 pipeline"""
    if not trade_date:
        trade_date = now_cn().strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        record = db.query(PipelineRunLog).filter_by(run_date=trade_date).first()
        if not record:
            return False
        if record.status in ("success", "no_data"):
            return True
        # 卡在 running 超过5分钟，自动恢复为 failed
        if record.status == "running" and record.start_time:
            start_time = record.start_time
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            if elapsed > 300:
                record.status = "failed"
                record.error_message = "auto-recovered: stuck in running > 5min"
                record.end_time = datetime.now(timezone.utc)
                db.commit()
                logger.warning("Auto-recovered stuck pipeline run for %s", trade_date)
                return False
        return False
    finally:
        db.close()


async def _warm_recommend_cache(
    recommendations: list[dict],
    market_regime: dict,
    regime_label: str,
    trade_date: str,
    pool_summary: dict | None = None,
    strategy_payload: dict | None = None,
) -> None:
    """Pipeline 完成后预热 /batch/recommend 接口的缓存，避免用户请求触发实时计算"""
    try:
        from backend.shared.cache import get_cache_manager

        cache = await get_cache_manager()
        await cache.invalidate_pattern("stock:daily_recommendations:*")

        _strategy = strategy_payload or {}
        cache_result = {
            "recommendations": recommendations,
            "count": len(recommendations),
            "market": "ALL",
            "status": "ok",
            "pipeline_status": "ok",
            "data_date": trade_date,
            "data_date_note": "current_trading_day",
            "pool_summary": pool_summary or {},
            "method": {
                "name": "anomaly_driven_v3",
                "description": "全市场量价异动筛选 + 行业硬否决 + 乘法评分，秒级响应。",
            },
            "active_strategy": {
                "id": _strategy.get("id", "unknown"),
                "name": _strategy.get("name", ""),
                "selection_mode": _strategy.get("selection_mode", ""),
                "selection_reason": _strategy.get("selection_reason", ""),
            },
            "updated_at": now_cn().isoformat(),
            "disclaimer": "每日观察池仅用于筛选值得继续研究的标的，不是买入建议；需结合个人风险承受能力和完整信息独立判断。",
        }

        default_key = "v4:market-ALL:limit-50:max-200:strategy-auto:evidence-1:debate-1:full-0"
        await cache.set("daily_recommendations", default_key, value=cache_result)
        logger.info("Cache warmed for default recommend key")
    except Exception as e:
        logger.warning(f"Failed to warm recommend cache: {e}")


def _save_almost_list(almost_candidates: list[dict], trade_date: str) -> None:
    """保存近选名单到 rejection_log"""
    if not almost_candidates:
        return
    db = SessionLocal()
    try:
        for item in almost_candidates:
            record = RejectionLog(
                symbol=item.get("symbol", ""),
                stock_name=item.get("name", ""),
                trade_date=trade_date,
                reject_stage="scoring",
                reject_reason=f"排名Top20之外，终分{item.get('final_score', 0):.1f}",
                reject_detail={
                    "base_score": item.get("base_score"),
                    "industry_mul": item.get("industry_mul"),
                    "fundamental_mul": item.get("fundamental_mul"),
                    "momentum_mul": item.get("momentum_mul"),
                },
                base_score=item.get("base_score"),
                final_score=item.get("final_score"),
                almost_qualified=True,
            )
            db.add(record)
        db.commit()
        logger.info("Saved %d almost-qualified stocks", len(almost_candidates))
    except Exception as e:
        logger.warning("Failed to save almost list: %s", e)
        db.rollback()
    finally:
        db.close()
