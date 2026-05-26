from __future__ import annotations

import logging
import json
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import inspect

from backend.shared.database import engine
from backend.shared.database import SessionLocal
from backend.shared.models import (
    DailySnapshot,
    ObservationReview,
    ResearchObservation,
    StrategyWeightPatchProposal,
    StrategyWeightVersion,
    WeightSuggestionAudit,
)
from backend.services.analysis_service.engine.ai_analysis_data import fetch_quote
from backend.services.analysis_service.engine.strategy_config import _load_all_strategies, _normalize_weights
from backend.services.analysis_service.engine.strategy_scoring import apply_strategy_weighted_score

logger = logging.getLogger(__name__)
_TABLE_CHECK_CACHE: dict[str, bool] = {}
VALID_REVIEW_OFFSETS = ("T+1", "T+5", "T+20")
_STRATEGY_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "strategies"
_WEIGHT_FACTOR_ALIASES = {
    "financial": "financial_quality",
    "financial_revenue": "financial_quality",
    "financial_profit": "financial_quality",
    "financial_cashflow": "financial_quality",
    "news_sentiment": "sentiment",
    "industry_events": "industry_theme",
    "risk_lights": "risk",
}


def _has_table(table_name: str) -> bool:
    cached = _TABLE_CHECK_CACHE.get(table_name)
    if cached is not None:
        return cached
    try:
        exists = inspect(engine).has_table(table_name)
    except Exception:
        exists = False
    _TABLE_CHECK_CACHE[table_name] = exists
    return exists


def save_observation_snapshots(
    snapshot_date: date,
    regime: str,
    recommendations: list[dict],
    strategy_id: str = "",
) -> int:
    if not _has_table("research_observations"):
        raise RuntimeError("research_observations table does not exist — run migrations")

    db = SessionLocal()
    saved = 0
    try:
        snapshot_dt = datetime.combine(snapshot_date, datetime.min.time(), tzinfo=timezone.utc)

        # Determine the strategy scope for this save.
        # Use explicit parameter if given, otherwise infer from the recommendations.
        pool_strategy = strategy_id.strip() if strategy_id else ""
        if not pool_strategy and recommendations:
            pool_strategy = str(recommendations[0].get("strategy_id") or "").strip()

        if not pool_strategy:
            raise ValueError("strategy_id is required (explicitly or via recommendations) to scope observation saves")

        # Delete stale records for this date+strategy that are not in the new pool.
        current_symbols = {str(item.get("symbol") or "").strip() for item in recommendations} - {""}
        stale_query = db.query(ResearchObservation).filter(
            ResearchObservation.snapshot_date == snapshot_dt,
            ResearchObservation.strategy_id == pool_strategy,
        )
        stale = stale_query.all()
        deleted = 0
        for row in stale:
            if row.symbol not in current_symbols:
                db.delete(row)
                deleted += 1
        if deleted:
            logger.info("Removed %d stale observations for %s/%s", deleted, snapshot_date, pool_strategy or "all")

        if not recommendations:
            db.commit()
            return 0

        for item in recommendations:
            symbol = str(item.get("symbol") or "").strip()
            strategy_id = str(item.get("strategy_id") or "").strip()
            if not symbol or not strategy_id:
                continue

            existing = (
                db.query(ResearchObservation)
                .filter(
                    ResearchObservation.snapshot_date == snapshot_dt,
                    ResearchObservation.symbol == symbol,
                    ResearchObservation.strategy_id == strategy_id,
                )
                .first()
            )
            payload = {
                "snapshot_date": snapshot_dt,
                "symbol": symbol,
                "strategy_id": strategy_id,
                "regime": regime,
                "score": float(item.get("score") or 0),
                "score_breakdown_json": item.get("score_breakdown") or [],
                "evidence_chain_json": item.get("evidence_chain") or [],
                "factor_snapshot_json": _build_factor_snapshot_with_tier(item),
                "debate_json": {
                    "bull_case": item.get("bull_case") or [],
                    "bear_case": item.get("bear_case") or [],
                    "key_disagreement": item.get("key_disagreement") or [],
                    "falsification": item.get("falsification") or [],
                },
                "veto_result_json": item.get("veto_result") or {},
                "close_price": item.get("price"),
            }
            if existing:
                for key, value in payload.items():
                    setattr(existing, key, value)
            else:
                db.add(ResearchObservation(**payload))
            saved += 1

        db.commit()
        return saved
    except Exception as exc:
        db.rollback()
        logger.error("save observation snapshots failed: %s", exc)
        raise
    finally:
        db.close()


def list_pending_reviews(review_date: date, offsets: tuple[str, ...] = ("T+1", "T+5", "T+20")) -> list[dict]:
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return []
    db = SessionLocal()
    try:
        rows = (
            db.query(ResearchObservation)
            .order_by(ResearchObservation.snapshot_date.desc(), ResearchObservation.id.desc())
            .all()
        )
        results: list[dict] = []
        for row in rows:
            snapshot_day = row.snapshot_date.date() if row.snapshot_date else None
            if not snapshot_day:
                continue
            delta = (review_date - snapshot_day).days
            target_offset = {1: "T+1", 5: "T+5", 20: "T+20"}.get(delta)
            if target_offset not in offsets:
                continue
            exists = (
                db.query(ObservationReview)
                .filter(
                    ObservationReview.observation_id == row.id,
                    ObservationReview.review_offset == target_offset,
                )
                .first()
            )
            if exists:
                continue
            results.append(
                {
                    "observation_id": row.id,
                    "symbol": row.symbol,
                    "strategy_id": row.strategy_id,
                    "snapshot_date": snapshot_day.isoformat(),
                    "review_offset": target_offset,
                    "base_price": row.close_price,
                }
            )
        return results
    finally:
        db.close()


def _falsification_triggered(observation: ResearchObservation, base_price: float | None, review_price: float | None) -> bool:
    if base_price in (None, 0) or review_price in (None, 0):
        return False
    try:
        return float(review_price) <= float(base_price) * 0.9
    except (TypeError, ValueError):
        return False


def _risk_signal_valid(observation: ResearchObservation, return_pct: float | None) -> bool:
    veto = observation.veto_result_json or {}
    warnings = veto.get("warnings") or []
    if not warnings or return_pct is None:
        return False
    return float(return_pct) <= 0


def _calculate_max_drawdown_pct(db, observation: ResearchObservation, review_date: date) -> float | None:
    if observation.close_price in (None, 0) or not observation.snapshot_date:
        return None
    snapshot_day = observation.snapshot_date.date()
    rows = (
        db.query(DailySnapshot)
        .filter(
            DailySnapshot.symbol == observation.symbol,
            DailySnapshot.trade_date >= snapshot_day.isoformat(),
            DailySnapshot.trade_date <= review_date.isoformat(),
        )
        .order_by(DailySnapshot.trade_date.asc())
        .all()
    )
    lows: list[float] = []
    for row in rows:
        value = row.low if row.low not in (None, 0) else row.close
        if value not in (None, 0):
            lows.append(float(value))
    if not lows:
        return None
    base_price = float(observation.close_price)
    worst_drop = min((low - base_price) / base_price * 100 for low in lows)
    return round(worst_drop, 4) if worst_drop < 0 else 0.0


