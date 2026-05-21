"""行业板块每日数据采集器 — 新浪行业快照 + AKShare历史K线补算MA"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from sqlalchemy import text

from backend.shared.database import SessionLocal
from backend.shared.models import IndustryDailySnapshot

logger = logging.getLogger(__name__)

SINA_INDUSTRY_URL = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
SINA_INDUSTRY_STOCKS_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


async def collect_industry_snapshot(trade_date: str) -> dict:
    """
    采集所有行业板块的行情快照。
    优先使用新浪财经接口（不依赖东方财富）。
    """
    loop = asyncio.get_event_loop()

    try:
        industries = await loop.run_in_executor(None, _fetch_sina_industries, trade_date)
    except Exception as e:
        logger.error("Failed to fetch industry list: %s", e)
        return {"collected": 0, "errors": 1, "status": "fetch_list_failed"}

    if not industries:
        return {"collected": 0, "errors": 0, "status": "no_industry_data"}

    results = []
    for ind in industries:
        ind["trade_date"] = trade_date
        results.append(ind)

    saved = _bulk_upsert(results, trade_date)
    logger.info("Industry snapshot: collected %d, saved %d", len(results), saved)
    return {"collected": len(results), "saved": saved, "errors": 0, "status": "ok"}


def _fetch_sina_industries(trade_date: str) -> list[dict]:
    """从新浪财经拉取行业板块实时行情"""
    r = requests.get(SINA_INDUSTRY_URL, timeout=15, headers=HEADERS)
    r.raise_for_status()
    raw_text = r.content.decode("gbk")
    match = re.search(r"= ({.*})", raw_text)
    if not match:
        return []

    data = json.loads(match.group(1))
    results = []
    for code, val in data.items():
        parts = val.split(",")
        if len(parts) < 8:
            continue
        industry_name = parts[1]
        change_pct = _safe_float(parts[5])
        avg_price = _safe_float(parts[3])
        amount = _safe_float(parts[7])

        results.append({
            "industry_code": code,
            "industry_name": industry_name,
            "close": avg_price,
            "change_pct": change_pct,
            "ma5": None,
            "ma20": None,
            "ma60": None,
            "ret_5d": None,
            "ret_20d": None,
            "ret_60d": None,
            "money_flow_1d": amount / 1e8 if amount else None,
            "money_flow_5d": None,
            "money_flow_20d": None,
        })

    # 用历史快照补算 MA 和收益率（不足时 AKShare 补全）
    _fill_historical_metrics(results, trade_date)
    return results


def _fill_historical_metrics(industries: list[dict], trade_date: str) -> None:
    """
    补算 MA 和收益率。
    先查本地历史快照；不足60天时用 AKShare stock_board_industry_hist_em 直接拉历史K线。
    """
    db = SessionLocal()
    try:
        for ind in industries:
            # 1. 先查本地已有历史
            rows = db.execute(
                text("""
                    SELECT trade_date, close, money_flow_1d
                    FROM industry_daily_snapshots
                    WHERE industry_code = :code AND trade_date < :td
                    ORDER BY trade_date DESC
                    LIMIT 65
                """),
                {"code": ind["industry_code"], "td": trade_date},
            ).fetchall()

            closes = [r[1] for r in rows if r[1] is not None]
            flows = [r[2] for r in rows if r[2] is not None]

            # 2. 本地不足20天 → 用 AKShare 拉历史K线补全
            if len(closes) < 20:
                akshare_closes = _fetch_akshare_hist(ind["industry_name"], trade_date)
                if akshare_closes:
                    closes = akshare_closes + closes
                    closes = closes[:65]

            current = ind["close"]
            if not current:
                continue

            all_closes = [current] + closes

            if len(all_closes) >= 5:
                ind["ma5"] = round(sum(all_closes[:5]) / 5, 4)
            if len(all_closes) >= 20:
                ind["ma20"] = round(sum(all_closes[:20]) / 20, 4)
            if len(all_closes) >= 60:
                ind["ma60"] = round(sum(all_closes[:60]) / 60, 4)

            if len(all_closes) >= 6 and all_closes[5]:
                ind["ret_5d"] = round((current - all_closes[5]) / all_closes[5], 4)
            if len(all_closes) >= 21 and all_closes[20]:
                ind["ret_20d"] = round((current - all_closes[20]) / all_closes[20], 4)
            if len(all_closes) >= 61 and all_closes[60]:
                ind["ret_60d"] = round((current - all_closes[60]) / all_closes[60], 4)

            if len(flows) >= 5:
                ind["money_flow_5d"] = round(sum(flows[:5]), 4)
            if len(flows) >= 20:
                ind["money_flow_20d"] = round(sum(flows[:20]), 4)
    finally:
        db.close()


def _fetch_akshare_hist(industry_name: str, trade_date: str) -> list[float]:
    """用 AKShare 拉行业历史K线，返回最近60日收盘价（新→旧）"""
    try:
        import akshare as ak
        end_date = trade_date.replace("-", "")
        start_dt = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=120)
        start_date = start_dt.strftime("%Y%m%d")

        df = ak.stock_board_industry_hist_em(
            symbol=industry_name,
            period="日k",
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
        if df is None or len(df) == 0:
            return []

        close_col = "收盘" if "收盘" in df.columns else df.columns[4]
        closes = df[close_col].astype(float).tolist()
        closes.reverse()  # 新→旧
        return closes[:65]
    except Exception as e:
        logger.debug("AKShare hist failed for %s: %s", industry_name, e)
        return []


def _bulk_upsert(snapshots: list[dict], trade_date: str) -> int:
    """批量写入行业快照，已存在则更新"""
    if not snapshots:
        return 0

    db = SessionLocal()
    try:
        existing = db.execute(
            text("SELECT industry_code FROM industry_daily_snapshots WHERE trade_date = :td"),
            {"td": trade_date},
        ).fetchall()
        existing_codes = {row[0] for row in existing}

        new_records = []
        updated = 0
        for snap in snapshots:
            if snap["industry_code"] in existing_codes:
                db.execute(
                    text("""
                        UPDATE industry_daily_snapshots
                        SET close = :close, change_pct = :change_pct,
                            ma5 = :ma5, ma20 = :ma20, ma60 = :ma60,
                            ret_5d = :ret_5d, ret_20d = :ret_20d, ret_60d = :ret_60d,
                            money_flow_1d = :money_flow_1d, money_flow_5d = :money_flow_5d,
                            money_flow_20d = :money_flow_20d
                        WHERE industry_code = :industry_code AND trade_date = :trade_date
                    """),
                    snap,
                )
                updated += 1
            else:
                new_records.append(IndustryDailySnapshot(**snap))

        if new_records:
            db.bulk_save_objects(new_records)

        db.commit()
        return len(new_records) + updated
    except Exception as e:
        logger.error("Failed to save industry snapshots: %s", e)
        db.rollback()
        return 0
    finally:
        db.close()


def get_industry_for_stock(symbol: str) -> Optional[dict]:
    """查询个股所属行业（从新浪获取）"""
    try:
        code = symbol[:6]
        prefix = "sz" if code.startswith(("0", "1", "2", "3")) else "sh"
        url = (
            f"{SINA_INDUSTRY_STOCKS_URL}?page=1&num=1&sort=symbol&asc=1"
            f"&node=hs_a&symbol={prefix}{code}&_s_r_a=page"
        )
        r = requests.get(url, timeout=5, headers=HEADERS)
        if r.status_code == 200 and r.text.strip():
            # 从新浪行业列表中查找包含该股票的行业
            pass
    except Exception:
        pass

    # 备用方案：从 stocks 表的 sector 字段获取
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT sector FROM stocks WHERE symbol = :sym"),
            {"sym": symbol},
        ).fetchone()
        if row and row[0]:
            return {"industry_name": row[0]}
    finally:
        db.close()

    return None
