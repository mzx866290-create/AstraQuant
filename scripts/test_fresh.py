import urllib.request, urllib.error, json

# Get token
data = json.dumps({'username': 'admin', 'password': '6216835Mo'}).encode()
req = urllib.request.Request('http://user-service:8000/api/v1/auth/login', data=data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
token = json.loads(resp.read().decode())['access_token']

# Test batch recommend - force fresh
req2 = urllib.request.Request(
    'http://localhost:8000/api/v1/analysis/score/batch/recommend?market=ALL&limit=10&force_refresh=true&strategy=auto&max_candidates=50',
    headers={'Authorization': f'Bearer {token}'}
)
resp2 = urllib.request.urlopen(req2, timeout=120)
result = json.loads(resp2.read().decode())
print(f"Method: {result.get('method')}")
print(f"Status: {result.get('status')}")
for r in result.get('recommendations', [])[:10]:
    print(f"  {r.get('symbol')} - name: '{r.get('name')}' score: {r.get('score')}")