async def run_pending_reviews(review_date: date, offsets: tuple[str, ...] = ("T+1", "T+5", "T+20")) -> dict:
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return {"review_date": review_date.isoformat(), "processed": 0, "created": 0, "skipped": 0, "items": [], "status": "tables_missing"}

    pending = list_pending_reviews(review_date, offsets=offsets)
    if not pending:
        return {"review_date": review_date.isoformat(), "processed": 0, "created": 0, "skipped": 0, "items": [], "status": "no_pending_reviews"}

    db = SessionLocal()
    created = 0
    items: list[dict] = []
    try:
        for item in pending:
            observation = db.query(ResearchObservation).filter(ResearchObservation.id == item["observation_id"]).first()
            if not observation:
                continue

            quote = await fetch_quote(item["symbol"])
            review_price = quote.get("price")
            base_price = observation.close_price
            return_pct = None
            if base_price not in (None, 0) and review_price not in (None, 0):
                try:
                    return_pct = round((float(review_price) - float(base_price)) / float(base_price) * 100, 4)
                except (TypeError, ValueError, ZeroDivisionError):
                    return_pct = None

            row = ObservationReview(
                observation_id=observation.id,
                review_offset=item["review_offset"],
                review_date=datetime.combine(review_date, datetime.min.time(), tzinfo=timezone.utc),
                close_price=review_price,
                return_pct=return_pct,
                max_drawdown_pct=_calculate_max_drawdown_pct(db, observation, review_date),
                falsification_triggered=_falsification_triggered(observation, base_price, review_price),
                risk_signal_valid=_risk_signal_valid(observation, return_pct),
                notes=f"source={quote.get('source') or 'unknown'}",
            )
            db.add(row)
            created += 1
            items.append(
                {
                    "symbol": item["symbol"],
                    "review_offset": item["review_offset"],
                    "base_price": base_price,
                    "review_price": review_price,
                    "return_pct": return_pct,
                }
            )
        db.commit()
        return {
            "review_date": review_date.isoformat(),
            "processed": len(pending),
            "created": created,
            "skipped": max(len(pending) - created, 0),
            "items": items,
            "status": "ok",
        }
    except Exception as exc:
        db.rollback()
        logger.warning("run pending reviews failed: %s", exc)
        return {
            "review_date": review_date.isoformat(),
            "processed": len(pending),
            "created": created,
            "skipped": max(len(pending) - created, 0),
            "items": items,
            "status": "error",
            "error": str(exc)[:200],
        }
    finally:
        db.close()


def build_review_report(snapshot_from: date | None = None, snapshot_to: date | None = None) -> dict:
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return {"status": "tables_missing", "summary": {}, "by_strategy": []}

    db = SessionLocal()
    try:
        reviews = db.query(ObservationReview).all()
        observations = {row.id: row for row in db.query(ResearchObservation).all()}
        rows = _filtered_review_rows(observations, reviews, snapshot_from, snapshot_to)

        by_strategy: dict[str, dict] = {}
        total_returns: list[float] = []
        for observation, review in rows:
            strategy_id = observation.strategy_id
            bucket = by_strategy.setdefault(
                strategy_id,
                {
                    "strategy_id": strategy_id,
                    "reviews": 0,
                    "positive_reviews": 0,
                    "avg_return_pct": 0.0,
                    "falsification_triggered": 0,
                    "risk_signal_valid": 0,
                },
            )
            bucket["reviews"] += 1
            if review.return_pct is not None:
                total_returns.append(float(review.return_pct))
                bucket["avg_return_pct"] += float(review.return_pct)
                if float(review.return_pct) > 0:
                    bucket["positive_reviews"] += 1
            if review.falsification_triggered:
                bucket["falsification_triggered"] += 1
            if review.risk_signal_valid:
                bucket["risk_signal_valid"] += 1

        result_rows = []
        for bucket in by_strategy.values():
            reviews_count = max(int(bucket["reviews"]), 1)
            result_rows.append(
                {
                    **bucket,
                    "win_rate": round(bucket["positive_reviews"] / reviews_count, 4),
                    "avg_return_pct": round(bucket["avg_return_pct"] / reviews_count, 4),
                }
            )

        return {
            "status": "ok",
            "summary": {
                "reviews": len(rows),
                "strategies": len(result_rows),
                "avg_return_pct": round(sum(total_returns) / len(total_returns), 4) if total_returns else None,
            },
            "by_strategy": sorted(result_rows, key=lambda item: item["reviews"], reverse=True),
        }
    finally:
        db.close()


def _serialize_topn_bucket(rank_cutoff: int, review_offset: str, observations: list[ResearchObservation], reviews: list[ObservationReview]) -> dict:
    returns = [float(review.return_pct) for review in reviews if review.return_pct is not None]
    drawdowns = [float(review.max_drawdown_pct) for review in reviews if review.max_drawdown_pct is not None]
    positive = sum(1 for value in returns if value > 0)
    worst_sample = None
    if reviews:
        worst_review = min(reviews, key=lambda review: float(review.return_pct) if review.return_pct is not None else float("inf"))
        worst_observation = next((observation for observation in observations if observation.id == worst_review.observation_id), None)
        worst_sample = {
            "symbol": worst_observation.symbol if worst_observation else "",
            "strategy_id": worst_observation.strategy_id if worst_observation else "",
            "score": worst_observation.score if worst_observation else None,
            "return_pct": worst_review.return_pct,
            "max_drawdown_pct": worst_review.max_drawdown_pct,
        }
    return {
        "rank_cutoff": rank_cutoff,
        "review_offset": review_offset,
        "observations": len(observations),
        "reviews": len(reviews),
        "coverage_rate": round(len(reviews) / max(len(observations), 1), 4),
        "win_rate": round(positive / max(len(returns), 1), 4) if returns else None,
        "avg_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "worst_return_pct": round(min(returns), 4) if returns else None,
        "max_drawdown_pct": round(min(drawdowns), 4) if drawdowns else None,
        "worst_sample": worst_sample,
    }


def build_topn_review_report(
    top_n_values: tuple[int, ...] = (5, 10, 20),
    snapshot_from: date | None = None,
    snapshot_to: date | None = None,
) -> dict:
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return {"status": "tables_missing", "summary": {}, "by_top_n": []}

    db = SessionLocal()
    try:
        reviews = db.query(ObservationReview).all()
        observations = {row.id: row for row in db.query(ResearchObservation).all()}
        rows = _filtered_review_rows(observations, reviews, snapshot_from, snapshot_to)
        reviews_by_observation_offset = {(review.observation_id, review.review_offset): review for _, review in rows}
        observations_by_day: dict[tuple[date, str], list[ResearchObservation]] = {}
        for observation in observations.values():
            snapshot_day = observation.snapshot_date.date() if observation.snapshot_date else None
            if not snapshot_day:
                continue
            if snapshot_from and snapshot_day < snapshot_from:
                continue
            if snapshot_to and snapshot_day > snapshot_to:
                continue
            observations_by_day.setdefault((snapshot_day, observation.strategy_id), []).append(observation)

        result_rows = []
        for cutoff in sorted(set(top_n_values)):
            if cutoff <= 0:
                continue
            top_observations: list[ResearchObservation] = []
            for group in observations_by_day.values():
                top_observations.extend(sorted(group, key=lambda item: float(item.score or 0), reverse=True)[:cutoff])
            top_ids = {observation.id for observation in top_observations}
            for offset in VALID_REVIEW_OFFSETS:
                offset_reviews = [review for (observation_id, review_offset), review in reviews_by_observation_offset.items() if observation_id in top_ids and review_offset == offset]
                result_rows.append(_serialize_topn_bucket(cutoff, offset, top_observations, offset_reviews))

        return {
            "status": "ok",
            "summary": {
                "snapshots": len({key[0] for key in observations_by_day}),
                "strategies": len({key[1] for key in observations_by_day}),
                "rows": len(result_rows),
                "reviews": len(rows),
            },
            "by_top_n": result_rows,
        }
    finally:
        db.close()


