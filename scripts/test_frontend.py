import urllib.request, urllib.error, json

# Get token
data = json.dumps({'username': 'admin', 'password': '6216835Mo'}).encode()
req = urllib.request.Request('http://user-service:8000/api/v1/auth/login', data=data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
token = json.loads(resp.read().decode())['access_token']

# Test exactly like frontend does (force_refresh=false)
req2 = urllib.request.Request(
    'http://localhost:8000/api/v1/analysis/score/batch/recommend?market=ALL&limit=50&force_refresh=false&strategy=auto&max_candidates=200&include_evidence=true&include_debate=true&initial_full_scan=false',
    headers={'Authorization': f'Bearer {token}'}
)
resp2 = urllib.request.urlopen(req2, timeout=60)
result = json.loads(resp2.read().decode())
recs = result.get('recommendations', [])
print(f"Count: {len(recs)}")
print(f"Status: {result.get('status')}")
print(f"Pipeline: {result.get('pipeline_status')}")
has_name = sum(1 for r in recs if r.get('name'))
print(f"With name: {has_name}/{len(recs)}")
for r in recs[:10]:
    print(f"  {r.get('symbol')} - '{r.get('name')}' score={r.get('score')}")
