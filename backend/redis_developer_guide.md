# Redis caching — developer guide (technical)

This is the technical companion to `app/redis.md` (UI-friendly).

---

## 1) Scope

- Redis is a cache layer for read-heavy APIs.
- Postgres remains source of truth.
- Cache failures are fail-open (API continues with DB).

---

## 2) Config source

Loaded from `app/utils.py`:

- `REDIS_HOST` or `host`
- `REDIS_PORT` or `port`
- `REDIS_PASSWORD` or `password`

`redis_cache.py` disables cache behavior when host is empty (`is_redis_configured()`).

---

## 3) `app/redis_cache.py` behavior

### Core helpers

- `is_redis_configured()`:
  - `True` only when `REDIS_HOST` is present.
- `get_redis_client()`:
  - Singleton async Redis client.
  - `ssl=True`, `decode_responses=True`, `password=REDIS_PASSWORD or None`.
- `close_redis_client()`:
  - Closes singleton on shutdown.

### Key/value ops

- `get_json(cache_key)`:
  - Returns parsed JSON or `None`.
- `set_json(cache_key, value, ttl_seconds=300)`:
  - `SETEX` JSON value.
- `delete_key(cache_key)`:
  - Deletes one key.

### Deterministic key builder

- `build_cache_key(prefix, **params)`:
  - Drops `None` params.
  - Sorts fields.
  - Creates stable compact JSON key.

### Tag indexing

- `set_json_with_tags(cache_key, value, ttl_seconds, tags)`:
  - Writes value.
  - Adds key to each tag set (`SADD`).
  - Keeps tag set alive longer than value TTL (`EXPIRE`).
- `invalidate_tag(tag)`:
  - `SMEMBERS tag` -> `DEL` keys -> `DEL tag`.

### Pattern delete utility

- `delete_by_pattern(pattern)`:
  - `SCAN` + `DEL` utility; tags are preferred for normal invalidation.

### Read-through orchestration

- `get_or_set_json(cache_key, loader, ttl_seconds=300, tags=None)`:
  1. Return cached value if hit.
  2. Try Redis loader lock (`SET lock_key NX EX`).
  3. Lock owner runs loader and writes cache+tags.
  4. Non-owner polls cache for a bounded window.
  5. Rare timeout fallback runs loader and writes anyway.
  6. Uses jittered TTL (~90%-110%, min 30s) to spread expiries.

---

## 4) Customer API integration (`app/customer_registration/customer.py`)

### Cache keys

- Detail endpoint key:
  - Prefix `customer:get_by_id`
  - Params include `customer_id`, normalized `role`, `emp_id`.
- Filter endpoint key:
  - Prefix `customer:filter`
  - Includes role, emp_id, filters, pagination, cursor.

### Tags

- `customer:get_by_id:index:{customer_id}`
- `customer:filter:index`

### Reads

- `get_customer_by_id` uses `get_or_set_json(..., tags=[detail_tag])`.
- `filter_customers` uses `get_or_set_json(..., tags=[filter_tag])`.

### Writes (invalidation)

After successful mutation, `_invalidate_customer_cache(customer_id)` invalidates:

1. Detail tag for that customer
2. Filter list tag

Called from:

- `create_customer`
- `edit_customer`
- `soft_delete_customer`
- `activate_customer`

---

## 5) App lifecycle

`app/main.py` shutdown sequence includes:

- `close_db_pool()`
- `close_redis_client()`

---

## 6) Known tradeoffs

- Permission/JWT changes may remain stale until TTL unless separately invalidated.
- Rare duplicate DB read can happen on lock timeout fallback.
- TTL policy is performance vs freshness tradeoff.

Redis & Caching — Simple Notes
1) What is Redis?
Redis is a very fast data store that keeps data in RAM (memory).
Because RAM is very fast, reading from Redis is much quicker than reading from database disk storage.
2) What is caching?
Caching means: save a recent API response temporarily, so next same request can return faster.
Instead of DB every time:
1st request -> DB -> save in Redis
2nd request -> Redis directly (if still valid)
3) Why it helps
Faster API response for repeated GET calls
Less load on Postgres
Better user experience in UI
4) What is RAM?
RAM is temporary, fast memory used by running apps.
Redis stores cached data in RAM.
If Redis restarts, RAM data may be lost (depends on persistence setup).
Cache data is temporary by design.
5) In-memory means what?
“In-memory” = data lives in RAM, not only on disk.
Very fast access
Good for temporary data like cache, sessions, counters
6) Your cache flow (simple)
For GET customer:
Build cache key (customer + role + emp)
Check Redis
If hit -> return cached response
If miss -> query DB
Save result to Redis with TTL (~300s)
Return response
For write APIs (create/edit/delete/activate):
Update DB
Invalidate related cache keys/tags
Next GET reloads fresh data from DB and re-caches
7) Main functions in your redis_cache.py (short)
is_redis_configured()
Checks if Redis host exists in env.
get_redis_client()
Creates/reuses one Redis client (singleton).
get_json(key)
Read JSON from Redis key. Returns None on miss/error.
set_json(key, value, ttl)
Save JSON to Redis with expiry time.
delete_key(key)
Delete one cache key.
build_cache_key(prefix, **params)
Makes stable key string from filters/params.
set_json_with_tags(key, value, ttl, tags)
Save value + register key under tags for group invalidation.
invalidate_tag(tag)
Delete all keys under a tag.
get_or_set_json(key, loader, ttl, tags)
Main helper:
try cache
if miss run loader(DB)
store and return
includes lock logic to reduce duplicate DB queries
close_redis_client()
Closes Redis connection on app shutdown.
8) Key terms
Cache hit: data found in Redis
Cache miss: not found -> fetch from DB
TTL: cache expiry time
Invalidate: remove old cache after data changes

---

## 7) Create/Edit/Delete/Activate invalidation flow (clarified)

This section explains exactly why write APIs call invalidation, even when create may not have a detail cache yet.

### One rule

- GET APIs read from cache when possible.
- Write APIs do not cache; they **invalidate** related cache buckets.

### What `_invalidate_customer_cache(customer_id)` clears

1. `customer:get_by_id:index:{customer_id}` (detail cache bucket for that customer)
2. `customer:filter:index` (list/filter cache bucket for customer lists)

### Why this is needed per operation

- **Create**
  - Detail cache for the new id may not exist yet (that is okay).
  - But filter/list caches often exist and are now stale (new row not visible).
  - So create invalidates mainly for list freshness; detail invalidation is harmless.

- **Edit**
  - Existing detail cache may contain old fields.
  - Existing list/filter cache may contain old row values.
  - Invalidate both, then next read rebuilds from DB.

- **Deactivate / Activate**
  - `is_active` and visibility outcomes change.
  - Both detail and list/filter caches can become stale.
  - Invalidate both, then next read rebuilds from DB.

### After invalidation, what happens next

On the next GET/filter call:

1. Cache lookup misses (`miss`)
2. API reads fresh data from DB
3. API stores fresh value in Redis (`stored`)
4. Following GETs become `hit` until TTL expiry or next invalidation

### Important behavior

- Invalidating a non-existing key/tag is safe (no-op).
- Tag sets can still list keys that already expired; deleting missing keys is safe.
- This is why always calling invalidation after successful write is a safe, consistent pattern.