def build_review_readiness(
    review_date: date | None = None,
    offsets: tuple[str, ...] = VALID_REVIEW_OFFSETS,
) -> dict:
    review_date = review_date or date.today()
    tables = {
        "research_observations": _has_table("research_observations"),
        "observation_reviews": _has_table("observation_reviews"),
    }
    if not all(tables.values()):
        return {
            "status": "tables_missing",
            "review_date": review_date.isoformat(),
            "offsets": list(offsets),
            "tables": tables,
            "summary": {
                "observations": 0,
                "reviews": 0,
                "pending_reviews": 0,
                "strategies_with_reviews": 0,
            },
            "latest_snapshot_date": None,
            "latest_review_date": None,
            "pending_reviews": [],
            "review_report_summary": {},
        }

    db = SessionLocal()
    try:
        observations = db.query(ResearchObservation).all()
        reviews = db.query(ObservationReview).all()
    except Exception as exc:
        logger.warning("build review readiness failed: %s", exc)
        return {
            "status": "error",
            "review_date": review_date.isoformat(),
            "offsets": list(offsets),
            "tables": tables,
            "summary": {
                "observations": 0,
                "reviews": 0,
                "pending_reviews": 0,
                "strategies_with_reviews": 0,
            },
            "latest_snapshot_date": None,
            "latest_review_date": None,
            "pending_reviews": [],
            "review_report_summary": {},
            "error": str(exc)[:200],
        }
    finally:
        db.close()

    pending = list_pending_reviews(review_date, offsets=offsets)
    report = build_review_report()
    latest_snapshot = max((row.snapshot_date for row in observations if row.snapshot_date), default=None)
    latest_review = max((row.review_date for row in reviews if row.review_date), default=None)

    if not observations:
        status = "no_observations"
    elif pending:
        status = "pending_reviews"
    elif reviews:
        status = "reviewed"
    else:
        status = "no_pending_reviews"

    return {
        "status": status,
        "review_date": review_date.isoformat(),
        "offsets": list(offsets),
        "tables": tables,
        "summary": {
            "observations": len(observations),
            "reviews": len(reviews),
            "pending_reviews": len(pending),
            "strategies_with_reviews": int((report.get("summary") or {}).get("strategies") or 0),
        },
        "latest_snapshot_date": latest_snapshot.date().isoformat() if latest_snapshot else None,
        "latest_review_date": latest_review.date().isoformat() if latest_review else None,
        "pending_reviews": pending[:20],
        "review_report_summary": report.get("summary") or {},
    }


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_optional_float(value) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _factor_key(value) -> str:
    return str(value or "").strip()


def _infer_direction(*values: float | None) -> str:
    total = sum(value for value in values if value is not None)
    if total > 0:
        return "positive"
    if total < 0:
        return "negative"
    return "neutral"


def _factor_contribution(item: dict) -> float:
    return abs(_safe_float(item.get("weighted_delta"), 0.0)) + abs(_safe_float(item.get("evidence_impact"), 0.0)) + abs(_safe_float(item.get("score_delta"), 0.0))


def _build_factor_snapshot_with_tier(item: dict) -> dict:
    """构建 factor_snapshot，包含原有因子快照列表和新增分层/动作字段。"""
    base_factors = build_factor_snapshot(item)
    return {
        "factors": base_factors,
        "tier": item.get("tier"),
        "tier_reason": item.get("tier_reason"),
        "resonance_count": item.get("resonance_count"),
        "priority_score": item.get("priority_score"),
        "observation_action": item.get("observation_action"),
        "sector": item.get("sector"),
        "industry_name": item.get("industry_name"),
        "observation_bucket": item.get("observation_bucket"),
        "observation_bucket_label": item.get("observation_bucket_label"),
        "trigger_condition": item.get("trigger_condition"),
        "invalidation_condition": item.get("invalidation_condition"),
        "risk_warning": item.get("risk_warning"),
        "chase_high_penalty": item.get("chase_high_penalty"),
        "news_freshness_score": item.get("news_freshness_score"),
        "diversification_penalty": item.get("diversification_penalty"),
        "review_feedback": item.get("review_feedback"),
        "pool_optimizer": item.get("pool_optimizer"),
        "optimizer_adjustments": item.get("optimizer_adjustments"),
    }


def build_factor_snapshot(item: dict) -> list[dict]:
    buckets: dict[str, dict] = {}

    def bucket_for(factor: str, label: str | None = None, dimension: str | None = None) -> dict:
        bucket = buckets.setdefault(
            factor,
            {
                "factor": factor,
                "dimension": dimension or factor,
                "label": label or factor,
                "sources": set(),
                "score_delta": None,
                "evidence_impact": None,
                "weighted_delta": None,
                "weight": None,
                "direction": None,
                "confidence": None,
            },
        )
        if dimension and (not bucket.get("dimension") or bucket.get("dimension") == factor):
            bucket["dimension"] = dimension
        if label and bucket.get("label") == factor:
            bucket["label"] = label
        return bucket

    score_breakdown = item.get("score_breakdown") or []
    if isinstance(score_breakdown, list):
        for entry in score_breakdown:
            entry = entry if isinstance(entry, dict) else {}
            factor = _factor_key(entry.get("key") or entry.get("factor") or entry.get("dimension"))
            if not factor or factor == "base":
                continue
            bucket = bucket_for(factor, entry.get("label"), entry.get("dimension"))
            bucket["sources"].add("score_breakdown")
            bucket["score_delta"] = _safe_optional_float(entry.get("delta"))

    evidence_chain = item.get("evidence_chain") or []
    if isinstance(evidence_chain, list):
        for entry in evidence_chain:
            entry = entry if isinstance(entry, dict) else {}
            factor = _factor_key(entry.get("factor") or entry.get("dimension"))
            if not factor:
                continue
            bucket = bucket_for(factor, entry.get("label"), entry.get("dimension"))
            bucket["sources"].add("evidence_chain")
            bucket["evidence_impact"] = _safe_optional_float(entry.get("impact"))
            if entry.get("direction"):
                bucket["direction"] = str(entry.get("direction"))
            if entry.get("confidence"):
                bucket["confidence"] = str(entry.get("confidence"))

    weighted_factors = item.get("strategy_weighted_factors") or []
    if isinstance(weighted_factors, list):
        for entry in weighted_factors:
            entry = entry if isinstance(entry, dict) else {}
            factor = _factor_key(entry.get("factor") or entry.get("dimension"))
            if not factor:
                continue
            bucket = bucket_for(factor, entry.get("label"), entry.get("dimension"))
            bucket["sources"].add("strategy_weighted")
            bucket["weighted_delta"] = _safe_optional_float(entry.get("weighted_delta"))
            bucket["weight"] = _safe_optional_float(entry.get("weight"))

    rows = []
    for bucket in buckets.values():
        if not bucket.get("direction"):
            bucket["direction"] = _infer_direction(bucket.get("weighted_delta"), bucket.get("evidence_impact"), bucket.get("score_delta"))
        bucket["sources"] = sorted(bucket["sources"])
        rows.append(bucket)
    return sorted(rows, key=lambda row: (-_factor_contribution(row), row["factor"]))


def _observation_factor_items(observation: ResearchObservation) -> list[dict]:
    snapshot = getattr(observation, "factor_snapshot_json", None) or []
    if isinstance(snapshot, dict):
        snapshot = snapshot.get("factors", [])
    if isinstance(snapshot, list) and snapshot:
        return [item for item in snapshot if isinstance(item, dict)]

    evidence_chain = observation.evidence_chain_json or []
    if not isinstance(evidence_chain, list):
        return []
    rows = []
    for item in evidence_chain:
        item = item if isinstance(item, dict) else {}
        factor = str(item.get("factor") or item.get("dimension") or "unknown")
        rows.append(
            {
                "factor": factor,
                "dimension": item.get("dimension") or factor,
                "label": str(item.get("label") or factor),
                "sources": ["evidence_chain"],
                "score_delta": None,
                "evidence_impact": _safe_optional_float(item.get("impact")),
                "weighted_delta": None,
                "weight": None,
                "direction": item.get("direction") or _infer_direction(_safe_optional_float(item.get("impact"))),
                "confidence": item.get("confidence"),
            }
        )
    return rows


