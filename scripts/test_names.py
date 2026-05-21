import urllib.request, urllib.error, json

# First get a token
data = json.dumps({'username': 'admin', 'password': '6216835Mo'}).encode()
req = urllib.request.Request('http://user-service:8000/api/v1/auth/login', data=data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
token = json.loads(resp.read().decode())['access_token']

# Test batch recommend - check name field
req2 = urllib.request.Request(
    'http://localhost:8000/api/v1/analysis/score/batch/recommend?market=ALL&limit=10&strategy=auto&max_candidates=50',
    headers={'Authorization': f'Bearer {token}'}
)
resp2 = urllib.request.urlopen(req2, timeout=60)
result = json.loads(resp2.read().decode())

recs = result.get('recommendations', [])
print(f"Total recommendations: {len(recs)}")
print("---")
for r in recs[:10]:
    print(f"  {r.get('symbol')} - name: '{r.get('name', 'MISSING')}' score: {r.get('score')}")

# Check stocks table
import sys, os
sys.path.insert(0, '/app')
sys.path.insert(0, '/backend')
from backend.shared.database import SessionLocal
from backend.shared.models import Stock

db = SessionLocal()
# Check if 600031.SH exists
s = db.query(Stock).filter(Stock.symbol == '600031.SH').first()
print(f"\n600031.SH in stocks table: {s is not None}")
if s:
    print(f"  name: {s.name}, market: {s.market}")
else:
    # Try .SS suffix
    s2 = db.query(Stock).filter(Stock.symbol == '600031.SS').first()
    print(f"600031.SS in stocks table: {s2 is not None}")
    if s2:
        print(f"  name: {s2.name}, market: {s2.market}")

# Count stocks by suffix
from sqlalchemy import func, text
result_q = db.execute(text("SELECT RIGHT(symbol, 2) as suffix, COUNT(*) as cnt FROM stocks GROUP BY RIGHT(symbol, 2)"))
print("\nStocks by suffix:")
for row in result_q:
    print(f"  .{row[0]}: {row[1]}")
db.close()
