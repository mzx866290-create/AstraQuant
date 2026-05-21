import sys, os
sys.path.insert(0, '/app')
sys.path.insert(0, '/backend')
sys.path.insert(0, '/')
os.chdir('/app')

from backend.shared.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()

# Check what symbols observations have vs stocks table
obs_syms = db.execute(text("""
    SELECT DISTINCT ro.symbol FROM research_observations ro
    ORDER BY ro.symbol LIMIT 20
"""))
obs_list = [row[0] for row in obs_syms]
print("Observation symbols:")
for s in obs_list:
    print(f"  {s}")

# Check what matching stocks exist
if obs_list:
    placeholders = ','.join(f"'{s}'" for s in obs_list)
    stock_syms = db.execute(text(f"SELECT symbol, name FROM stocks WHERE symbol IN ({placeholders})"))
    found = {row[0]: row[1] for row in stock_syms}
    print(f"\nMatched in stocks table: {len(found)}/{len(obs_list)}")
    for s in obs_list:
        if s in found:
            print(f"  OK  {s}: {found[s]}")
        else:
            print(f"  MISS {s}")

# Check if stocks with these codes exist under different format
for s in obs_list[:5]:
    code = s.split('.')[0]
    r = db.execute(text(f"SELECT symbol FROM stocks WHERE symbol LIKE '{code}%'"))
    variants = [row[0] for row in r]
    if s not in variants:
        print(f"\n  {s} not found, variants: {variants}")

db.close()