def _factor_impact(item: dict) -> float:
    for key in ("weighted_delta", "evidence_impact", "score_delta", "impact"):
        value = item.get(key)
        if value is not None:
            return _safe_float(value, 0.0)
    return 0.0


def _filtered_review_rows(
    observations: dict[int, ResearchObservation],
    reviews: list[ObservationReview],
    snapshot_from: date | None = None,
    snapshot_to: date | None = None,
) -> list[tuple[ResearchObservation, ObservationReview]]:
    rows = []
    for review in reviews:
        observation = observations.get(review.observation_id)
        if not observation:
            continue
        snapshot_day = observation.snapshot_date.date() if observation.snapshot_date else None
        if snapshot_from and snapshot_day and snapshot_day < snapshot_from:
            continue
        if snapshot_to and snapshot_day and snapshot_day > snapshot_to:
            continue
        rows.append((observation, review))
    return rows


def _new_factor_bucket(factor: str, label: str, regime: str | None = None, dimension: str | None = None) -> dict:
    bucket = {
        "factor": factor,
        "dimension": dimension,
        "label": label,
        "sources": set(),
        "reviews": 0,
        "positive_reviews": 0,
        "return_total": 0.0,
        "return_count": 0,
        "impact_total": 0.0,
        "score_delta_total": 0.0,
        "score_delta_count": 0,
        "evidence_impact_total": 0.0,
        "evidence_impact_count": 0,
        "weighted_delta_total": 0.0,
        "weighted_delta_count": 0,
        "positive_impact_reviews": 0,
        "negative_impact_reviews": 0,
        "max_drawdown_pct": None,
        "worst_return_pct": None,
        "falsification_triggered": 0,
        "risk_signal_valid": 0,
    }
    if regime is not None:
        bucket["regime"] = regime
    return bucket


def _update_factor_bucket(bucket: dict, impact: float, review: ObservationReview, item: dict | None = None) -> None:
    bucket["reviews"] += 1
    bucket["impact_total"] += impact
    if item:
        if item.get("dimension") and not bucket.get("dimension"):
            bucket["dimension"] = item.get("dimension")
        for source in item.get("sources") or []:
            bucket["sources"].add(str(source))
        for field, total_key, count_key in (
            ("score_delta", "score_delta_total", "score_delta_count"),
            ("evidence_impact", "evidence_impact_total", "evidence_impact_count"),
            ("weighted_delta", "weighted_delta_total", "weighted_delta_count"),
        ):
            if item.get(field) is not None:
                bucket[total_key] += _safe_float(item.get(field), 0.0)
                bucket[count_key] += 1
    if impact > 0:
        bucket["positive_impact_reviews"] += 1
    if impact < 0:
        bucket["negative_impact_reviews"] += 1
    if review.return_pct is not None:
        return_pct = float(review.return_pct)
        bucket["return_total"] += return_pct
        bucket["return_count"] += 1
        bucket["worst_return_pct"] = return_pct if bucket["worst_return_pct"] is None else min(bucket["worst_return_pct"], return_pct)
        if return_pct > 0:
            bucket["positive_reviews"] += 1
    if review.max_drawdown_pct is not None:
        drawdown = float(review.max_drawdown_pct)
        bucket["max_drawdown_pct"] = drawdown if bucket["max_drawdown_pct"] is None else min(bucket["max_drawdown_pct"], drawdown)
    if review.falsification_triggered:
        bucket["falsification_triggered"] += 1
    if review.risk_signal_valid:
        bucket["risk_signal_valid"] += 1


def _serialize_factor_bucket(bucket: dict, total_reviews: int) -> dict:
    reviews_count = max(int(bucket["reviews"]), 1)
    return_count = int(bucket["return_count"])
    item = {
        "factor": bucket["factor"],
        "dimension": bucket.get("dimension") or bucket["factor"],
        "label": bucket["label"],
        "sources": sorted(bucket.get("sources") or []),
        "reviews": bucket["reviews"],
        "positive_reviews": bucket["positive_reviews"],
        "win_rate": round(bucket["positive_reviews"] / reviews_count, 4),
        "avg_return_pct": round(bucket["return_total"] / return_count, 4) if return_count else None,
        "max_drawdown_pct": round(bucket["max_drawdown_pct"], 4) if bucket["max_drawdown_pct"] is not None else None,
        "worst_return_pct": round(bucket["worst_return_pct"], 4) if bucket["worst_return_pct"] is not None else None,
        "coverage_rate": round(bucket["reviews"] / max(total_reviews, 1), 4),
        "avg_impact": round(bucket["impact_total"] / reviews_count, 4),
        "avg_score_delta": round(bucket["score_delta_total"] / bucket["score_delta_count"], 4) if bucket["score_delta_count"] else None,
        "avg_evidence_impact": round(bucket["evidence_impact_total"] / bucket["evidence_impact_count"], 4) if bucket["evidence_impact_count"] else None,
        "avg_weighted_delta": round(bucket["weighted_delta_total"] / bucket["weighted_delta_count"], 4) if bucket["weighted_delta_count"] else None,
        "positive_impact_reviews": bucket["positive_impact_reviews"],
        "negative_impact_reviews": bucket["negative_impact_reviews"],
        "falsification_triggered": bucket["falsification_triggered"],
        "risk_signal_valid": bucket["risk_signal_valid"],
    }
    if "regime" in bucket:
        item["regime"] = bucket["regime"]
    return item


def build_factor_review_report(snapshot_from: date | None = None, snapshot_to: date | None = None) -> dict:
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return {"status": "tables_missing", "summary": {}, "by_factor": []}

    db = SessionLocal()
    try:
        reviews = db.query(ObservationReview).all()
        observations = {row.id: row for row in db.query(ResearchObservation).all()}
        rows = _filtered_review_rows(observations, reviews, snapshot_from, snapshot_to)

        by_factor: dict[str, dict] = {}
        by_regime_factor: dict[tuple[str, str], dict] = {}
        for observation, review in rows:
            regime = str(observation.regime or "unknown")
            for item in _observation_factor_items(observation):
                factor = str(item.get("factor") or item.get("dimension") or "unknown")
                label = str(item.get("label") or factor)
                impact = _factor_impact(item)
                dimension = item.get("dimension") or factor
                bucket = by_factor.setdefault(factor, _new_factor_bucket(factor, label, dimension=dimension))
                _update_factor_bucket(bucket, impact, review, item)
                regime_bucket = by_regime_factor.setdefault((regime, factor), _new_factor_bucket(factor, label, regime=regime, dimension=dimension))
                _update_factor_bucket(regime_bucket, impact, review, item)

        result_rows = [_serialize_factor_bucket(bucket, len(rows)) for bucket in by_factor.values()]
        regime_rows = [_serialize_factor_bucket(bucket, len(rows)) for bucket in by_regime_factor.values()]

        return {
            "status": "ok",
            "summary": {"factors": len(result_rows), "reviews": len(rows), "regime_factors": len(regime_rows)},
            "by_factor": sorted(result_rows, key=lambda item: item["reviews"], reverse=True),
            "by_regime_factor": sorted(regime_rows, key=lambda item: (item["regime"], -item["reviews"], item["factor"])),
        }
    finally:
        db.close()


