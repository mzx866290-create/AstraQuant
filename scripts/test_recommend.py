import urllib.request, urllib.error, json

# First get a token
data = json.dumps({'username': 'admin', 'password': '6216835Mo'}).encode()
req = urllib.request.Request('http://user-service:8000/api/v1/auth/login', data=data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
token = json.loads(resp.read().decode())['access_token']

# Now test batch recommend
req2 = urllib.request.Request(
    'http://localhost:8000/api/v1/analysis/score/batch/recommend?market=ALL&limit=5&strategy=auto&max_candidates=50',
    headers={'Authorization': f'Bearer {token}'}
)
resp2 = urllib.request.urlopen(req2, timeout=60)
result = json.loads(resp2.read().decode())
print('Keys:', list(result.keys()) if isinstance(result, dict) else type(result))
if isinstance(result, dict) and 'recommendations' in result:
    for r in result['recommendations'][:3]:
        print(f"  {r.get('symbol')} - name: {r.get('name', 'MISSING')} score: {r.get('score')}")
elif isinstance(result, list):
    for r in result[:3]:
        print(f"  {r.get('symbol')} - name: {r.get('name', 'MISSING')} score: {r.get('score')}")
else:
    print(json.dumps(result, ensure_ascii=False)[:800])
