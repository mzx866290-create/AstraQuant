import sys, os
sys.path.insert(0, '/app')
sys.path.insert(0, '/backend')
sys.path.insert(0, '/')
os.chdir('/app')

from backend.shared.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
r = db.execute(text('SELECT snapshot_date, COUNT(*) FROM research_observations GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 5'))
print('Observations by date:')
for row in r:
    print(f'  {row[0]}: {row[1]}')
r2 = db.execute(text('SELECT COUNT(*) FROM research_observations'))
print(f'Total: {r2.scalar()}')
db.close()
