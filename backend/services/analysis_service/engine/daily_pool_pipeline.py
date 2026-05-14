"""每日观察池全流程编排：采集 → 趋势筛选 → 评分 → 否决 → 证据 → 辩论 → 存DB"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from backend.services.analysis_service.engine.daily_snapshot_collector import (
    cleanup_old_snapshots,
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
from backend.shared.database import SessionLocal
from backend.shared.models import PipelineRunLog

logger = logging.getLogger(__name__)

STRATEGY_ID = "trend_momentum"
TOP_N = 20


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
            "data_grade": {"grade": "B"},
        },
        "quote": {
            "turnover_rate": item.get("turnover_rate"),
            "total_mv": item.get("total_mv"),
            "circ_mv": item.get("circ_mv"),
            "volume": item.get("volume"),
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
        trade_date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"=== Daily pool pipeline started: {trade_date} ===")
    result = {
        "trade_date": trade_date,
        "status": "ok",
        "steps": {},
    }

    run_log = _create_run_log(trade_date)

    try:
        collect_result = await collect_market_snapshot(trade_date)
        result["steps"]["collect"] = collect_result
        logger.info(f"Step 1 done: collected {collect_result['collected']} snapshots")
        run_log["total_collected"] = collect_result.get("collected", 0)
    except Exception as e:
        logger.error(f"Pipeline failed at collection: {e}")
        result["status"] = "error"
        result["error"] = f"采集失败: {e}"
        _finish_run_log(run_log, "failed", str(e))
        return result

    try:
        candidates = screen_anomalies(trade_date)
        result["steps"]["screen"] = {"candidates": len(candidates)}
        logger.info(f"Step 2 done: {len(candidates)} trend candidates")
        run_log["total_screened"] = len(candidates)
    except Exception as e:
        logger.error(f"Pipeline failed at screening: {e}")
        result["status"] = "error"
        result["error"] = f"筛选失败: {e}"
        _finish_run_log(run_log, "failed", str(e))
        return result

    if not candidates:
        result["status"] = "no_data"
        result["steps"]["screen"]["note"] = "无趋势候选股（可能非交易日或数据不足）"
        _finish_run_log(run_log, "no_data", None)
        return result

    try:
        top_candidates = score_anomalies(candidates, top_n=TOP_N)
        result["steps"]["score"] = {"top_count": len(top_candidates)}
        logger.info(f"Step 3 done: top {len(top_candidates)} scored")
        run_log["total_scored"] = len(top_candidates)
    except Exception as e:
        logger.error(f"Pipeline failed at scoring: {e}")
        result["status"] = "error"
        result["error"] = f"评分失败: {e}"
        _finish_run_log(run_log, "failed", str(e))
        return result

    try:
        top_candidates, capital_flow_summary = await enhance_candidates_with_capital_flow(top_candidates, trade_date)
        result["steps"]["capital_flow"] = capital_flow_summary
        logger.info("Step 3.5 done: capital flow validation %s", capital_flow_summary)
    except Exception as e:
        logger.warning("Capital flow enhancement failed non-blocking: %s", e)
        result["steps"]["capital_flow"] = {"status": "error_non_blocking", "error": str(e)}

    try:
        market_regime = await detect_market_regime()
    except Exception:
        market_regime = {"regime": "unknown"}

    regime_label = str(market_regime.get("regime") or "unknown")
    strategy_payload = {
        "id": STRATEGY_ID,
        "name": "趋势动量",
        "selection_mode": "trend_screening",
        "selection_reason": "基于线性趋势确认 + 量价质量评分 + 过热过滤",
    }

    recommendations = []
    for item in top_candidates:
        try:
            stock_data = _build_stock_data_from_snapshot(item)
            stock_data["capital_flow_features"] = item.get("capital_flow_features")
            stock_data["data_quality"] = {
                "capital_flow": {
                    "source": "akshare",
                    "freshness": "latest" if item.get("capital_flow_status") in {"confirming", "contradicting", "neutral"} else "missing",
                    "confidence": "medium" if item.get("capital_flow_status") in {"confirming", "contradicting"} else "low",
                }
            }
            risk_lights = _build_risk_lights_from_snapshot(item)
            apply_capital_flow_risk_light(item, risk_lights)
            score_breakdown = _build_score_breakdown_from_anomaly(item)
            score_breakdown.append(build_capital_flow_score_item(item))

            veto_result = evaluate_risk_veto(stock_data, risk_lights, strategy_payload)
            if not veto_result.get("passed", True):
                continue

            evidence_chain = build_evidence_chain(stock_data, risk_lights, strategy_payload, score_breakdown=score_breakdown)
            debate_view = build_debate_view(stock_data, evidence_chain, veto_result, strategy_payload)

            rec = {
                "symbol": item["symbol"],
                "name": item.get("name", ""),
                "market": item.get("market", ""),
                "price": item.get("close"),
                "change_pct": item.get("change_pct"),
                "score": item.get("anomaly_score", 0),
                "strategy_id": STRATEGY_ID,
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
                "capital_flow_features": item.get("capital_flow_features"),
                "capital_flow_status": item.get("capital_flow_status"),
            }
            recommendations.append(rec)
        except Exception as e:
            logger.warning(f"Failed to process {item.get('symbol')}: {e}")
            continue

    result["steps"]["enrich"] = {"passed_veto": len(recommendations)}
    logger.info(f"Step 4 done: {len(recommendations)} passed risk veto")

    try:
        saved = save_observation_snapshots(
            snapshot_date=date.fromisoformat(trade_date),
            regime=regime_label,
            recommendations=recommendations,
        )
        result["steps"]["save"] = {"saved": saved}
        logger.info(f"Step 5 done: saved {saved} observations")
    except Exception as e:
        logger.warning(f"Failed to save observations: {e}")
        result["steps"]["save"] = {"error": str(e)}

    try:
        cleanup_old_snapshots(keep_days=30)
        result["steps"]["cleanup"] = {"status": "ok"}
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")

    result["recommendations_count"] = len(recommendations)
    result["market_regime"] = market_regime
    logger.info(f"=== Pipeline complete: {len(recommendations)} recommendations ===")

    run_log["final_pool_size"] = len(recommendations)
    _finish_run_log(run_log, "success", None)

    await _warm_recommend_cache(recommendations, market_regime, regime_label, trade_date)

    return result


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
    }
    db = SessionLocal()
    try:
        existing = db.query(PipelineRunLog).filter_by(run_date=trade_date).first()
        if existing:
            existing.start_time = log["start_time"]
            existing.status = "running"
            existing.error_message = None
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
        trade_date = datetime.now().strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        record = db.query(PipelineRunLog).filter_by(run_date=trade_date).first()
        return bool(record and record.status in ("success", "no_data"))
    finally:
        db.close()


async def _warm_recommend_cache(recommendations: list[dict], market_regime: dict, regime_label: str, trade_date: str) -> None:
    """Pipeline 完成后预热 /batch/recommend 接口的缓存，避免用户请求触发实时计算"""
    try:
        from backend.shared.cache import get_cache_manager

        cache = await get_cache_manager()

        cache_result = {
            "recommendations": recommendations,
            "count": len(recommendations),
            "market": "ALL",
            "status": "ok",
            "pipeline_status": "ok",
            "method": {
                "name": "anomaly_driven_v1",
                "description": "基于全市场量价异动筛选，定时采集+本地评分，秒级响应。",
            },
            "active_strategy": {
                "id": "anomaly_driven",
                "name": "量价异动驱动",
                "selection_mode": "anomaly_screening",
                "selection_reason": "全市场量价异动筛选 + 风险否决 + 证据链",
            },
            "updated_at": datetime.now().isoformat(),
            "disclaimer": "每日观察池仅用于筛选值得继续研究的标的，不是买入建议；需结合个人风险承受能力和完整信息独立判断。",
        }

        default_key = "market-ALL:limit-10:max-200:strategy-auto:evidence-1:debate-1:full-0"
        await cache.set("daily_recommendations", default_key, value=cache_result)
        logger.info("Cache warmed for default recommend key")
    except Exception as e:
        logger.warning(f"Failed to warm recommend cache: {e}")
