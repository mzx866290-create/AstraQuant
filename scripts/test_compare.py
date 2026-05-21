import urllib.request, urllib.error, json

# Get token
data = json.dumps({'username': 'admin', 'password': '6216835Mo'}).encode()
req = urllib.request.Request('http://user-service:8000/api/v1/auth/login', data=data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
token = json.loads(resp.read().decode())['access_token']

# Test compare
req2 = urllib.request.Request(
    'http://localhost:8000/api/v1/analysis/compare?symbols=600519.SH,000858.SZ,601318.SH&indicators=ma5,ma20,rsi',
    headers={'Authorization': f'Bearer {token}'}
)
try:
    resp2 = urllib.request.urlopen(req2, timeout=30)
    result = json.loads(resp2.read().decode())
    print(f"Compare status: {resp2.status}")
    print(f"Result keys: {list(result.keys()) if isinstance(result, dict) else 'list'}")
    print(json.dumps(result, ensure_ascii=False)[:600])
except urllib.error.HTTPError as e:
    print(f"Error: {e.code}")
    print(e.read().decode()[:300])

# Test batch recommend names
print("\n--- Batch Recommend ---")
req3 = urllib.request.Request(
    'http://localhost:8000/api/v1/analysis/score/batch/recommend?market=ALL&limit=5&strategy=auto&max_candidates=50',
    headers={'Authorization': f'Bearer {token}'}
)
resp3 = urllib.request.urlopen(req3, timeout=60)
result3 = json.loads(resp3.read().decode())
for r in result3.get('recommendations', [])[:5]:
    print(f"  {r.get('symbol')} - name: '{r.get('name')}' score: {r.get('score')}")