def build_single_factor_validation_report(
    factor: str,
    snapshot_from: date | None = None,
    snapshot_to: date | None = None,
    min_reviews: int = 1,
) -> dict:
    factor_key = str(factor or "").strip()
    if not factor_key:
        return {"status": "invalid_factor", "factor": factor_key, "summary": {}, "by_offset": [], "samples": []}
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return {"status": "tables_missing", "factor": factor_key, "summary": {}, "by_offset": [], "samples": []}

    db = SessionLocal()
    try:
        reviews = db.query(ObservationReview).all()
        observations = {row.id: row for row in db.query(ResearchObservation).all()}
        rows = _filtered_review_rows(observations, reviews, snapshot_from, snapshot_to)

        summary_bucket = _new_factor_bucket(factor_key, factor_key)
        by_offset: dict[str, dict] = {}
        samples = []
        for observation, review in rows:
            match = next(
                (
                    item
                    for item in _observation_factor_items(observation)
                    if str(item.get("factor") or "") == factor_key or str(item.get("dimension") or "") == factor_key
                ),
                None,
            )
            if not match:
                continue

            label = str(match.get("label") or factor_key)
            if summary_bucket["label"] == factor_key:
                summary_bucket["label"] = label
            impact = _factor_impact(match)
            _update_factor_bucket(summary_bucket, impact, review, match)
            offset = str(getattr(review, "review_offset", None) or "unknown")
            offset_bucket = by_offset.setdefault(offset, _new_factor_bucket(factor_key, label))
            _update_factor_bucket(offset_bucket, impact, review, match)
            samples.append(
                {
                    "symbol": observation.symbol,
                    "strategy_id": observation.strategy_id,
                    "snapshot_date": observation.snapshot_date.date().isoformat() if observation.snapshot_date else None,
                    "review_offset": offset,
                    "return_pct": review.return_pct,
                    "impact": impact,
                    "direction": match.get("direction"),
                    "label": label,
                }
            )

        summary = _serialize_factor_bucket(summary_bucket, max(len(rows), 1))
        reviews_count = int(summary["reviews"])
        if reviews_count < int(min_reviews):
            validation_state = "insufficient_samples"
        elif _safe_float(summary.get("win_rate"), 0.0) >= 0.6 and summary.get("avg_return_pct") is not None and _safe_float(summary.get("avg_return_pct"), 0.0) > 0:
            validation_state = "positive_observation"
        elif summary.get("avg_return_pct") is None:
            validation_state = "observed"
        else:
            validation_state = "needs_more_review"
        summary["min_reviews"] = int(min_reviews)
        summary["validation_state"] = validation_state

        samples.sort(key=lambda sample: (sample.get("snapshot_date") or "", sample.get("review_offset") or ""), reverse=True)
        return {
            "status": "ok",
            "factor": factor_key,
            "summary": summary,
            "by_offset": sorted(
                (
                    {**_serialize_factor_bucket(bucket, max(len(rows), 1)), "review_offset": offset}
                    for offset, bucket in by_offset.items()
                ),
                key=lambda item: item["review_offset"],
            ),
            "samples": samples[:20],
        }
    finally:
        db.close()


def _weight_suggestion_action(item: dict) -> str:
    reviews = max(int(item.get("reviews") or 0), 1)
    win_rate = _safe_float(item.get("win_rate"), 0.0)
    avg_return_pct = item.get("avg_return_pct")
    avg_impact = _safe_float(item.get("avg_impact"), 0.0)
    falsification_rate = _safe_float(item.get("falsification_triggered"), 0.0) / reviews

    if win_rate >= 0.6 and avg_return_pct is not None and _safe_float(avg_return_pct) > 0 and avg_impact > 0:
        return "increase"
    if win_rate <= 0.4 or (avg_return_pct is not None and _safe_float(avg_return_pct) < 0) or falsification_rate >= 0.3:
        return "decrease"
    return "hold"


def _weight_suggestion_confidence(item: dict, action: str) -> str:
    reviews = int(item.get("reviews") or 0)
    win_rate = _safe_float(item.get("win_rate"), 0.0)
    avg_return_pct = item.get("avg_return_pct")
    avg_return = _safe_float(avg_return_pct) if avg_return_pct is not None else 0.0
    avg_impact = _safe_float(item.get("avg_impact"), 0.0)
    falsification_rate = _safe_float(item.get("falsification_triggered"), 0.0) / max(reviews, 1)

    strong_increase = action == "increase" and win_rate >= 0.75 and avg_return > 3 and avg_impact > 0.5
    strong_decrease = action == "decrease" and (win_rate <= 0.25 or avg_return < -3 or falsification_rate >= 0.5)
    medium_increase = action == "increase" and win_rate >= 0.65 and avg_return > 1 and avg_impact > 0
    medium_decrease = action == "decrease" and (win_rate <= 0.35 or avg_return < -1 or falsification_rate >= 0.3)

    if reviews >= 10 and (strong_increase or strong_decrease):
        return "high"
    if reviews >= 5 and (medium_increase or medium_decrease):
        return "medium"
    return "low"


def _weight_suggestion_reason(item: dict, action: str) -> str:
    reviews = int(item.get("reviews") or 0)
    win_rate = _safe_float(item.get("win_rate"), 0.0)
    avg_return_pct = item.get("avg_return_pct")
    avg_return_text = "n/a" if avg_return_pct is None else f"{_safe_float(avg_return_pct):.2f}%"
    avg_impact = _safe_float(item.get("avg_impact"), 0.0)
    falsification = int(item.get("falsification_triggered") or 0)

    if action == "increase":
        return f"{reviews} reviews show win_rate={win_rate:.2f}, avg_return={avg_return_text}, avg_impact={avg_impact:.2f}; positive return and impact support a cautious increase."
    if action == "decrease":
        return f"{reviews} reviews show win_rate={win_rate:.2f}, avg_return={avg_return_text}, falsification_triggered={falsification}; weak outcome or risk signal supports a cautious decrease."
    return f"{reviews} reviews show mixed signals with win_rate={win_rate:.2f}, avg_return={avg_return_text}, avg_impact={avg_impact:.2f}; hold weight until evidence strengthens."


def build_weight_adjustment_suggestions(
    min_reviews: int = 3,
    snapshot_from: date | None = None,
    snapshot_to: date | None = None,
) -> dict:
    report = build_factor_review_report(snapshot_from=snapshot_from, snapshot_to=snapshot_to)
    if report.get("status") != "ok":
        return {
            "status": report.get("status", "tables_missing"),
            "summary": {"suggestions": 0, "eligible_factors": 0, "min_reviews": min_reviews},
            "suggestions": [],
        }

    suggestions = []
    for item in report.get("by_factor", []):
        reviews = int(item.get("reviews") or 0)
        if reviews < min_reviews:
            continue

        action = _weight_suggestion_action(item)
        suggestions.append(
            {
                "factor": str(item.get("factor") or "unknown"),
                "label": str(item.get("label") or item.get("factor") or "unknown"),
                "action": action,
                "confidence": _weight_suggestion_confidence(item, action),
                "reason": _weight_suggestion_reason(item, action),
                "metrics": {
                    "reviews": reviews,
                    "win_rate": _safe_float(item.get("win_rate"), 0.0),
                    "avg_return_pct": item.get("avg_return_pct"),
                    "avg_impact": _safe_float(item.get("avg_impact"), 0.0),
                    "falsification_triggered": int(item.get("falsification_triggered") or 0),
                    "risk_signal_valid": int(item.get("risk_signal_valid") or 0),
                },
            }
        )

    action_rank = {"increase": 0, "decrease": 1, "hold": 2}
    suggestions.sort(key=lambda item: (action_rank.get(item["action"], 99), -item["metrics"]["reviews"], item["factor"]))

    return {
        "status": "ok",
        "summary": {
            "suggestions": len(suggestions),
            "eligible_factors": len(suggestions),
            "min_reviews": min_reviews,
        },
        "suggestions": suggestions,
    }


def _date_to_datetime(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)


