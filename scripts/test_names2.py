import sys, os
sys.path.insert(0, '/app')
sys.path.insert(0, '/backend')
sys.path.insert(0, '/')
os.chdir('/app')

from backend.shared.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

# Get the actual symbols from observations that batch/recommend returns
result = db.execute(text("""
    SELECT ro.symbol, s.name
    FROM research_observations ro
    LEFT JOIN stocks s ON s.symbol = ro.symbol
    WHERE ro.snapshot_date = (SELECT MAX(snapshot_date) FROM research_observations)
    ORDER BY ro.score DESC
    LIMIT 10
"""))
print("Top 10 observations with stock name lookup:")
for row in result:
    print(f"  {row[0]}: name='{row[1] or ''}'")

# Check if there are duplicate symbols with different IDs
result2 = db.execute(text("""
    SELECT symbol, COUNT(*) as cnt FROM stocks
    WHERE symbol IN (
        SELECT DISTINCT symbol FROM research_observations
    )
    GROUP BY symbol
    HAVING COUNT(*) > 1
"""))
print("\nDuplicate symbols in stocks:")
dupes = list(result2)
if not dupes:
    print("  None")
for row in dupes:
    print(f"  {row[0]}: {row[1]}")

# Check unique constraint
result3 = db.execute(text("SELECT symbol, id FROM stocks WHERE symbol LIKE '600031%'"))
print("\n600031 entries:")
for row in result3:
    print(f"  id={row[1]} symbol={row[0]}")

db.close()
