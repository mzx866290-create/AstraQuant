"""
回填历史观察池数据的分层/动作字段。
对 research_observations 表中 factor_snapshot_json 没有 tier 的记录，
基于已有的 score_breakdown_json 和 evidence_chain_json 重新计算并回填。

用法：
    python -m backend.services.analysis_service.engine.backfill_tier_action
"""
from __future__ import annotations

import asyncio
import json
import logging

from backend.shared.database import SessionLocal
from backend.shared.models import ResearchObservation
from backend.services.analysis_service.engine.tier_classifier import classify_tiers
from backend.services.analysis_service.engine.observation_action_generator import generate_observation_actions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_json(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return None


async def backfill(dry_run: bool = False, limit: int = 200) -> dict:
    db = SessionLocal()
    updated = 0
    skipped = 0
    try:
        rows = (
            db.query(ResearchObservation)
            .order_by(ResearchObservation.snapshot_date.desc(), ResearchObservation.id.desc())
            .limit(limit)
            .all()
        )
        logger.info("Loaded %d observations to backfill", len(rows))

        # 构建 rec 列表
        recs = []
        for row in rows:
            factor_snapshot = _load_json(row.factor_snapshot_json) or {}
            if isinstance(factor_snapshot, list):
                factor_snapshot = {"factors": factor_snapshot}
            # 已有 tier 的跳过
            if factor_snapshot.get("tier"):
                skipped += 1
                continue
            rec = {
                "_row_id": row.id,
                "symbol": row.symbol,
                "name": "",
                "score": row.score,
                "change_pct": None,
                "price": row.close_price,
                "score_breakdown": _load_json(row.score_breakdown_json) or [],
                "evidence_chain": _load_json(row.evidence_chain_json) or [],
                "veto_result": _load_json(row.veto_result_json) or {},
                "debate_json": _load_json(row.debate_json) or {},
                "bull_case": (_load_json(row.debate_json) or {}).get("bull_case", []),
                "bear_case": (_load_json(row.debate_json) or {}).get("bear_case", []),
                "falsification": (_load_json(row.debate_json) or {}).get("falsification", []),
                "capital_flow_status": None,
                "chase_high_penalty": None,
                # 从 factor_snapshot 读 capital_flow_status
            }
            # 从 score_breakdown 提取 capital_flow_status
            for bd in rec["score_breakdown"]:
                if isinstance(bd, dict) and bd.get("key") == "capital_flow":
                    features = bd.get("features") or {}
                    rec["capital_flow_status"] = features.get("status")
                    break
            recs.append(rec)

        logger.info("Need to backfill %d records, skip %d already-filled", len(recs), skipped)

        if not recs:
            return {"updated": 0, "skipped": skipped}

        # 分层
        classified = classify_tiers(recs)

        # 生成动作（关闭 AI，只用规则，避免 backfill 太慢）
        classified = await generate_observation_actions(classified, use_ai=False)

        if dry_run:
            for r in classified[:5]:
                logger.info("DRY RUN %s: tier=%s action=%s", r["symbol"], r.get("tier"), r.get("observation_action"))
            return {"updated": 0, "skipped": skipped, "dry_run": True, "sample_count": len(classified)}

        # 回写
        id_to_rec = {r["_row_id"]: r for r in classified}
        for row in rows:
            rec = id_to_rec.get(row.id)
            if not rec:
                continue
            factor_snapshot = _load_json(row.factor_snapshot_json) or {}
            if isinstance(factor_snapshot, list):
                factor_snapshot = {"factors": factor_snapshot}
            factor_snapshot.update({
                "tier": rec.get("tier"),
                "tier_reason": rec.get("tier_reason"),
                "resonance_count": rec.get("resonance_count"),
                "priority_score": rec.get("priority_score"),
                "observation_action": rec.get("observation_action"),
                "trigger_condition": rec.get("trigger_condition"),
                "invalidation_condition": rec.get("invalidation_condition"),
                "risk_warning": rec.get("risk_warning"),
                "chase_high_penalty": rec.get("chase_high_penalty"),
            })
            row.factor_snapshot_json = factor_snapshot
            updated += 1

        db.commit()
        logger.info("Backfill done: updated=%d skipped=%d", updated, skipped)
        return {"updated": updated, "skipped": skipped}
    except Exception as e:
        db.rollback()
        logger.error("Backfill failed: %s", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    result = asyncio.run(backfill(dry_run=False, limit=200))
    print(result)
