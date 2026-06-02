from __future__ import annotations

import logging
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import inspect

from backend.shared.database import engine
from backend.shared.database import SessionLocal
from backend.shared.models import (
    DailySnapshot,
    ObservationReview,
    PipelineRunLog,
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
# Confounding guard: a factor that appears in nearly every pick (high coverage)
# but whose win rate barely beats the pool baseline (low lift) is not a signal —
# it just inherits the pool average. Such factors must not drive weight changes.
_CONFOUND_COVERAGE_THRESHOLD = 0.85  # appears in >=85% of evaluated reviews
_CONFOUND_LIFT_THRESHOLD = 0.05      # win-rate lift over baseline within +/-5pp
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


def _historical_close_on_or_before(db, symbol: str, review_date: date, tolerance_days: int = 4) -> float | None:
    """Return the DailySnapshot close for review_date, or the nearest prior trading day.

    Reviews must be reproducible: the recorded price has to be the close on the
    review day, not whatever the realtime quote happens to be when the job runs.
    A small backward tolerance absorbs weekends/holidays (review_date may be a
    calendar day with no bar). Same data source the drawdown calc already uses.
    """
    lower_bound = (review_date - timedelta(days=tolerance_days)).isoformat()
    row = (
        db.query(DailySnapshot)
        .filter(
            DailySnapshot.symbol == symbol,
            DailySnapshot.trade_date >= lower_bound,
            DailySnapshot.trade_date <= review_date.isoformat(),
        )
        .order_by(DailySnapshot.trade_date.desc())
        .first()
    )
    if not row:
        return None
    value = row.close if row.close not in (None, 0) else None
    return float(value) if value not in (None, 0) else None


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

            historical_close = _historical_close_on_or_before(db, item["symbol"], review_date)
            base_price = observation.close_price
            price_source = "daily_snapshot"
            quote_source = ""
            if historical_close not in (None, 0):
                review_price = historical_close
            else:
                # No historical bar for the review day — fall back to a realtime
                # quote so the review is not silently dropped, but mark it as
                # non-reproducible so downstream stats can treat it with caution.
                quote = await fetch_quote(item["symbol"])
                review_price = quote.get("price")
                quote_source = str(quote.get("source") or "unknown")
                price_source = "realtime_quote_fallback"

            return_pct = None
            if base_price not in (None, 0) and review_price not in (None, 0):
                try:
                    return_pct = round((float(review_price) - float(base_price)) / float(base_price) * 100, 4)
                except (TypeError, ValueError, ZeroDivisionError):
                    return_pct = None

            note_source = "daily_snapshot" if price_source == "daily_snapshot" else f"realtime_quote:{quote_source}"
            row = ObservationReview(
                observation_id=observation.id,
                review_offset=item["review_offset"],
                review_date=datetime.combine(review_date, datetime.min.time(), tzinfo=timezone.utc),
                close_price=review_price,
                return_pct=return_pct,
                max_drawdown_pct=_calculate_max_drawdown_pct(db, observation, review_date),
                falsification_triggered=_falsification_triggered(observation, base_price, review_price),
                risk_signal_valid=_risk_signal_valid(observation, return_pct),
                notes=f"price_source={price_source} source={note_source}",
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
                    "price_source": price_source,
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


def _observation_tier(observation: ResearchObservation) -> str:
    """Extract the A/B/C tier stored in factor_snapshot_json, defaulting to C.

    Matches the scorecard convention so tier-level win rates are consistent
    across both reports.
    """
    snapshot = getattr(observation, "factor_snapshot_json", None)
    if isinstance(snapshot, dict):
        tier = snapshot.get("tier")
        if tier:
            return str(tier)
    return "C"


def build_review_report(snapshot_from: date | None = None, snapshot_to: date | None = None) -> dict:
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return {"status": "tables_missing", "summary": {}, "by_strategy": [], "by_offset": []}

    db = SessionLocal()
    try:
        reviews = db.query(ObservationReview).all()
        observations = {row.id: row for row in db.query(ResearchObservation).all()}
        rows = _filtered_review_rows(observations, reviews, snapshot_from, snapshot_to)

        by_strategy: dict[str, dict] = {}
        by_tier: dict[str, dict] = {}
        by_offset: dict[str, dict] = {}
        total_returns: list[float] = []
        total_positive = 0
        for observation, review in rows:
            strategy_id = observation.strategy_id
            bucket = by_strategy.setdefault(
                strategy_id,
                {
                    "strategy_id": strategy_id,
                    "reviews": 0,
                    "evaluated_reviews": 0,
                    "positive_reviews": 0,
                    "avg_return_pct": 0.0,
                    "falsification_triggered": 0,
                    "risk_signal_valid": 0,
                },
            )
            tier = _observation_tier(observation)
            tier_bucket = by_tier.setdefault(
                tier,
                {
                    "tier": tier,
                    "reviews": 0,
                    "evaluated_reviews": 0,
                    "positive_reviews": 0,
                    "avg_return_pct": 0.0,
                    "falsification_triggered": 0,
                    "risk_signal_valid": 0,
                },
            )
            grouped = (bucket, tier_bucket)
            for group in grouped:
                group["reviews"] += 1
            offset = getattr(review, "review_offset", None) or "unknown"
            offset_bucket = by_offset.setdefault(
                offset,
                {
                    "review_offset": offset,
                    "reviews": 0,
                    "evaluated_reviews": 0,
                    "positive_reviews": 0,
                    "return_total": 0.0,
                },
            )
            offset_bucket["reviews"] += 1
            if review.return_pct is not None:
                return_pct = float(review.return_pct)
                total_returns.append(return_pct)
                offset_bucket["evaluated_reviews"] += 1
                offset_bucket["return_total"] += return_pct
                for group in grouped:
                    group["avg_return_pct"] += return_pct
                    group["evaluated_reviews"] += 1
                if return_pct > 0:
                    offset_bucket["positive_reviews"] += 1
                    total_positive += 1
                    for group in grouped:
                        group["positive_reviews"] += 1
            if review.falsification_triggered:
                for group in grouped:
                    group["falsification_triggered"] += 1
            if review.risk_signal_valid:
                for group in grouped:
                    group["risk_signal_valid"] += 1

        result_rows = []
        for bucket in by_strategy.values():
            evaluated = int(bucket["evaluated_reviews"])
            result_rows.append(
                {
                    **bucket,
                    "win_rate": round(bucket["positive_reviews"] / evaluated, 4) if evaluated else None,
                    "avg_return_pct": round(bucket["avg_return_pct"] / evaluated, 4) if evaluated else None,
                }
            )

        tier_order = {"A": 1, "B": 2, "C": 3}
        tier_rows = []
        for bucket in by_tier.values():
            evaluated = int(bucket["evaluated_reviews"])
            tier_rows.append(
                {
                    **bucket,
                    "win_rate": round(bucket["positive_reviews"] / evaluated, 4) if evaluated else None,
                    "avg_return_pct": round(bucket["avg_return_pct"] / evaluated, 4) if evaluated else None,
                }
            )

        offset_order = {"T+1": 1, "T+5": 2, "T+20": 3}
        offset_rows = []
        for bucket in by_offset.values():
            evaluated = int(bucket["evaluated_reviews"])
            offset_rows.append(
                {
                    "review_offset": bucket["review_offset"],
                    "reviews": int(bucket["reviews"]),
                    "evaluated_reviews": evaluated,
                    "positive_reviews": int(bucket["positive_reviews"]),
                    "win_rate": round(bucket["positive_reviews"] / evaluated, 4) if evaluated else None,
                    "avg_return_pct": round(bucket["return_total"] / evaluated, 4) if evaluated else None,
                }
            )

        return {
            "status": "ok",
            "summary": {
                "reviews": len(rows),
                "evaluated_reviews": len(total_returns),
                "positive_reviews": total_positive,
                "strategies": len(result_rows),
                "tiers": len(tier_rows),
                "win_rate": round(total_positive / len(total_returns), 4) if total_returns else None,
                "avg_return_pct": round(sum(total_returns) / len(total_returns), 4) if total_returns else None,
            },
            "by_strategy": sorted(result_rows, key=lambda item: item["reviews"], reverse=True),
            "by_tier": sorted(tier_rows, key=lambda item: tier_order.get(item["tier"], 99)),
            "by_offset": sorted(offset_rows, key=lambda item: offset_order.get(item["review_offset"], 99)),
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


def _expected_trading_days(start: date, end: date) -> list[str]:
    """Weekday calendar between start and end inclusive (Mon–Fri).

    A coarse proxy for trading days — it does not know A-share public holidays,
    so a holiday shows up as an expected-but-missing day. That over-reports gaps
    rather than hiding them, which is the safe direction for a health check.
    """
    if start > end:
        return []
    days: list[str] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def _price_source_from_notes(notes: str | None) -> str:
    text = str(notes or "")
    if "price_source=daily_snapshot" in text:
        return "daily_snapshot"
    if "price_source=realtime_quote_fallback" in text:
        return "realtime_quote_fallback"
    # Legacy rows written before the reproducible-pricing change only carried
    # "source=..." — treat them as unknown rather than miscount them as clean.
    return "legacy_unknown"


def build_data_foundation_health(lookback_days: int = 30) -> dict:
    """Health check for the observation-pool data foundation.

    Surfaces the three things that determine whether the pool accumulates clean,
    reproducible data day over day:
      1. pipeline-run continuity — missing run days mean missing observations
         (and offsets match on exact calendar deltas, so a missed day is a
         permanently un-reviewed cohort).
      2. observation accumulation — how many observation-days actually landed.
      3. price-source reproducibility — share of reviews priced from historical
         closes vs realtime-quote fallbacks vs legacy unknown rows.
    """
    tables = {
        "pipeline_run_logs": _has_table("pipeline_run_logs"),
        "research_observations": _has_table("research_observations"),
        "observation_reviews": _has_table("observation_reviews"),
    }
    today = date.today()
    window_start = today - timedelta(days=max(int(lookback_days), 1))

    db = SessionLocal()
    try:
        # 1. Pipeline-run continuity
        run_continuity: dict = {"status": "tables_missing"}
        if tables["pipeline_run_logs"]:
            runs = (
                db.query(PipelineRunLog)
                .filter(PipelineRunLog.run_date >= window_start.isoformat())
                .all()
            )
            run_by_date = {str(row.run_date): row for row in runs}
            successful = {d for d, row in run_by_date.items() if row.status in ("success", "no_data")}
            run_dates = sorted(run_by_date)
            earliest = date.fromisoformat(run_dates[0]) if run_dates else window_start
            expected = _expected_trading_days(earliest, today)
            missing = [d for d in expected if d not in run_by_date]
            failed = sorted(d for d, row in run_by_date.items() if row.status not in ("success", "no_data", "running"))
            run_continuity = {
                "status": "ok",
                "window_from": earliest.isoformat(),
                "window_to": today.isoformat(),
                "expected_trading_days": len(expected),
                "runs_recorded": len(run_by_date),
                "successful_runs": len(successful),
                "missing_days": missing[:20],
                "missing_day_count": len(missing),
                "failed_days": failed[:20],
                "failed_day_count": len(failed),
                "continuity_rate": round(len(successful) / len(expected), 4) if expected else None,
            }

        # 2. Observation accumulation
        observation_stats: dict = {"status": "tables_missing"}
        if tables["research_observations"]:
            observations = (
                db.query(ResearchObservation)
                .filter(ResearchObservation.snapshot_date >= datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc))
                .all()
            )
            obs_days = {row.snapshot_date.date().isoformat() for row in observations if row.snapshot_date}
            observation_stats = {
                "status": "ok",
                "observations": len(observations),
                "observation_days": len(obs_days),
                "avg_per_day": round(len(observations) / len(obs_days), 2) if obs_days else 0.0,
                "latest_observation_date": max(obs_days) if obs_days else None,
            }

        # 3. Price-source reproducibility
        price_quality: dict = {"status": "tables_missing"}
        if tables["observation_reviews"]:
            reviews = (
                db.query(ObservationReview)
                .filter(ObservationReview.review_date >= datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc))
                .all()
            )
            counts = {"daily_snapshot": 0, "realtime_quote_fallback": 0, "legacy_unknown": 0}
            for review in reviews:
                counts[_price_source_from_notes(review.notes)] += 1
            total = sum(counts.values())
            reproducible = counts["daily_snapshot"]
            price_quality = {
                "status": "ok",
                "reviews": total,
                "by_source": counts,
                "reproducible_rate": round(reproducible / total, 4) if total else None,
            }
    finally:
        db.close()

    # Roll up an overall verdict for quick scanning.
    issues: list[str] = []
    if run_continuity.get("status") == "ok" and run_continuity.get("missing_day_count"):
        issues.append(f"{run_continuity['missing_day_count']} 个交易日缺少 pipeline 运行")
    if run_continuity.get("status") == "ok" and run_continuity.get("failed_day_count"):
        issues.append(f"{run_continuity['failed_day_count']} 个交易日 pipeline 运行失败")
    if price_quality.get("status") == "ok":
        rate = price_quality.get("reproducible_rate")
        if rate is not None and rate < 1.0 and price_quality.get("reviews"):
            issues.append(f"复盘价可复现率 {rate:.0%}（其余来自实时报价回退或历史遗留）")

    if not all(tables.values()):
        verdict = "tables_missing"
    elif issues:
        verdict = "degraded"
    else:
        verdict = "healthy"

    return {
        "status": verdict,
        "as_of": today.isoformat(),
        "lookback_days": int(lookback_days),
        "tables": tables,
        "run_continuity": run_continuity,
        "observation_accumulation": observation_stats,
        "price_source_quality": price_quality,
        "issues": issues,
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
        "win_rate": round(bucket["positive_reviews"] / return_count, 4) if return_count else None,
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


def _annotate_confounding(item: dict, baseline_win_rate: float | None) -> dict:
    """Tag a factor row with its win-rate lift over the pool baseline.

    A factor's raw win rate is confounded: because every factor on an
    observation is bound to the same return, a factor present in nearly all
    picks just inherits the pool average. ``win_rate_lift`` isolates the part
    that is actually attributable to the factor, and ``confounded`` flags rows
    that are high-coverage but indistinguishable from baseline — these must not
    drive weight changes.
    """
    win_rate = item.get("win_rate")
    coverage = _safe_float(item.get("coverage_rate"), 0.0)
    if win_rate is None or baseline_win_rate is None:
        item["baseline_win_rate"] = baseline_win_rate
        item["win_rate_lift"] = None
        item["confounded"] = False
        return item
    lift = round(_safe_float(win_rate) - baseline_win_rate, 4)
    item["baseline_win_rate"] = baseline_win_rate
    item["win_rate_lift"] = lift
    item["confounded"] = (
        coverage >= _CONFOUND_COVERAGE_THRESHOLD and abs(lift) < _CONFOUND_LIFT_THRESHOLD
    )
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
        baseline_positive = 0
        baseline_evaluated = 0
        for observation, review in rows:
            if review.return_pct is not None:
                baseline_evaluated += 1
                if float(review.return_pct) > 0:
                    baseline_positive += 1
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

        baseline_win_rate = round(baseline_positive / baseline_evaluated, 4) if baseline_evaluated else None
        result_rows = [_annotate_confounding(_serialize_factor_bucket(bucket, len(rows)), baseline_win_rate) for bucket in by_factor.values()]
        regime_rows = [_annotate_confounding(_serialize_factor_bucket(bucket, len(rows)), baseline_win_rate) for bucket in by_regime_factor.values()]

        return {
            "status": "ok",
            "summary": {
                "factors": len(result_rows),
                "reviews": len(rows),
                "regime_factors": len(regime_rows),
                "baseline_win_rate": baseline_win_rate,
                "baseline_evaluated_reviews": baseline_evaluated,
            },
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
    avg_return_pct = item.get("avg_return_pct")
    # No evaluated outcomes (all reviews lack return_pct) — outcome is unknown,
    # so hold instead of penalizing the factor for missing price data.
    if item.get("win_rate") is None and avg_return_pct is None:
        return "hold"
    win_rate = _safe_float(item.get("win_rate"), 0.0)
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
    confounded_held = 0
    for item in report.get("by_factor", []):
        reviews = int(item.get("reviews") or 0)
        if reviews < min_reviews:
            continue

        is_confounded = bool(item.get("confounded"))
        if is_confounded:
            # High coverage, negligible lift over baseline: the win rate is not
            # attributable to this factor. Hold and say why, rather than letting
            # a confounded number move the weight.
            action = "hold"
            confidence = "low"
            lift = item.get("win_rate_lift")
            lift_text = "n/a" if lift is None else f"{_safe_float(lift) * 100:.1f}pp"
            reason = (
                f"coverage={_safe_float(item.get('coverage_rate')) * 100:.0f}% with win-rate lift {lift_text} "
                f"over baseline — indistinguishable from the pool average (confounded); hold until attribution improves."
            )
        else:
            action = _weight_suggestion_action(item)
            confidence = _weight_suggestion_confidence(item, action)
            reason = _weight_suggestion_reason(item, action)

        if is_confounded:
            confounded_held += 1
        suggestions.append(
            {
                "factor": str(item.get("factor") or "unknown"),
                "label": str(item.get("label") or item.get("factor") or "unknown"),
                "action": action,
                "confidence": confidence,
                "reason": reason,
                "confounded": is_confounded,
                "metrics": {
                    "reviews": reviews,
                    "win_rate": _safe_float(item.get("win_rate"), 0.0),
                    "baseline_win_rate": item.get("baseline_win_rate"),
                    "win_rate_lift": item.get("win_rate_lift"),
                    "coverage_rate": _safe_float(item.get("coverage_rate"), 0.0),
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
            "confounded_held": confounded_held,
            "baseline_win_rate": (report.get("summary") or {}).get("baseline_win_rate"),
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


# ── Pool Scorecard ──


_SCORECARD_SAMPLE_THRESHOLD = 10
_SCORECARD_BENCHMARK_SYMBOL = "000300.SH"
_SCORECARD_OFFSETS = ("T+1", "T+5", "T+20")


def _find_nearest_close(date_map: dict[str, float], target_date: str, tolerance: int = 3) -> float | None:
    if target_date in date_map:
        return date_map[target_date]
    try:
        base = date.fromisoformat(target_date)
    except ValueError:
        return None
    for delta in range(1, tolerance + 1):
        for direction in (-1, 1):
            candidate = (base + timedelta(days=delta * direction)).isoformat()
            if candidate in date_map:
                return date_map[candidate]
    return None


def _build_scorecard_bucket(returns: list[float], excess_returns: list[float | None], drawdowns: list[float]) -> dict:
    reviews_count = len(returns)
    if reviews_count < _SCORECARD_SAMPLE_THRESHOLD:
        return {
            "reviews": reviews_count,
            "win_rate": None,
            "avg_return_pct": None,
            "avg_excess_pct": None,
            "worst_return_pct": None,
            "max_drawdown_pct": None,
        }
    positive = sum(1 for r in returns if r > 0)
    valid_excess = [e for e in excess_returns if e is not None]
    return {
        "reviews": reviews_count,
        "win_rate": round(positive / reviews_count, 4),
        "avg_return_pct": round(sum(returns) / reviews_count, 4),
        "avg_excess_pct": round(sum(valid_excess) / len(valid_excess), 4) if valid_excess else None,
        "worst_return_pct": round(min(returns), 4),
        "max_drawdown_pct": round(min(drawdowns), 4) if drawdowns else None,
    }


async def build_pool_scorecard(lookback_days: int = 90, strategy: str = "auto") -> dict:
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return {"status": "tables_missing", "lookback_days": lookback_days, "disclaimer": "历史统计不代表未来表现，不构成投资建议"}

    from backend.shared.cache import get_cache_manager

    cache = await get_cache_manager()
    cache_key = f"scorecard:{strategy}:{lookback_days}"
    cached = await cache.get("pool_scorecard", cache_key)
    if cached is not None:
        return cached

    from backend.services.analysis_service.engine.scoring_data import fetch_recent_kline

    benchmark_map: dict[str, float] = {}
    benchmark_status = "ok"
    try:
        kline = await fetch_recent_kline(_SCORECARD_BENCHMARK_SYMBOL, count=lookback_days + 60)
        for row in kline:
            trade_date = str(row.get("trade_date") or row.get("date") or "").strip()[:10]
            close = row.get("close")
            if trade_date and close:
                try:
                    benchmark_map[trade_date] = float(close)
                except (TypeError, ValueError):
                    pass
    except Exception as exc:
        logger.warning("Scorecard benchmark fetch failed: %s", exc)
        benchmark_status = "unavailable"

    db = SessionLocal()
    try:
        cutoff = datetime.combine(date.today() - timedelta(days=lookback_days), datetime.min.time(), tzinfo=timezone.utc)

        query = db.query(ResearchObservation, ObservationReview).join(
            ObservationReview, ObservationReview.observation_id == ResearchObservation.id
        ).filter(
            ResearchObservation.snapshot_date >= cutoff,
            ObservationReview.return_pct.isnot(None),
        )

        if strategy and strategy != "auto":
            from backend.services.analysis_service.engine.strategy_config import _ALIASES
            resolved = _ALIASES.get(strategy.strip().lower(), strategy.strip().lower())
            query = query.filter(ResearchObservation.strategy_id == resolved)

        rows = query.all()

        if not rows:
            result = {
                "status": "insufficient_data",
                "lookback_days": lookback_days,
                "as_of": date.today().isoformat(),
                "strategy": strategy,
                "benchmark": _SCORECARD_BENCHMARK_SYMBOL,
                "benchmark_status": benchmark_status,
                "overall": {},
                "by_tier": {},
                "sample_threshold": _SCORECARD_SAMPLE_THRESHOLD,
                "disclaimer": "历史统计不代表未来表现，不构成投资建议",
            }
            await cache.set("pool_scorecard", cache_key, value=result, ttl=timedelta(hours=1))
            return result

        buckets: dict[tuple[str, str], dict] = {}
        for observation, review in rows:
            factor_snapshot = observation.factor_snapshot_json if isinstance(observation.factor_snapshot_json, dict) else {}
            tier = factor_snapshot.get("tier") or "C"
            offset = review.review_offset

            if offset not in _SCORECARD_OFFSETS:
                continue

            stock_return = float(review.return_pct)

            snapshot_date_str = observation.snapshot_date.strftime("%Y-%m-%d") if observation.snapshot_date else ""
            review_date_str = review.review_date.strftime("%Y-%m-%d") if review.review_date else ""

            excess: float | None = None
            if benchmark_map and snapshot_date_str and review_date_str:
                bench_start = _find_nearest_close(benchmark_map, snapshot_date_str)
                bench_end = _find_nearest_close(benchmark_map, review_date_str)
                if bench_start and bench_end and bench_start > 0:
                    bench_return = (bench_end / bench_start - 1) * 100
                    excess = stock_return - bench_return

            drawdown = float(review.max_drawdown_pct) if review.max_drawdown_pct is not None else None

            for key in [(tier, offset), ("ALL", offset)]:
                bucket = buckets.setdefault(key, {"returns": [], "excess": [], "drawdowns": []})
                bucket["returns"].append(stock_return)
                bucket["excess"].append(excess)
                if drawdown is not None:
                    bucket["drawdowns"].append(drawdown)

        by_tier: dict[str, dict] = {}
        for tier_label in ("A", "B", "C"):
            tier_data: dict[str, dict] = {}
            for offset in _SCORECARD_OFFSETS:
                bucket = buckets.get((tier_label, offset))
                if bucket:
                    tier_data[offset] = _build_scorecard_bucket(bucket["returns"], bucket["excess"], bucket["drawdowns"])
                else:
                    tier_data[offset] = _build_scorecard_bucket([], [], [])
            by_tier[tier_label] = tier_data

        overall: dict[str, dict] = {}
        for offset in _SCORECARD_OFFSETS:
            bucket = buckets.get(("ALL", offset))
            if bucket:
                overall[offset] = _build_scorecard_bucket(bucket["returns"], bucket["excess"], bucket["drawdowns"])
            else:
                overall[offset] = _build_scorecard_bucket([], [], [])

        resolved_strategy = strategy
        if rows:
            resolved_strategy = rows[0][0].strategy_id or strategy

        result = {
            "status": "ok",
            "lookback_days": lookback_days,
            "as_of": date.today().isoformat(),
            "strategy": resolved_strategy,
            "benchmark": _SCORECARD_BENCHMARK_SYMBOL,
            "benchmark_status": benchmark_status,
            "overall": overall,
            "by_tier": by_tier,
            "sample_threshold": _SCORECARD_SAMPLE_THRESHOLD,
            "disclaimer": "历史统计不代表未来表现，不构成投资建议",
        }
        await cache.set("pool_scorecard", cache_key, value=result, ttl=timedelta(hours=1))
        return result
    finally:
        db.close()


# ── Pool Simulation (admin-only) ──
#
# A deterministic, low-fidelity execution simulation built on existing reviews.
# It measures what the pool would have returned under the system's OWN discipline
# (stop out at the falsification line) versus naive buy-and-hold, so the win rate
# reflects how the product is actually meant to be used rather than passive holding.
#
# Intentionally NOT a curve-fit: the stop is locked to the existing -10%
# falsification threshold, never tuned to flatter the numbers. Outputs expectancy
# and payoff ratio alongside win rate because win rate alone hides small-win/
# big-loss strategies with negative expectancy.

_SIMULATION_SAMPLE_THRESHOLD = 10
_SIMULATION_OFFSETS = ("T+1", "T+5", "T+20")
_SIMULATION_STOP_LOSS_PCT = -10.0  # mirrors _falsification_triggered (review_price <= base * 0.9)


def _discipline_exit_return(return_pct: float, max_drawdown_pct: float | None) -> tuple[float, bool]:
    """Return (exit_return_pct, stopped) under the -10% discipline rule.

    If the path drew down to the stop at any point, the position is closed at the
    stop (a deliberately conservative model — it does not assume you got out at
    exactly -10%, it assumes the stop cost you the full -10% even if it later
    recovered). Otherwise the position is held to the offset and exits at T+N.
    """
    if max_drawdown_pct is not None and float(max_drawdown_pct) <= _SIMULATION_STOP_LOSS_PCT:
        return _SIMULATION_STOP_LOSS_PCT, True
    return float(return_pct), False


def _simulation_bucket(returns: list[float]) -> dict:
    n = len(returns)
    if n < _SIMULATION_SAMPLE_THRESHOLD:
        return {
            "trades": n,
            "win_rate": None,
            "avg_return_pct": None,
            "expectancy_pct": None,
            "payoff_ratio": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
            "worst_return_pct": None,
        }
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0  # negative or 0
    win_rate = len(wins) / n
    expectancy = sum(returns) / n  # mean return per trade == win_rate*avg_win + loss_rate*avg_loss
    payoff_ratio = round(avg_win / abs(avg_loss), 4) if avg_loss < 0 else None
    return {
        "trades": n,
        "win_rate": round(win_rate, 4),
        "avg_return_pct": round(expectancy, 4),
        "expectancy_pct": round(expectancy, 4),
        "payoff_ratio": payoff_ratio,
        "avg_win_pct": round(avg_win, 4) if wins else None,
        "avg_loss_pct": round(avg_loss, 4) if losses else None,
        "worst_return_pct": round(min(returns), 4),
    }


def _simulation_arm(returns: list[float]) -> dict:
    """One arm (discipline or buy_hold) summarized with its overall bucket."""
    return _simulation_bucket(returns)


def build_pool_simulation(lookback_days: int = 90, strategy: str = "auto") -> dict:
    """Admin-only execution simulation: discipline (-10% stop) vs buy-and-hold.

    Deterministic and reproducible — reads only stored reviews, no realtime IO.
    Returns per-offset, per-tier metrics for both arms plus the discipline delta.
    """
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return {
            "status": "tables_missing",
            "lookback_days": lookback_days,
            "disclaimer": "历史模拟不代表未来表现，不构成投资建议",
        }

    db = SessionLocal()
    try:
        cutoff = datetime.combine(date.today() - timedelta(days=lookback_days), datetime.min.time(), tzinfo=timezone.utc)
        query = db.query(ResearchObservation, ObservationReview).join(
            ObservationReview, ObservationReview.observation_id == ResearchObservation.id
        ).filter(
            ResearchObservation.snapshot_date >= cutoff,
            ObservationReview.return_pct.isnot(None),
        )
        if strategy and strategy != "auto":
            from backend.services.analysis_service.engine.strategy_config import _ALIASES
            resolved = _ALIASES.get(strategy.strip().lower(), strategy.strip().lower())
            query = query.filter(ResearchObservation.strategy_id == resolved)

        rows = query.all()
        if not rows:
            return {
                "status": "insufficient_data",
                "lookback_days": lookback_days,
                "as_of": date.today().isoformat(),
                "strategy": strategy,
                "overall": {},
                "by_tier": {},
                "sample_threshold": _SIMULATION_SAMPLE_THRESHOLD,
                "stop_loss_pct": _SIMULATION_STOP_LOSS_PCT,
                "disclaimer": "历史模拟不代表未来表现，不构成投资建议",
            }

        # key -> {"discipline": [...], "buy_hold": [...], "stopped": int}
        buckets: dict[tuple[str, str], dict] = {}
        for observation, review in rows:
            offset = review.review_offset
            if offset not in _SIMULATION_OFFSETS:
                continue
            factor_snapshot = observation.factor_snapshot_json if isinstance(observation.factor_snapshot_json, dict) else {}
            tier = factor_snapshot.get("tier") or "C"
            hold_return = float(review.return_pct)
            disc_return, stopped = _discipline_exit_return(hold_return, review.max_drawdown_pct)
            for key in ((tier, offset), ("ALL", offset)):
                bucket = buckets.setdefault(key, {"discipline": [], "buy_hold": [], "stopped": 0})
                bucket["discipline"].append(disc_return)
                bucket["buy_hold"].append(hold_return)
                if stopped:
                    bucket["stopped"] += 1

        def _serialize(key: tuple[str, str]) -> dict:
            bucket = buckets.get(key)
            if not bucket:
                empty = _simulation_bucket([])
                return {"discipline": empty, "buy_hold": dict(empty), "stopped": 0, "stop_rate": None, "expectancy_delta_pct": None}
            discipline = _simulation_arm(bucket["discipline"])
            buy_hold = _simulation_arm(bucket["buy_hold"])
            trades = discipline["trades"]
            disc_exp = discipline.get("expectancy_pct")
            hold_exp = buy_hold.get("expectancy_pct")
            return {
                "discipline": discipline,
                "buy_hold": buy_hold,
                "stopped": bucket["stopped"],
                "stop_rate": round(bucket["stopped"] / trades, 4) if trades else None,
                "expectancy_delta_pct": round(disc_exp - hold_exp, 4) if disc_exp is not None and hold_exp is not None else None,
            }

        overall = {offset: _serialize(("ALL", offset)) for offset in _SIMULATION_OFFSETS}
        by_tier = {
            tier_label: {offset: _serialize((tier_label, offset)) for offset in _SIMULATION_OFFSETS}
            for tier_label in ("A", "B", "C")
        }

        resolved_strategy = rows[0][0].strategy_id or strategy if rows else strategy
        return {
            "status": "ok",
            "lookback_days": lookback_days,
            "as_of": date.today().isoformat(),
            "strategy": resolved_strategy,
            "stop_loss_pct": _SIMULATION_STOP_LOSS_PCT,
            "sample_threshold": _SIMULATION_SAMPLE_THRESHOLD,
            "overall": overall,
            "by_tier": by_tier,
            "disclaimer": "历史模拟不代表未来表现，不构成投资建议",
        }
    finally:
        db.close()
