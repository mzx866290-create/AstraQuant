"""追高惩罚模块 — 对当日大涨候选股降权或移出主池。"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 涨幅阈值
PENALTY_THRESHOLD = 6.0    # 涨幅超过此值打折
EXCLUDE_THRESHOLD = 9.0    # 涨幅超过此值移出主池进高风险桶
# 科创板(688)/创业板(300)极端波动阈值（20cm 板）
EXTREME_THRESHOLD = 15.0

PENALTY_MULTIPLIER = 0.80  # 6-9% 区间的评分折扣


def _is_high_volatility_board(symbol: str) -> bool:
    """科创板（688xxx）或创业板（300xxx）允许 20%/30% 涨跌幅。"""
    code = symbol.split(".")[0]
    return code.startswith("688") or code.startswith("300")


def apply_chase_high_penalty(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    对候选股应用追高惩罚。

    返回：
        (main_pool, high_risk_bucket)
        - main_pool: 主池候选（涨幅 <= 排除阈值）
        - high_risk_bucket: 高风险观察桶（涨幅超过排除阈值或极端波动）
    """
    main_pool: list[dict] = []
    high_risk_bucket: list[dict] = []

    for item in candidates:
        symbol = item.get("symbol", "")
        change_pct = abs(float(item.get("change_pct") or 0))
        is_high_vol = _is_high_volatility_board(symbol)

        # 极端波动板（科创/创业板 >15%）→ 高风险桶
        if is_high_vol and change_pct > EXTREME_THRESHOLD:
            item["chase_high_penalty"] = None
            item["high_risk_reason"] = f"极端波动板涨幅{change_pct:.1f}%"
            high_risk_bucket.append(item)
            continue

        # 涨幅 > 排除阈值 → 高风险桶
        if change_pct > EXCLUDE_THRESHOLD:
            item["chase_high_penalty"] = None
            item["high_risk_reason"] = f"涨幅{change_pct:.1f}%超过{EXCLUDE_THRESHOLD}%排除阈值"
            high_risk_bucket.append(item)
            continue

        # 涨幅 > 惩罚阈值 → 降权
        if change_pct > PENALTY_THRESHOLD:
            original_score = item.get("final_score") or item.get("anomaly_score", 0)
            penalized_score = round(original_score * PENALTY_MULTIPLIER, 1)
            item["final_score"] = penalized_score
            item["score"] = penalized_score
            item["chase_high_penalty"] = {
                "original_score": original_score,
                "penalized_score": penalized_score,
                "multiplier": PENALTY_MULTIPLIER,
                "reason": f"涨幅{change_pct:.1f}%超过{PENALTY_THRESHOLD}%，评分打{int(PENALTY_MULTIPLIER * 100)}折",
            }
            logger.debug(
                "Chase-high penalty applied to %s: %.1f%% gain, score %.1f -> %.1f",
                symbol, change_pct, original_score, penalized_score,
            )
        else:
            item["chase_high_penalty"] = None

        main_pool.append(item)

    if high_risk_bucket:
        logger.info(
            "Chase-high: %d main pool, %d moved to high-risk bucket",
            len(main_pool), len(high_risk_bucket),
        )

    return main_pool, high_risk_bucket
