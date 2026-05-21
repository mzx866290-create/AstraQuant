import sys, os
sys.path.insert(0, '/app')
sys.path.insert(0, '/backend')
sys.path.insert(0, '/')
os.chdir('/app')

from backend.shared.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

# Check if observation symbols exist in stocks table
result = db.execute(text("""
    SELECT s.symbol, s.name FROM stocks s
    WHERE s.symbol IN ('600031.SH','600060.SH','000027.SZ','601006.SH','600001.SH')
"""))
print("Stocks found for observation symbols:")
for row in result:
    print(f"  {row[0]}: {row[1]}")

# Check what format observations use
result2 = db.execute(text("SELECT DISTINCT symbol FROM research_observations LIMIT 10"))
print("\nObservation symbols sample:")
for row in result2:
    print(f"  {row[0]}")

# Check if there's a duplicate key issue
result3 = db.execute(text("SELECT COUNT(*) FROM stocks WHERE symbol LIKE '600031%'"))
print(f"\n600031 variants count: {result3.scalar()}")

result4 = db.execute(text("SELECT symbol FROM stocks WHERE symbol LIKE '600031%'"))
for row in result4:
    print(f"  found: {row[0]}")

db.close()