def _serialize_weight_suggestion_audit(row: WeightSuggestionAudit) -> dict:
    return {
        "id": row.id,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "snapshot_from": row.snapshot_from.isoformat() if row.snapshot_from else None,
        "snapshot_to": row.snapshot_to.isoformat() if row.snapshot_to else None,
        "min_reviews": row.min_reviews,
        "status": row.status,
        "suggestions": row.suggestions_json or [],
        "summary": row.summary_json or {},
        "accepted": row.accepted,
        "accepted_by": row.accepted_by,
        "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def save_weight_suggestion_audit(
    result: dict,
    min_reviews: int,
    snapshot_from: datetime | date | None = None,
    snapshot_to: datetime | date | None = None,
) -> int | None:
    if not _has_table("weight_suggestion_audits"):
        return None

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        row = WeightSuggestionAudit(
            generated_at=now,
            snapshot_from=_date_to_datetime(snapshot_from),
            snapshot_to=_date_to_datetime(snapshot_to),
            min_reviews=int(min_reviews),
            status=str(result.get("status") or "unknown")[:30],
            suggestions_json=result.get("suggestions") or [],
            summary_json=result.get("summary") or {},
            created_at=now,
        )
        db.add(row)
        db.commit()
        return row.id
    except Exception as exc:
        db.rollback()
        logger.warning("save weight suggestion audit failed: %s", exc)
        return None
    finally:
        db.close()


def list_weight_suggestion_audits(limit: int = 20) -> list[dict]:
    if not _has_table("weight_suggestion_audits"):
        return []

    db = SessionLocal()
    try:
        rows = (
            db.query(WeightSuggestionAudit)
            .order_by(WeightSuggestionAudit.generated_at.desc(), WeightSuggestionAudit.id.desc())
            .limit(min(max(int(limit), 1), 100))
            .all()
        )
        return [_serialize_weight_suggestion_audit(row) for row in rows]
    finally:
        db.close()


def update_weight_suggestion_audit(
    audit_id: int,
    accepted: bool | None = None,
    notes: str | None = None,
    accepted_by: int | None = None,
    accepted_provided: bool = False,
) -> dict | None:
    if not _has_table("weight_suggestion_audits"):
        return None

    db = SessionLocal()
    try:
        row = db.query(WeightSuggestionAudit).filter(WeightSuggestionAudit.id == audit_id).first()
        if not row:
            return None
        if accepted_provided or accepted is not None:
            row.accepted = None if accepted is None else bool(accepted)
            row.accepted_by = None if accepted is None else accepted_by
            row.accepted_at = None if accepted is None else datetime.now(timezone.utc)
        if notes is not None:
            row.notes = notes
        db.commit()
        return _serialize_weight_suggestion_audit(row)
    except Exception as exc:
        db.rollback()
        logger.warning("update weight suggestion audit failed: %s", exc)
        return None
    finally:
        db.close()


def _normalized_weights(weights: dict) -> dict[str, float]:
    clean = {str(key): min(max(_safe_float(value), 0.0), 1.0) for key, value in weights.items()}
    total = sum(clean.values())
    if total <= 0:
        return clean
    return {key: round(value / total, 6) for key, value in clean.items()}


def _weight_factor_key(factor: str, weights: dict[str, float]) -> str | None:
    normalized = str(factor or "").strip()
    if normalized in weights:
        return normalized
    aliased = _WEIGHT_FACTOR_ALIASES.get(normalized)
    if aliased in weights:
        return aliased
    if normalized.startswith("risk_") and "risk" in weights:
        return "risk"
    return None


def build_weight_strategy_patch_preview(
    audit_id: int,
    strategy_id: str = "retail_small",
    step: float = 0.03,
    max_delta: float = 0.08,
) -> dict:
    if not _has_table("weight_suggestion_audits"):
        return {"status": "tables_missing", "audit_id": audit_id, "strategy_id": strategy_id, "items": []}

    db = SessionLocal()
    try:
        audit = db.query(WeightSuggestionAudit).filter(WeightSuggestionAudit.id == audit_id).first()
    except Exception as exc:
        logger.warning("load weight suggestion audit for patch preview failed: %s", exc)
        return {"status": "error", "audit_id": audit_id, "strategy_id": strategy_id, "items": [], "error": str(exc)[:200]}
    finally:
        db.close()

    if not audit:
        return {"status": "audit_not_found", "audit_id": audit_id, "strategy_id": strategy_id, "items": []}
    if audit.accepted is not True:
        return {
            "status": "audit_not_accepted",
            "audit_id": audit_id,
            "strategy_id": strategy_id,
            "accepted": audit.accepted,
            "items": [],
        }

    clean_strategy_id = (strategy_id or "retail_small").strip()
    strategy_path = _STRATEGY_CONFIG_DIR / f"{clean_strategy_id}.json"
    try:
        strategy = json.loads(strategy_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "strategy_not_found", "audit_id": audit_id, "strategy_id": clean_strategy_id, "items": []}
    except Exception as exc:
        logger.warning("load strategy config for patch preview failed: %s", exc)
        return {"status": "strategy_config_error", "audit_id": audit_id, "strategy_id": clean_strategy_id, "items": [], "error": str(exc)[:200]}

    weights = strategy.get("weights")
    if not isinstance(weights, dict) or not weights:
        return {"status": "strategy_weights_missing", "audit_id": audit_id, "strategy_id": clean_strategy_id, "items": []}

    before = _normalized_weights(weights)
    adjusted = dict(before)
    suggestions = audit.suggestions_json if isinstance(audit.suggestions_json, list) else []
    confidence_multiplier = {"low": 1, "medium": 2, "high": 3}
    safe_step = max(_safe_float(step, 0.03), 0.0)
    safe_max_delta = max(_safe_float(max_delta, 0.08), 0.0)
    items: list[dict] = []

    for suggestion in suggestions:
        item = suggestion if isinstance(suggestion, dict) else {}
        source_factor = str(item.get("factor") or "").strip()
        factor = _weight_factor_key(source_factor, adjusted)
        action = str(item.get("action") or "hold").strip().lower()
        confidence = str(item.get("confidence") or "low").strip().lower()
        if not factor or action not in {"increase", "decrease", "hold"}:
            continue

        requested_delta = 0.0
        if action in {"increase", "decrease"}:
            multiplier = confidence_multiplier.get(confidence, 1)
            requested_delta = min(safe_step * multiplier, safe_max_delta)
            if action == "decrease":
                requested_delta = -requested_delta

        raw_before = adjusted[factor]
        raw_after = min(max(raw_before + requested_delta, 0.0), 1.0)
        adjusted[factor] = raw_after
        items.append(
            {
                "factor": factor,
                "source_factor": source_factor,
                "action": action,
                "confidence": confidence,
                "before": before[factor],
                "raw_after": round(raw_after, 6),
                "requested_delta": round(requested_delta, 6),
                "applied_delta": round(raw_after - raw_before, 6),
            }
        )

    after = _normalized_weights(adjusted)
    delta = {factor: round(after.get(factor, 0.0) - before.get(factor, 0.0), 6) for factor in before}
    after_items = {
        item["factor"]: {
            **item,
            "after": after.get(item["factor"], item["raw_after"]),
            "normalized_delta": delta.get(item["factor"], 0.0),
        }
        for item in items
    }

    return {
        "status": "ok",
        "audit_id": audit_id,
        "strategy_id": clean_strategy_id,
        "step": safe_step,
        "max_delta": safe_max_delta,
        "before": before,
        "after": after,
        "delta": delta,
        "items": list(after_items.values()),
    }


