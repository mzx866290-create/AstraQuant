"""硬否决层 — 任一条件触发即淘汰，位于粗筛之后、评分之前"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text

from backend.shared.database import SessionLocal
from backend.shared.models import RejectionLog

logger = logging.getLogger(__name__)

PROFIT_DECLINE_THRESHOLD = 4
PEER_DECLINE_THRESHOLD = 3
PEER_RET_20D_LIMIT = -0.05


def batch_hard_veto(
    candidates: list[dict],
    trade_date: str,
) -> tuple[list[dict], list[dict], dict]:
    """
    对候选股执行硬否决检查。

    返回 (passed, rejected, stats)
    stats: {"total", "passed", "rejected_by": {reason: count}}
    """
    if not candidates:
        return [], [], {"total": 0, "passed": 0, "rejected_by": {}}

    db = SessionLocal()
    try:
        symbols = [c["symbol"] for c in candidates]
        fin_map = _load_financial_trends(db, symbols)
        peer_map = _load_peer_data(db, candidates, trade_date)

        passed = []
        rejected = []
        stats = {"total": len(candidates), "passed": 0, "rejected_by": {}}

        for item in candidates:
            result = _check_single(item, trade_date, fin_map, peer_map)
            if result["pass"]:
                passed.append(item)
                stats["passed"] += 1
            else:
                item["hard_veto"] = result
                rejected.append(item)
                vtype = result["vetoed_by"]
                stats["rejected_by"][vtype] = stats["rejected_by"].get(vtype, 0) + 1
                _log_rejection(db, item, trade_date, result)

        db.commit()
        logger.info(
            "Hard veto: %d → %d passed, rejected_by=%s",
            len(candidates), len(passed), stats["rejected_by"],
        )
        return passed, rejected, stats

    except Exception as e:
        logger.error("Hard veto batch failed: %s", e)
        db.rollback()
        return candidates, [], {"total": len(candidates), "passed": len(candidates), "rejected_by": {}, "error": str(e)}
    finally:
        db.close()


def _check_single(
    item: dict,
    trade_date: str,
    fin_map: dict,
    peer_map: dict,
) -> dict:
    """对单只股票执行所有硬否决规则"""
    symbol = item.get("symbol", "")

    result = _check_fundamental_decline(symbol, fin_map)
    if not result["pass"]:
        return result

    result = _check_peer_linkage(item, peer_map)
    if not result["pass"]:
        return result

    return {"pass": True, "vetoed_by": None, "reason": ""}


def _check_fundamental_decline(symbol: str, fin_map: dict) -> dict:
    """财务连续4季度恶化"""
    fin = fin_map.get(symbol)
    if not fin:
        return {"pass": True, "vetoed_by": None, "reason": ""}

    decline_q = max(fin.get("revenue_decline_quarters") or 0, fin.get("profit_decline_quarters") or 0)
    if decline_q >= PROFIT_DECLINE_THRESHOLD:
        return {
            "pass": False,
            "vetoed_by": "fundamental",
            "reason": f"基本面连续{decline_q}季度恶化",
            "detail": {
                "revenue_decline_quarters": fin.get("revenue_decline_quarters"),
                "profit_decline_quarters": fin.get("profit_decline_quarters"),
                "cashflow_negative_quarters": fin.get("cashflow_negative_quarters"),
            },
        }
    return {"pass": True, "vetoed_by": None, "reason": ""}


def _check_peer_linkage(item: dict, peer_map: dict) -> dict:
    """同行业Top5龙头中3只以上近20日下跌超5%"""
    industry_name = item.get("industry_name") or item.get("sector")
    if not industry_name:
        return {"pass": True, "vetoed_by": None, "reason": ""}

    peers = peer_map.get(industry_name)
    if not peers or len(peers) < PEER_DECLINE_THRESHOLD:
        return {"pass": True, "vetoed_by": None, "reason": ""}

    symbol = item.get("symbol", "")
    declining = [
        p for p in peers
        if p["symbol"] != symbol and (p.get("ret_20d") or 0) < PEER_RET_20D_LIMIT
    ]

    if len(declining) >= PEER_DECLINE_THRESHOLD:
        names = ", ".join(p.get("name", p["symbol"]) for p in declining[:3])
        return {
            "pass": False,
            "vetoed_by": "peer",
            "reason": f"同行业龙头{len(declining)}只近20日跌超5%（{names}），行业性下跌",
            "detail": {
                "declining_count": len(declining),
                "declining_peers": [
                    {"symbol": p["symbol"], "name": p.get("name"), "ret_20d": p.get("ret_20d")}
                    for p in declining[:5]
                ],
            },
        }
    return {"pass": True, "vetoed_by": None, "reason": ""}


def _load_financial_trends(db, symbols: list[str]) -> dict:
    """加载候选股的最新财务趋势"""
    if not symbols:
        return {}
    code_map = {}
    for s in symbols:
        code = s.split(".")[0] if "." in s else s
        code_map[code] = s

    codes = list(code_map.keys())
    placeholders = ", ".join(f":c{i}" for i in range(len(codes)))
    params = {f"c{i}": c for i, c in enumerate(codes)}

    rows = db.execute(
        text(f"""
            SELECT DISTINCT ON (stock_code) stock_code,
                   revenue_decline_quarters, profit_decline_quarters,
                   cashflow_negative_quarters, revenue_yoy, profit_yoy
            FROM financial_trends
            WHERE stock_code IN ({placeholders})
            ORDER BY stock_code, report_date DESC
        """),
        params,
    ).fetchall()

    result = {}
    for row in rows:
        stock_code = row[0]
        symbol = code_map.get(stock_code, stock_code)
        result[symbol] = {
            "revenue_decline_quarters": row[1],
            "profit_decline_quarters": row[2],
            "cashflow_negative_quarters": row[3],
            "revenue_yoy": row[4],
            "profit_yoy": row[5],
        }
    return result


def _load_peer_data(db, candidates: list[dict], trade_date: str) -> dict:
    """按行业加载龙头股20日收益率，返回 {industry_name: [peers]}"""
    industries = set()
    for c in candidates:
        name = c.get("industry_name") or c.get("sector")
        if name:
            industries.add(name)

    if not industries:
        return {}

    ind_list = list(industries)
    placeholders = ", ".join(f":i{i}" for i in range(len(ind_list)))
    params = {f"i{i}": v for i, v in enumerate(ind_list)}
    params["td"] = trade_date

    rows = db.execute(
        text(f"""
            SELECT s.symbol, s.name, s.sector,
                   ds.total_mv,
                   CASE WHEN ds.prev_close > 0
                        THEN (ds.close - ds.prev_close) / ds.prev_close
                        ELSE 0 END AS ret_1d
            FROM daily_snapshots ds
            JOIN stocks s ON s.symbol = ds.symbol
            WHERE s.sector IN ({placeholders})
              AND ds.trade_date = :td
              AND ds.volume > 0
            ORDER BY s.sector, ds.total_mv DESC NULLS LAST
        """),
        params,
    ).fetchall()

    peer_map: dict[str, list[dict]] = {}
    for row in rows:
        sector = row[2]
        if sector not in peer_map:
            peer_map[sector] = []
        if len(peer_map[sector]) < 6:
            peer_map[sector].append({
                "symbol": row[0],
                "name": row[1],
                "total_mv": row[3],
                "ret_20d": None,
            })

    _fill_peer_20d_returns(db, peer_map, trade_date)
    return peer_map


def _fill_peer_20d_returns(db, peer_map: dict, trade_date: str) -> None:
    """补充龙头股20日收益率"""
    all_symbols = []
    for peers in peer_map.values():
        for p in peers:
            all_symbols.append(p["symbol"])

    if not all_symbols:
        return

    placeholders = ", ".join(f":s{i}" for i in range(len(all_symbols)))
    params = {f"s{i}": s for i, s in enumerate(all_symbols)}
    params["td"] = trade_date

    rows = db.execute(
        text(f"""
            SELECT symbol, close FROM daily_snapshots
            WHERE symbol IN ({placeholders})
              AND trade_date <= :td
            ORDER BY symbol, trade_date DESC
        """),
        params,
    ).fetchall()

    history: dict[str, list[float]] = {}
    for row in rows:
        sym = row[0]
        if sym not in history:
            history[sym] = []
        if len(history[sym]) < 25:
            history[sym].append(row[1])

    for peers in peer_map.values():
        for p in peers:
            closes = history.get(p["symbol"], [])
            if len(closes) >= 20 and closes[-1] and closes[-1] > 0:
                p["ret_20d"] = (closes[0] / closes[min(19, len(closes) - 1)] - 1)


def _log_rejection(db, item: dict, trade_date: str, veto_result: dict) -> None:
    """写入淘汰日志"""
    try:
        record = RejectionLog(
            symbol=item.get("symbol", ""),
            stock_name=item.get("name", ""),
            trade_date=trade_date,
            reject_stage="hard_veto",
            reject_reason=veto_result.get("reason", ""),
            reject_detail=veto_result.get("detail"),
            base_score=item.get("anomaly_score"),
            almost_qualified=False,
        )
        db.add(record)
    except Exception as e:
        logger.warning("Failed to log rejection for %s: %s", item.get("symbol"), e)
