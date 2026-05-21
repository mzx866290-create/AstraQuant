import sys, os
sys.path.insert(0, '/app')
sys.path.insert(0, '/backend')
sys.path.insert(0, '/')
os.chdir('/app')

from backend.shared.database import SessionLocal
from backend.shared.models import DailySnapshot, ResearchObservation, Stock
from datetime import date, datetime
from sqlalchemy import text

db = SessionLocal()

today_str = date.today().isoformat()
today_dt = datetime.combine(date.today(), datetime.min.time())
print(f"Today: {today_str}, today_dt: {today_dt}")

# Simulate what the endpoint does
rows = db.query(ResearchObservation).filter(
    ResearchObservation.snapshot_date == today_dt,
).order_by(ResearchObservation.score.desc()).limit(50).all()
print(f"Today's observations: {len(rows)}")

if not rows:
    rows = db.query(ResearchObservation).order_by(
        ResearchObservation.snapshot_date.desc(), ResearchObservation.score.desc()
    ).limit(50).all()
    print(f"Fallback observations (stale): {len(rows)}")

if rows:
    symbols = [row.symbol for row in rows]
    snapshot_date_str = rows[0].snapshot_date.strftime("%Y-%m-%d") if rows[0].snapshot_date else today_str
    print(f"Snapshot date for lookup: {snapshot_date_str}")
    print(f"Unique symbols: {len(set(symbols))}")

    snap_rows = db.query(DailySnapshot.symbol, DailySnapshot.name, DailySnapshot.change_pct).filter(
        DailySnapshot.symbol.in_(symbols),
        DailySnapshot.trade_date == snapshot_date_str,
    ).all()
    print(f"DailySnapshot rows found: {len(snap_rows)}")
    name_map = {r.symbol: r.name or "" for r in snap_rows}
    print(f"name_map from snapshots: {len(name_map)} entries, bool={bool(name_map)}")

    if not name_map:
        stock_rows = db.query(Stock.symbol, Stock.name).filter(Stock.symbol.in_(symbols)).all()
        name_map = {r.symbol: r.name or "" for r in stock_rows}
        print(f"name_map from stocks: {len(name_map)} entries")

    # Show first 5 with names
    for s in symbols[:5]:
        print(f"  {s} -> '{name_map.get(s, 'NOT FOUND')}'")

db.close()
