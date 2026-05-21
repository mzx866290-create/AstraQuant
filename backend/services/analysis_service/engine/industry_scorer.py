"""行业健康评分器 — 基于趋势、资金流、动量三维度评估行业景气度"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text

from backend.shared.database import SessionLocal
from backend.shared.models import IndustryHealthScore

logger = logging.getLogger(__name__)

HEALTHY_THRESHOLD = 50


def score_all_industries(trade_date: str) -> dict:
    """
    对当日所有行业计算健康分并写入 industry_health_scores 表。

    返回 {"scored": int, "healthy": int, "unhealthy": int}
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT * FROM industry_daily_snapshots WHERE trade_date = :td"),
            {"td": trade_date},
        ).fetchall()

        if not rows:
            return {"scored": 0, "healthy": 0, "unhealthy": 0}

        columns = [
            "id", "industry_code", "industry_name", "trade_date",
            "close", "change_pct", "ma5", "ma20", "ma60",
            "ret_5d", "ret_20d", "ret_60d",
            "money_flow_1d", "money_flow_5d", "money_flow_20d",
            "source", "created_at",
        ]

        results = []
        for row in rows:
            snap = dict(zip(columns, row))
            score_result = _compute_health_score(snap)
            results.append(score_result)

        _enrich_acceleration(results, trade_date, db)

        saved = _bulk_upsert_scores(results, trade_date, db)
        healthy = sum(1 for r in results if r["is_healthy"])
        logger.info(
            "Industry health scores: %d scored, %d healthy, %d unhealthy",
            len(results), healthy, len(results) - healthy,
        )
        return {"scored": len(results), "healthy": healthy, "unhealthy": len(results) - healthy}
    except Exception as e:
        logger.error("Failed to score industries: %s", e)
        db.rollback()
        return {"scored": 0, "healthy": 0, "unhealthy": 0, "error": str(e)}
    finally:
        db.close()


def _compute_health_score(snap: dict) -> dict:
    """计算单个行业的健康分（满分100）"""
    flags = []

    # === 趋势维度 (40分) ===
    trend_score = 40
    ret_60d = snap.get("ret_60d")
    ret_20d = snap.get("ret_20d")
    ret_5d = snap.get("ret_5d")
    change_pct = snap.get("change_pct")  # 1日涨跌幅（百分比，如-2.3）
    close = snap.get("close") or 0
    ma20 = snap.get("ma20") or 0
    ma60 = snap.get("ma60") or 0

    if ret_60d is not None:
        if ret_60d < -0.10:
            trend_score -= 25
            flags.append(f"行业60日跌{ret_60d*100:.1f}%")
        elif ret_60d < -0.05:
            trend_score -= 12
            flags.append(f"行业60日跌{ret_60d*100:.1f}%")
    elif ret_20d is not None:
        # 没有60日数据时用20日替代
        if ret_20d < -0.08:
            trend_score -= 20
            flags.append(f"行业20日跌{ret_20d*100:.1f}%")
        elif ret_20d < -0.04:
            trend_score -= 10
            flags.append(f"行业20日跌{ret_20d*100:.1f}%")
    elif change_pct is not None:
        # 降级到1日数据：连续重跌信号
        if change_pct < -3.0:
            trend_score -= 12
            flags.append(f"行业今日跌{change_pct:.1f}%")
        elif change_pct < -1.5:
            trend_score -= 6
            flags.append(f"行业今日跌{change_pct:.1f}%")

    if close and ma20 and ma60:
        if not (close > ma20 > ma60):
            trend_score -= 15
            flags.append("行业MA空头排列")
    elif close and ma20:
        if close < ma20:
            trend_score -= 10
            flags.append("行业价格低于MA20")

    trend_score = max(trend_score, 0)

    # === 资金维度 (30分) ===
    money_score = 30
    money_flow_5d = snap.get("money_flow_5d")
    money_flow_20d = snap.get("money_flow_20d")
    money_flow_1d = snap.get("money_flow_1d")

    if money_flow_20d is not None:
        if money_flow_20d < -50:
            money_score -= 20
            flags.append(f"行业20日净流出{abs(money_flow_20d):.0f}亿")
        elif money_flow_20d < -20:
            money_score -= 12
        elif money_flow_20d < 0:
            money_score -= 5
    elif money_flow_5d is not None:
        if money_flow_5d < -30:
            money_score -= 15
            flags.append(f"行业5日净流出{abs(money_flow_5d):.0f}亿")
        elif money_flow_5d < -15:
            money_score -= 8
    elif money_flow_1d is not None:
        # 只有1日数据时按比例估算
        if money_flow_1d < -30:
            money_score -= 10
            flags.append(f"行业今日净流出{abs(money_flow_1d):.0f}亿")
        elif money_flow_1d < -10:
            money_score -= 5
        elif money_flow_1d > 50:
            pass  # 大流入时不加分（保守）

    if money_flow_5d is not None and money_flow_20d is not None:
        if money_flow_5d < -20:
            money_score -= 10
            flags.append("近5日资金加速流出")
        elif money_flow_5d < -10:
            money_score -= 5

    money_score = max(money_score, 0)

    # === 动量维度 (30分) ===
    momentum_score = 30

    if ret_5d is not None:
        if ret_5d < -0.05:
            momentum_score -= 20
            flags.append(f"行业近5日跌{ret_5d*100:.1f}%")
        elif ret_5d < -0.03:
            momentum_score -= 12
            flags.append("行业近5日下跌")
    elif change_pct is not None:
        # 降级：用今日涨跌幅作为超短期动量代理
        if change_pct < -2.5:
            momentum_score -= 12
            flags.append(f"行业今日跌幅{change_pct:.1f}%")
        elif change_pct < -1.5:
            momentum_score -= 6
        elif change_pct > 2.0:
            pass  # 今日大涨不加分（可能是反弹）

    # 逆势反弹检测：整体下跌中的短期反弹
    if ret_20d is not None and ret_5d is not None:
        if ret_20d < -0.05 and ret_5d > 0.02:
            momentum_score -= 15
            flags.append("行业整体下跌中的反弹")

    momentum_score = max(momentum_score, 0)

    total = trend_score + money_score + momentum_score
    is_healthy = total >= HEALTHY_THRESHOLD

    return {
        "industry_code": snap["industry_code"],
        "industry_name": snap["industry_name"],
        "trade_date": snap["trade_date"],
        "health_score": total,
        "trend_score": trend_score,
        "money_score": money_score,
        "momentum_score": momentum_score,
        "flags": flags,
        "is_healthy": is_healthy,
        "score_5d_ago": None,
        "score_change_5d": None,
        "is_accelerating_down": False,
    }