def _serialize_strategy_weight_patch_proposal(row: StrategyWeightPatchProposal) -> dict:
    return {
        "id": row.id,
        "audit_id": row.audit_id,
        "strategy_id": row.strategy_id,
        "status": row.status,
        "step": row.step,
        "max_delta": row.max_delta,
        "before": row.before_json or {},
        "after": row.after_json or {},
        "delta": row.delta_json or {},
        "items": row.items_json or [],
        "preview": row.preview_json or {},
        "created_by": row.created_by,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "applied_by": getattr(row, "applied_by", None),
        "applied_at": row.applied_at.isoformat() if getattr(row, "applied_at", None) else None,
        "applied_error": getattr(row, "applied_error", None),
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_strategy_weight_version(row: StrategyWeightVersion) -> dict:
    return {
        "id": row.id,
        "strategy_id": row.strategy_id,
        "proposal_id": row.proposal_id,
        "version": row.version,
        "before": row.before_json or {},
        "after": row.after_json or {},
        "applied_by": row.applied_by,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "rolled_back_by": row.rolled_back_by,
        "rolled_back_at": row.rolled_back_at.isoformat() if row.rolled_back_at else None,
        "rollback_error": row.rollback_error,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def create_strategy_weight_patch_proposal(
    audit_id: int,
    strategy_id: str = "retail_small",
    step: float = 0.03,
    max_delta: float = 0.08,
    created_by: int | None = None,
    notes: str | None = None,
) -> dict:
    if not _has_table("strategy_weight_patch_proposals"):
        return {"status": "tables_missing", "audit_id": audit_id, "strategy_id": strategy_id}

    preview = build_weight_strategy_patch_preview(
        audit_id,
        strategy_id=strategy_id,
        step=step,
        max_delta=max_delta,
    )
    if preview.get("status") != "ok":
        return {"status": "preview_not_ready", "preview": preview, "audit_id": audit_id, "strategy_id": strategy_id}

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        row = StrategyWeightPatchProposal(
            audit_id=int(audit_id),
            strategy_id=str(preview.get("strategy_id") or strategy_id),
            status="pending",
            step=float(preview.get("step") or step),
            max_delta=float(preview.get("max_delta") or max_delta),
            before_json=preview.get("before") or {},
            after_json=preview.get("after") or {},
            delta_json=preview.get("delta") or {},
            items_json=preview.get("items") or [],
            preview_json=preview,
            created_by=created_by,
            notes=notes,
            created_at=now,
        )
        db.add(row)
        db.commit()
        return _serialize_strategy_weight_patch_proposal(row)
    except Exception as exc:
        db.rollback()
        logger.warning("create strategy weight patch proposal failed: %s", exc)
        return {"status": "error", "audit_id": audit_id, "strategy_id": strategy_id, "error": str(exc)[:200]}
    finally:
        db.close()


def list_strategy_weight_patch_proposals(limit: int = 20, status: str | None = None) -> list[dict]:
    if not _has_table("strategy_weight_patch_proposals"):
        return []

    db = SessionLocal()
    try:
        query = db.query(StrategyWeightPatchProposal)
        if status:
            query = query.filter(StrategyWeightPatchProposal.status == status)
        rows = (
            query.order_by(StrategyWeightPatchProposal.created_at.desc(), StrategyWeightPatchProposal.id.desc())
            .limit(min(max(int(limit), 1), 100))
            .all()
        )
        return [_serialize_strategy_weight_patch_proposal(row) for row in rows]
    finally:
        db.close()


def decide_strategy_weight_patch_proposal(
    proposal_id: int,
    status: str,
    decided_by: int | None = None,
    notes: str | None = None,
) -> dict | None:
    if not _has_table("strategy_weight_patch_proposals"):
        return None
    clean_status = str(status or "").strip().lower()
    if clean_status not in {"approved", "rejected", "pending"}:
        return None

    db = SessionLocal()
    try:
        row = db.query(StrategyWeightPatchProposal).filter(StrategyWeightPatchProposal.id == proposal_id).first()
        if not row:
            return None
        row.status = clean_status
        if clean_status == "pending":
            row.decided_by = None
            row.decided_at = None
        else:
            row.decided_by = decided_by
            row.decided_at = datetime.now(timezone.utc)
        if notes is not None:
            row.notes = notes
        db.commit()
        return _serialize_strategy_weight_patch_proposal(row)
    except Exception as exc:
        db.rollback()
        logger.warning("decide strategy weight patch proposal failed: %s", exc)
        return None
    finally:
        db.close()


def apply_strategy_weight_patch_proposal(
    proposal_id: int,
    applied_by: int | None = None,
    notes: str | None = None,
) -> dict | None:
    if not _has_table("strategy_weight_patch_proposals"):
        return None

    db = SessionLocal()
    try:
        row = db.query(StrategyWeightPatchProposal).filter(StrategyWeightPatchProposal.id == proposal_id).first()
        if not row:
            return None
        if row.status != "approved":
            return _serialize_strategy_weight_patch_proposal(row)

        try:
            actual_before, actual_after = _write_strategy_weights(row.strategy_id, row.after_json or {})
        except Exception as exc:
            row.applied_error = str(exc)[:500]
            db.commit()
            return _serialize_strategy_weight_patch_proposal(row)

        now = datetime.now(timezone.utc)
        row.status = "applied"
        row.applied_by = applied_by
        row.applied_at = now
        row.applied_error = None
        if notes is not None:
            row.notes = notes
        if _has_table("strategy_weight_versions"):
            version = StrategyWeightVersion(
                strategy_id=row.strategy_id,
                proposal_id=row.id,
                version=_next_strategy_weight_version(db, row.strategy_id),
                before_json=actual_before,
                after_json=actual_after,
                applied_by=applied_by,
                applied_at=now,
                notes=notes,
                created_at=now,
            )
            db.add(version)
        db.commit()
        _load_all_strategies.cache_clear()
        return _serialize_strategy_weight_patch_proposal(row)
    except Exception as exc:
        db.rollback()
        logger.warning("apply strategy weight patch proposal failed: %s", exc)
        return None
    finally:
        db.close()


def list_strategy_weight_versions(strategy_id: str | None = None, limit: int = 20) -> list[dict]:
    if not _has_table("strategy_weight_versions"):
        return []

    db = SessionLocal()
    try:
        query = db.query(StrategyWeightVersion)
        clean_strategy_id = str(strategy_id or "").strip()
        if clean_strategy_id:
            query = query.filter(StrategyWeightVersion.strategy_id == clean_strategy_id)
        rows = (
            query.order_by(StrategyWeightVersion.created_at.desc(), StrategyWeightVersion.id.desc())
            .limit(min(max(int(limit), 1), 100))
            .all()
        )
        return [_serialize_strategy_weight_version(row) for row in rows]
    finally:
        db.close()


def rollback_strategy_weight_version(
    version_id: int,
    rolled_back_by: int | None = None,
    notes: str | None = None,
) -> dict | None:
    if not _has_table("strategy_weight_versions"):
        return None

    db = SessionLocal()
    try:
        row = db.query(StrategyWeightVersion).filter(StrategyWeightVersion.id == version_id).first()
        if not row:
            return None
        if row.rolled_back_at:
            return _serialize_strategy_weight_version(row)

        try:
            _write_strategy_weights(row.strategy_id, row.before_json or {})
        except Exception as exc:
            row.rollback_error = str(exc)[:500]
            db.commit()
            return _serialize_strategy_weight_version(row)

        row.rolled_back_by = rolled_back_by
        row.rolled_back_at = datetime.now(timezone.utc)
        row.rollback_error = None
        if notes is not None:
            row.notes = notes
        db.commit()
        _load_all_strategies.cache_clear()
        return _serialize_strategy_weight_version(row)
    except Exception as exc:
        db.rollback()
        logger.warning("rollback strategy weight version failed: %s", exc)
        return None
    finally:
        db.close()


async def preview_strategy_weight_proposal_impact(
    proposal_id: int,
    *,
    market: str = "ALL",
    limit: int = 20,
    candidate_limit: int = 60,
    concurrency: int = 8,
) -> dict:
    if not _has_table("strategy_weight_patch_proposals"):
        return {"status": "tables_missing", "proposal_id": proposal_id, "items": []}

    db = SessionLocal()
    try:
        row = db.query(StrategyWeightPatchProposal).filter(StrategyWeightPatchProposal.id == proposal_id).first()
        if not row:
            return {"status": "proposal_not_found", "proposal_id": proposal_id, "items": []}
        proposal = _serialize_strategy_weight_patch_proposal(row)
    finally:
        db.close()

    before_weights = proposal.get("before") or {}
    after_weights = proposal.get("after") or {}
    if not isinstance(before_weights, dict) or not isinstance(after_weights, dict) or not after_weights:
        return {"status": "proposal_weights_missing", "proposal_id": proposal_id, "items": []}

    from backend.services.analysis_service.engine.research_pipeline import run_research_pipeline

    sample_limit = min(max(int(limit), 1), 50)
    sample_candidate_limit = min(max(int(candidate_limit), sample_limit), 200)
    result = await run_research_pipeline(
        market=market,
        limit=sample_limit,
        requested_strategy=str(proposal.get("strategy_id") or "retail_small"),
        candidate_limit=sample_candidate_limit,
        concurrency=min(max(int(concurrency), 1), 32),
        run_initial_full_scan=False,
        include_evidence=False,
        include_debate=False,
    )
    recommendations = list(result.get("recommendations") or [])
    before_strategy = {
        "id": proposal.get("strategy_id"),
        "weights": before_weights,
    }
    after_strategy = {
        "id": proposal.get("strategy_id"),
        "weights": after_weights,
    }
    before_ranked = _rank_preview_items(recommendations, before_strategy)
    after_ranked = _rank_preview_items(recommendations, after_strategy)
    before_by_symbol = {item["symbol"]: item for item in before_ranked}
    after_by_symbol = {item["symbol"]: item for item in after_ranked}
    items: list[dict] = []

    for symbol, after_item in after_by_symbol.items():
        before_item = before_by_symbol.get(symbol) or {}
        items.append(
            {
                "symbol": symbol,
                "name": after_item.get("name") or before_item.get("name"),
                "before_rank": before_item.get("rank"),
                "after_rank": after_item.get("rank"),
                "rank_delta": (
                    int(before_item["rank"]) - int(after_item["rank"])
                    if before_item.get("rank") is not None and after_item.get("rank") is not None
                    else None
                ),
                "base_score": after_item.get("base_score") or before_item.get("base_score"),
                "before_score": before_item.get("strategy_score"),
                "after_score": after_item.get("strategy_score"),
                "score_delta": (
                    int(after_item["strategy_score"]) - int(before_item["strategy_score"])
                    if before_item.get("strategy_score") is not None and after_item.get("strategy_score") is not None
                    else None
                ),
            }
        )

    items.sort(key=lambda item: (item.get("after_rank") or 9999, item.get("before_rank") or 9999))
    changed = [item for item in items if item.get("rank_delta") or item.get("score_delta")]
    return {
        "status": "ok",
        "proposal_id": proposal_id,
        "strategy_id": proposal.get("strategy_id"),
        "market": market,
        "sample_count": len(items),
        "changed_count": len(changed),
        "candidate_limit": sample_candidate_limit,
        "items": items,
        "selection": result.get("selection") or {},
        "warnings": result.get("warnings") or [],
    }


def _rank_preview_items(items: list[dict], strategy: dict) -> list[dict]:
    ranked: list[dict] = []
    for item in items:
        scored = apply_strategy_weighted_score(
            {
                **item,
                "score": item.get("base_score", item.get("score")),
            },
            strategy,
        )
        ranked.append(scored)
    ranked.sort(
        key=lambda x: (
            x.get("strategy_score", x.get("score", 0)),
            (x.get("data_grade") or {}).get("grade") == "A",
            -len(x.get("risk_flags", [])),
        ),
        reverse=True,
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked


def _next_strategy_weight_version(db, strategy_id: str) -> int:
    try:
        latest = (
            db.query(StrategyWeightVersion)
            .filter(StrategyWeightVersion.strategy_id == strategy_id)
            .order_by(StrategyWeightVersion.version.desc(), StrategyWeightVersion.id.desc())
            .first()
        )
        return int(getattr(latest, "version", 0) or 0) + 1
    except Exception:
        return 1


def _write_strategy_weights(strategy_id: str, weights: dict) -> tuple[dict, dict]:
    clean_strategy_id = str(strategy_id or "").strip()
    if not clean_strategy_id or clean_strategy_id in {"auto", ".."} or "/" in clean_strategy_id or "\\" in clean_strategy_id:
        raise ValueError("invalid strategy id")
    normalized = _normalize_weights(weights)
    if not normalized:
        raise ValueError("proposal after weights are empty")

    strategy_path = (_STRATEGY_CONFIG_DIR / f"{clean_strategy_id}.json").resolve()
    config_dir = _STRATEGY_CONFIG_DIR.resolve()
    if config_dir not in strategy_path.parents:
        raise ValueError("strategy path escapes config directory")
    if not strategy_path.exists():
        raise FileNotFoundError(f"strategy config not found: {clean_strategy_id}")

    payload = json.loads(strategy_path.read_text(encoding="utf-8"))
    if str(payload.get("id") or strategy_path.stem) != clean_strategy_id:
        raise ValueError("strategy id mismatch")
    before = _normalize_weights(payload.get("weights"))
    payload["weights"] = normalized
    strategy_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return before, normalized


def _iso_date(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def build_recent_review_summaries(
    symbols: list[str],
    strategy: str = "auto",
    offsets: tuple[str, ...] = VALID_REVIEW_OFFSETS,
    limit_per_symbol: int = 1,
) -> dict:
    clean_symbols = [symbol.strip() for symbol in symbols if symbol and symbol.strip()]
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return {"status": "tables_missing", "items": {}, "missing_symbols": clean_symbols}

    limit = min(max(int(limit_per_symbol), 1), 5)
    requested_offsets = tuple(offset for offset in offsets if offset in VALID_REVIEW_OFFSETS)
    if not clean_symbols:
        return {"status": "ok", "items": {}, "missing_symbols": []}

    db = SessionLocal()
    try:
        query = db.query(ResearchObservation).filter(ResearchObservation.symbol.in_(clean_symbols))
        if strategy and strategy != "auto":
            query = query.filter(ResearchObservation.strategy_id == strategy)
        observations = query.order_by(ResearchObservation.snapshot_date.desc(), ResearchObservation.id.desc()).all()

        selected: dict[str, list[ResearchObservation]] = {symbol: [] for symbol in clean_symbols}
        selected_ids: list[int] = []
        for observation in observations:
            bucket = selected.setdefault(observation.symbol, [])
            if len(bucket) >= limit:
                continue
            bucket.append(observation)
            selected_ids.append(observation.id)

        reviews_by_observation: dict[int, dict[str, ObservationReview]] = {}
        if selected_ids:
            review_rows = (
                db.query(ObservationReview)
                .filter(
                    ObservationReview.observation_id.in_(selected_ids),
                    ObservationReview.review_offset.in_(requested_offsets),
                )
                .all()
            )
            for review in review_rows:
                reviews_by_observation.setdefault(review.observation_id, {})[review.review_offset] = review

        items: dict[str, dict] = {}
        for symbol in clean_symbols:
            rows = []
            for observation in selected.get(symbol, []):
                review_map = reviews_by_observation.get(observation.id, {})
                rows.append(
                    {
                        "latest_snapshot_date": _iso_date(observation.snapshot_date),
                        "strategy_id": observation.strategy_id,
                        "base_price": observation.close_price,
                        "reviews": {
                            offset: _serialize_review(review_map.get(offset))
                            for offset in requested_offsets
                        },
                    }
                )
            if rows:
                items[symbol] = rows[0] if limit == 1 else {"latest": rows[0], "history": rows}

        return {
            "status": "ok",
            "items": items,
            "missing_symbols": [symbol for symbol in clean_symbols if not selected.get(symbol)],
        }
    finally:
        db.close()


def _serialize_review(review: ObservationReview | None) -> dict | None:
    if review is None:
        return None
    return {
        "review_date": _iso_date(review.review_date),
        "close_price": review.close_price,
        "return_pct": review.return_pct,
        "max_drawdown_pct": review.max_drawdown_pct,
        "falsification_triggered": bool(review.falsification_triggered),
        "risk_signal_valid": bool(review.risk_signal_valid),
        "notes": review.notes,
    }
