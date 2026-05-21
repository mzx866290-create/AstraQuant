import redis
r = redis.from_url("redis://redis:6379")
all_keys = r.keys("*")
print(f"Total Redis keys: {len(all_keys)}")
for k in all_keys:
    print(f"  {k}")
r.flushdb()
print("\nFlushed all Redis cache")