def _enrich_acceleration(results: list[dict], trade_date: str, db) -> None:
    """为每个行业补充5日加速度：查5天前的健康分，计算变化量"""
    if not results:
        return

    codes = [r["industry_code"] for r in results]
    placeholders = ", ".join(f":c{i}" for i in range(len(codes)))
    params = {f"c{i}": c for i, c in enumerate(codes)}
    params["td"] = trade_date

    prev_rows = db.execute(
        text(f"""
            SELECT DISTINCT ON (industry_code) industry_code, health_score
            FROM industry_health_scores
            WHERE industry_code IN ({placeholders})
              AND trade_date < :td
            ORDER BY industry_code, trade_date DESC
        """),
        params,
    ).fetchall()
    prev_map = {row[0]: row[1] for row in prev_rows}

    for item in results:
        prev_score = prev_map.get(item["industry_code"])
        if prev_score is not None:
            item["score_5d_ago"] = prev_score
            item["score_change_5d"] = item["health_score"] - prev_score
            if item["score_change_5d"] < -15:
                item["is_accelerating_down"] = True
                item["flags"].append(f"健康度骤降{item['score_change_5d']}分")


def get_industry_health(industry_name: str, trade_date: str) -> Optional[dict]:
    """查询指定行业在指定日期的健康分"""
    db = SessionLocal()
    try:
        row = db.execute(
            text("""
                SELECT health_score, trend_score, money_score, momentum_score,
                       flags, is_healthy, score_5d_ago, score_change_5d, is_accelerating_down
                FROM industry_health_scores
                WHERE industry_name = :name AND trade_date = :td
            """),
            {"name": industry_name, "td": trade_date},
        ).fetchone()
        if not row:
            return None
        return {
            "health_score": row[0],
            "trend_score": row[1],
            "money_score": row[2],
            "momentum_score": row[3],
            "flags": row[4],
            "is_healthy": row[5],
            "score_5d_ago": row[6],
            "score_change_5d": row[7],
            "is_accelerating_down": row[8],
        }
    finally:
        db.close()


def _bulk_upsert_scores(results: list[dict], trade_date: str, db) -> int:
    """批量写入健康分"""
    existing = db.execute(
        text("SELECT industry_code FROM industry_health_scores WHERE trade_date = :td"),
        {"td": trade_date},
    ).fetchall()
    existing_codes = {row[0] for row in existing}

    new_records = []
    updated = 0
    for item in results:
        if item["industry_code"] in existing_codes:
            db.execute(
                text("""
                    UPDATE industry_health_scores
                    SET health_score = :health_score, trend_score = :trend_score,
                        money_score = :money_score, momentum_score = :momentum_score,
                        flags = :flags, is_healthy = :is_healthy,
                        score_5d_ago = :score_5d_ago, score_change_5d = :score_change_5d,
                        is_accelerating_down = :is_accelerating_down
                    WHERE industry_code = :industry_code AND trade_date = :trade_date
                """),
                {**item, "flags": json.dumps(item["flags"], ensure_ascii=False)},
            )
            updated += 1
        else:
            record_data = {**item, "flags": json.dumps(item["flags"], ensure_ascii=False)}
            new_records.append(IndustryHealthScore(**record_data))

    if new_records:
        db.bulk_save_objects(new_records)

    db.commit()
    return len(new_records) + updated
