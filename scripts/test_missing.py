import sys, os
sys.path.insert(0, '/app')
sys.path.insert(0, '/backend')
sys.path.insert(0, '/')
os.chdir('/app')

from backend.shared.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

# The problem: daily_snapshots is empty, so name_map from snapshots is empty
# Then fallback to stocks table - but 600001.SH is not found
# Let's check which observation symbols are NOT in stocks
result = db.execute(text("""
    SELECT DISTINCT ro.symbol
    FROM research_observations ro
    LEFT JOIN stocks s ON s.symbol = ro.symbol
    WHERE s.symbol IS NULL
    ORDER BY ro.symbol
    LIMIT 20
"""))
print("Observation symbols NOT in stocks table:")
for row in result:
    print(f"  {row[0]}")

# Total missing
result2 = db.execute(text("""
    SELECT COUNT(DISTINCT ro.symbol)
    FROM research_observations ro
    LEFT JOIN stocks s ON s.symbol = ro.symbol
    WHERE s.symbol IS NULL
"""))
print(f"\nTotal missing: {result2.scalar()}")

# Total in observations
result3 = db.execute(text("SELECT COUNT(DISTINCT symbol) FROM research_observations"))
print(f"Total distinct symbols in observations: {result3.scalar()}")

db.close()
