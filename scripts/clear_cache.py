import redis
r = redis.from_url("redis://redis:6379")
keys = r.keys("daily_recommendations*")
print(f"Cache keys: {len(keys)}")
for k in keys[:10]:
    print(f"  {k}")

# Delete stale cache
if keys:
    r.delete(*keys)
    print("Deleted all daily_recommendations cache keys")
