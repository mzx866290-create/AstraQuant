import sys, os
sys.path.insert(0, '/app')
sys.path.insert(0, '/backend')
sys.path.insert(0, '/')
os.chdir('/app')

from backend.shared.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

# Update stocks with no suffix - add proper market suffix
# SH stocks start with 6, 9
# SZ stocks start with 0, 1, 2, 3
result1 = db.execute(text("""
    UPDATE stocks SET symbol = symbol || '.SH'
    WHERE symbol NOT LIKE '%.%'
    AND (symbol LIKE '6%' OR symbol LIKE '9%')
"""))
print(f"Added .SH suffix to {result1.rowcount} stocks")

result2 = db.execute(text("""
    UPDATE stocks SET symbol = symbol || '.SZ'
    WHERE symbol NOT LIKE '%.%'
    AND (symbol LIKE '0%' OR symbol LIKE '1%' OR symbol LIKE '2%' OR symbol LIKE '3%')
"""))
print(f"Added .SZ suffix to {result2.rowcount} stocks")

result3 = db.execute(text("""
    UPDATE stocks SET symbol = symbol || '.BJ'
    WHERE symbol NOT LIKE '%.%'
    AND (symbol LIKE '4%' OR symbol LIKE '8%')
"""))
print(f"Added .BJ suffix to {result3.rowcount} stocks")

# Fix .SS to .SH
result4 = db.execute(text("UPDATE stocks SET symbol = REPLACE(symbol, '.SS', '.SH') WHERE symbol LIKE '%.SS'"))
print(f"Fixed {result4.rowcount} stocks from .SS to .SH")

db.commit()

# Check result
result5 = db.execute(text("SELECT COUNT(*) FROM stocks"))
print(f"\nTotal stocks: {result5.scalar()}")

result6 = db.execute(text("SELECT symbol, name FROM stocks WHERE symbol LIKE '600031%' OR symbol LIKE '600519%' OR symbol LIKE '000651%'"))
print("\nSample stocks:")
for row in result6:
    print(f"  {row[0]}: {row[1]}")

db.close()
