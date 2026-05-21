import sys, os
sys.path.insert(0, '/app')
sys.path.insert(0, '/backend')
sys.path.insert(0, '/')

from sqlalchemy import text
from shared.database import SessionLocal

db = SessionLocal()

# Check symbol suffixes
result = db.execute(text("SELECT RIGHT(symbol, 2) as suffix, COUNT(*) as cnt FROM stocks GROUP BY RIGHT(symbol, 2)"))
print("Stocks by suffix:")
for row in result:
    print(f"  .{row[0]}: {row[1]}")

# Check if .SH stocks exist
result2 = db.execute(text("SELECT symbol, name FROM stocks WHERE symbol LIKE '%.SH' LIMIT 3"))
print("\n.SH stocks:")
for row in result2:
    print(f"  {row[0]}: {row[1]}")

result3 = db.execute(text("SELECT symbol, name FROM stocks WHERE symbol LIKE '%.SS' LIMIT 3"))
print("\n.SS stocks:")
for row in result3:
    print(f"  {row[0]}: {row[1]}")

# Check 600031
result4 = db.execute(text("SELECT symbol, name FROM stocks WHERE symbol LIKE '600031%'"))
print("\n600031 variants:")
for row in result4:
    print(f"  {row[0]}: {row[1]}")

# Check observations symbol format
result5 = db.execute(text("SELECT DISTINCT RIGHT(symbol, 3) as suffix FROM research_observations LIMIT 5"))
print("\nObservation symbol suffixes:")
for row in result5:
    print(f"  .{row[0]}")

db.close()
