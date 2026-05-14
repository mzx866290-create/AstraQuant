"""
一次性批量导入财报和公告数据。

用法:
    python scripts/init_financials.py                   # 默认导入预设清单
    python scripts/init_financials.py --symbols 000001.SZ 600519.SH
    python scripts/init_financials.py --watchlist       # 从数据库自选股读取
    python scripts/init_financials.py --skip-announcements

每只股票只在数据库里没有财报时才拉取，已有数据的跳过（节省流量）。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("init_financials")

# 常用指数成分 + 典型行业代表，覆盖主要分析场景
DEFAULT_SYMBOLS = [
    # 银行
    "000001.SZ", "600036.SH", "601398.SH", "601288.SH", "600016.SH",
    # 消费/白酒
    "600519.SH", "000858.SZ", "002304.SZ",
    # 科技/半导体
    "000725.SZ", "688981.SH", "002459.SZ",
    # 新能源/电池
    "300750.SZ", "002594.SZ", "600438.SH",
    # 地产
    "000002.SZ", "600048.SH",
    # 医药
    "600276.SH", "000538.SZ", "300015.SZ",
    # 工业/机械
    "600031.SH", "000338.SZ",
    # 券商/保险
    "600030.SH", "601318.SH",
    # 电力/公用
    "600900.SH", "002027.SZ",
]


def _normalize(symbol: str) -> str:
    s = symbol.strip().upper()
    if "." not in s:
        code = s[:6]
        suffix = "SH" if code.startswith(("6", "5", "9")) else "SZ"
        return f"{code}.{suffix}"
    return s


def _bare_code(symbol: str) -> str:
    return symbol.split(".")[0]


def _load_watchlist_symbols() -> list[str]:
    from backend.shared.database import SessionLocal
    import sqlalchemy as sa
    db = SessionLocal()
    try:
        rows = db.execute(sa.text(
            "SELECT s.symbol FROM watchlist_items wi JOIN stocks s ON s.id = wi.stock_id"
        )).fetchall()
        return [_normalize(r[0]) for r in rows]
    except Exception as e:
        logger.warning("Failed to load watchlist symbols: %s", e)
        return []
    finally:
        db.close()


def _already_has_financials(db, symbol: str) -> bool:
    import sqlalchemy as sa
    code = _bare_code(symbol)
    count = db.execute(
        sa.text("SELECT COUNT(*) FROM financial_reports WHERE stock_symbol = :s"),
        {"s": code},
    ).scalar()
    return (count or 0) > 0


def _already_has_announcements(db, symbol: str) -> bool:
    import sqlalchemy as sa
    code = _bare_code(symbol)
    count = db.execute(
        sa.text("SELECT COUNT(*) FROM company_announcements WHERE stock_symbol = :s"),
        {"s": code},
    ).scalar()
    return (count or 0) > 0


async def fetch_financials(symbol: str, source, etl, db) -> tuple[int, int]:
    code = _bare_code(symbol)
    balance = await source.fetch_balance_sheet(symbol=code)
    profit = await source.fetch_profit_sheet(symbol=code)
    cashflow = await source.fetch_cash_flow_sheet(symbol=code)
    fetched = len(balance) + len(profit) + len(cashflow)
    saved = await etl.save(db, code, balance, profit, cashflow, source.name)
    return fetched, saved


async def fetch_announcements(symbol: str, source, etl, db) -> tuple[int, int]:
    code = _bare_code(symbol)
    data = await source.fetch_stock_notices(symbol=code, limit=30)
    saved = await etl.save(db, code, data, "CNINFO")
    return len(data), saved


async def main(symbols: list[str], skip_announcements: bool, force: bool) -> None:
    from backend.shared.database import SessionLocal, init_db
    from backend.services.data_crawler.sources.akshare_source import AKShareSource
    from backend.services.data_crawler.pipeline.financial_etl import (
        AnnouncementETL,
        FinancialReportETL,
    )

    init_db()
    source = AKShareSource()
    fin_etl = FinancialReportETL()
    ann_etl = AnnouncementETL()

    total = len(symbols)
    fin_ok = fin_skip = fin_fail = 0
    ann_ok = ann_skip = ann_fail = 0

    for i, symbol in enumerate(symbols, 1):
        db = SessionLocal()
        try:
            logger.info("[%d/%d] %s", i, total, symbol)

            # --- 财报 ---
            if not force and _already_has_financials(db, symbol):
                logger.info("  财报: 已有数据，跳过")
                fin_skip += 1
            else:
                try:
                    fetched, saved = await fetch_financials(symbol, source, fin_etl, db)
                    logger.info("  财报: fetched=%d saved=%d", fetched, saved)
                    fin_ok += 1
                except Exception as e:
                    db.rollback()
                    logger.warning("  财报失败: %s", e)
                    fin_fail += 1

            # --- 公告 ---
            if not skip_announcements:
                if not force and _already_has_announcements(db, symbol):
                    logger.info("  公告: 已有数据，跳过")
                    ann_skip += 1
                else:
                    try:
                        fetched, saved = await fetch_announcements(symbol, source, ann_etl, db)
                        logger.info("  公告: fetched=%d saved=%d", fetched, saved)
                        ann_ok += 1
                    except Exception as e:
                        db.rollback()
                        logger.warning("  公告失败: %s", e)
                        ann_fail += 1

            # 每只股票之间稍作停顿，避免触发数据源限速
            await asyncio.sleep(1.5)

        finally:
            db.close()

    logger.info(
        "完成。财报: ok=%d skip=%d fail=%d | 公告: ok=%d skip=%d fail=%d",
        fin_ok, fin_skip, fin_fail,
        ann_ok, ann_skip, ann_fail,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量初始化财报和公告数据")
    parser.add_argument("--symbols", nargs="+", help="指定股票代码，如 000001.SZ 600519.SH")
    parser.add_argument("--watchlist", action="store_true", help="从数据库自选股读取")
    parser.add_argument("--skip-announcements", action="store_true", help="跳过公告采集")
    parser.add_argument("--force", action="store_true", help="强制重新拉取（忽略已有数据）")
    args = parser.parse_args()

    if args.symbols:
        symbols = [_normalize(s) for s in args.symbols]
    elif args.watchlist:
        symbols = _load_watchlist_symbols()
        if not symbols:
            logger.error("自选股列表为空，请先添加自选股或用 --symbols 指定")
            sys.exit(1)
    else:
        symbols = [_normalize(s) for s in DEFAULT_SYMBOLS]

    # 去重保序
    seen: set[str] = set()
    deduped = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            deduped.append(s)

    logger.info("准备导入 %d 只股票的财报数据", len(deduped))
    asyncio.run(main(deduped, args.skip_announcements, args.force))
