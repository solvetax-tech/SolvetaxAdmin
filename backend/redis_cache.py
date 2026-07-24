import json
import logging
import os
import asyncio
import random
import hashlib
import secrets
import time
from typing import Any, Awaitable, Callable, Optional, Sequence

import redis.asyncio as redis
from fastapi.encoders import jsonable_encoder

from backend.utils import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None

# Cross-worker / cross-task loader coordination (replaces per-key asyncio.Lock growth).
_LOADER_LOCK_KEY_PREFIX = "cache:loader:"
_LOADER_LOCK_TTL_SEC = 25
_LOADER_WAIT_ATTEMPTS = int(os.getenv("REDIS_LOADER_WAIT_ATTEMPTS", "40"))
_LOADER_WAIT_INTERVAL_SEC = float(os.getenv("REDIS_LOADER_WAIT_INTERVAL_SEC", "0.05"))
_REDIS_CONNECT_TIMEOUT_SEC = float(os.getenv("REDIS_CONNECT_TIMEOUT_SEC", "2"))
_REDIS_COOLDOWN_SEC = int(os.getenv("REDIS_COOLDOWN_SEC", "15"))
# Bound the pool so a request burst can't exceed the Azure Cache connection
# limit for the tier (Basic C0 allows 256). Health-check + keepalive keep pooled
# connections from going stale — Azure closes idle connections after ~10 min, and
# without a health check the first request afterwards fails and trips the cooldown.
_REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))
_REDIS_HEALTH_CHECK_INTERVAL_SEC = int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL_SEC", "30"))
# REDIS_SSL defaults to 'true' (Azure Cache for Redis requires TLS).
# Set REDIS_SSL=false or REDIS_SSL=disable for local/test environments.
_REDIS_USE_SSL: bool = os.getenv("REDIS_SSL", "true").strip().lower() not in ("false", "disable")
_redis_skip_until_ts = 0.0


def _log_cache_step(step: str, **fields: Any) -> None:
    parts = [f"cache_step={step}"]
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    logger.debug(" ".join(parts))


def is_redis_configured() -> bool:
    return bool(REDIS_HOST)


def _redis_temporarily_disabled() -> bool:
    return time.time() < _redis_skip_until_ts


def _mark_redis_unhealthy() -> None:
    global _redis_skip_until_ts
    _redis_skip_until_ts = time.time() + _REDIS_COOLDOWN_SEC
    _log_cache_step("redis_mark_unhealthy", cooldown_seconds=_REDIS_COOLDOWN_SEC)


def get_redis_client() -> redis.Redis:
    global _redis_client
    if not is_redis_configured():
        raise RuntimeError("Redis is not configured (set REDIS_HOST or host in .env)")
    if _redis_client is None:
        _log_cache_step(
            "redis_client_create",
            host=REDIS_HOST,
            port=REDIS_PORT,
            ssl=_REDIS_USE_SSL,
            connect_timeout_sec=_REDIS_CONNECT_TIMEOUT_SEC,
            max_connections=_REDIS_MAX_CONNECTIONS,
            health_check_interval_sec=_REDIS_HEALTH_CHECK_INTERVAL_SEC,
        )
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            ssl=_REDIS_USE_SSL,
            decode_responses=True,
            socket_connect_timeout=_REDIS_CONNECT_TIMEOUT_SEC,
            socket_timeout=_REDIS_CONNECT_TIMEOUT_SEC,
            # No command retries by design: fail fast and let callers fall back to
            # the DB (fail-open). Omitting retry_on_timeout leaves .retry=None (the
            # redis 8.x default); passing it only raised a deprecation warning.
            # Detect dead/idle-dropped connections before issuing a command so a
            # stale pooled socket transparently reconnects instead of failing the
            # request and tripping the unhealthy cooldown.
            socket_keepalive=True,
            health_check_interval=_REDIS_HEALTH_CHECK_INTERVAL_SEC,
            max_connections=_REDIS_MAX_CONNECTIONS,
        )
    return _redis_client


def _loader_lock_redis_key(cache_key: str) -> str:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return f"{_LOADER_LOCK_KEY_PREFIX}{digest}"


def _json_default_serializer(value: Any) -> Any:
    # Preserve structured payloads for Pydantic-like objects.
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        return value.model_dump()
    if hasattr(value, "dict") and callable(getattr(value, "dict")):
        return value.dict()
    return str(value)


async def get_json(cache_key: str) -> Optional[Any]:
    if not is_redis_configured() or _redis_temporarily_disabled():
        _log_cache_step(
            "get_json_bypass",
            key=cache_key,
            redis_configured=is_redis_configured(),
            redis_cooldown=_redis_temporarily_disabled(),
        )
        return None
    try:
        raw = await get_redis_client().get(cache_key)
        if not raw:
            _log_cache_step("get_json_miss", key=cache_key)
            return None
        _log_cache_step("get_json_hit", key=cache_key)
        return json.loads(raw)
    except Exception:
        _mark_redis_unhealthy()
        logger.warning("Redis get failed for key=%s", cache_key, exc_info=True)
        return None


async def set_json(cache_key: str, value: Any, ttl_seconds: int = 300) -> None:
    if not is_redis_configured() or _redis_temporarily_disabled():
        _log_cache_step(
            "set_json_bypass",
            key=cache_key,
            ttl_seconds=ttl_seconds,
            redis_configured=is_redis_configured(),
            redis_cooldown=_redis_temporarily_disabled(),
        )
        return
    # Encode with the SAME encoder FastAPI applies to endpoint return values, so a
    # cache HIT (deserialized JSON) has the identical shape to a cache MISS (the
    # loader's raw object re-encoded by FastAPI). Without this, datetime cached via
    # str() came back "2026-07-15 10:30:00" on a hit vs ISO "2026-07-15T10:30:00"
    # on a miss, and Decimal came back as a JSON string on a hit vs a number on a
    # miss. Serialize OUTSIDE the Redis try so a serialization failure skips the
    # write without tripping the unhealthy cooldown.
    try:
        payload = json.dumps(jsonable_encoder(value), default=_json_default_serializer)
    except Exception:
        logger.warning(
            "Cache value serialization failed for key=%s; skipping cache write",
            cache_key,
            exc_info=True,
        )
        return
    try:
        await get_redis_client().setex(cache_key, ttl_seconds, payload)
        _log_cache_step("set_json_success", key=cache_key, ttl_seconds=ttl_seconds)
    except Exception:
        _mark_redis_unhealthy()
        logger.warning("Redis set failed for key=%s", cache_key, exc_info=True)


async def delete_key(cache_key: str) -> None:
    if not is_redis_configured() or _redis_temporarily_disabled():
        _log_cache_step(
            "delete_key_bypass",
            key=cache_key,
            redis_configured=is_redis_configured(),
            redis_cooldown=_redis_temporarily_disabled(),
        )
        return
    try:
        deleted = await get_redis_client().delete(cache_key)
        _log_cache_step("delete_key_success", key=cache_key, deleted=deleted)
    except Exception:
        _mark_redis_unhealthy()
        logger.warning("Redis delete failed for key=%s", cache_key, exc_info=True)


# Atomic INCR + EXPIRE. A plain "incr, then if value==1 expire" leaves a window:
# if the EXPIRE is lost (a blip between the two calls), the counter survives with
# NO TTL and never resets — every later request sees count > limit, permanently
# locking out that identifier (rate-limit bucket / OTP-attempt key). Running both
# in one Lua script closes that window, and the TTL-repair branch heals any key
# that was already stranded without an expiry.
_INCR_WITH_TTL_LUA = (
    "local v = redis.call('INCR', KEYS[1]) "
    "if v == 1 then "
    "  redis.call('EXPIRE', KEYS[1], ARGV[1]) "
    "elseif redis.call('TTL', KEYS[1]) < 0 then "
    "  redis.call('EXPIRE', KEYS[1], ARGV[1]) "
    "end "
    "return v"
)


async def incr_with_ttl(key: str, ttl_seconds: int) -> Optional[int]:
    """Atomically increment a counter, guaranteeing it always carries a TTL.

    Returns the new value, or None when Redis is unavailable so callers can
    fail open (never lock out a legitimate user during a Redis outage).
    """
    if not is_redis_configured() or _redis_temporarily_disabled():
        return None
    try:
        value = await get_redis_client().eval(_INCR_WITH_TTL_LUA, 1, key, ttl_seconds)
        return int(value)
    except Exception:
        _mark_redis_unhealthy()
        logger.warning("Redis incr failed for key=%s", key, exc_info=True)
        return None


async def get_int(key: str) -> Optional[int]:
    """Read an integer counter. Returns 0 if unset, or None if Redis is down."""
    if not is_redis_configured() or _redis_temporarily_disabled():
        return None
    try:
        raw = await get_redis_client().get(key)
        return int(raw) if raw is not None else 0
    except Exception:
        _mark_redis_unhealthy()
        logger.warning("Redis get_int failed for key=%s", key, exc_info=True)
        return None


async def acquire_lock(key: str, token: str, ttl_seconds: int) -> bool:
    """Try to acquire a distributed lock (SET NX EX). Returns True if acquired.

    Fails CLOSED (returns False) when Redis is unavailable — a caller that needs
    a single fleet-wide runner (e.g. the scheduler) must decide separately
    whether to proceed when Redis is unconfigured vs merely down.
    """
    if not is_redis_configured() or _redis_temporarily_disabled():
        return False
    try:
        return bool(await get_redis_client().set(key, token, nx=True, ex=ttl_seconds))
    except Exception:
        _mark_redis_unhealthy()
        logger.warning("Redis acquire_lock failed for key=%s", key, exc_info=True)
        return False


async def release_lock(key: str, token: str) -> None:
    """Release a lock only if we still own it (compare-and-delete via Lua).

    Guards against deleting a lock another instance re-acquired after our TTL
    expired mid-run.
    """
    if not is_redis_configured() or _redis_temporarily_disabled():
        return
    try:
        lua = (
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('del', KEYS[1]) else return 0 end"
        )
        await get_redis_client().eval(lua, 1, key, token)
    except Exception:
        _mark_redis_unhealthy()
        logger.warning("Redis release_lock failed for key=%s", key, exc_info=True)


async def redis_ping() -> bool:
    """Lightweight readiness check — True if Redis answers PING within timeout."""
    if not is_redis_configured():
        return False
    try:
        return bool(await get_redis_client().ping())
    except Exception:
        return False


async def close_redis_client() -> None:
    global _redis_client
    if _redis_client is None:
        return
    try:
        await _redis_client.aclose()
        _log_cache_step("redis_client_closed")
    except Exception:
        logger.warning("Redis close failed", exc_info=True)
    finally:
        _redis_client = None


def normalize_cache_role(role: Any) -> Optional[str]:
    """Uppercase/strip role so cache keys match SQL visibility (RM vs rm)."""
    if role is None:
        return None
    text = str(role).strip().upper()
    return text or None


def normalize_cache_emp_id(emp_id: Any) -> Optional[int]:
    if emp_id is None:
        return None
    try:
        return int(emp_id)
    except (TypeError, ValueError):
        return None


# Recommended TTLs for read-through GET caches (seconds).
CACHE_TTL_LIST = 90
CACHE_TTL_COUNTS = 90
CACHE_TTL_ALERTS = 120
CACHE_TTL_DETAIL = 120
CACHE_TTL_CONFIG = 300


def build_cache_key(prefix: str, **params: Any) -> str:
    # Canonical, order-stable key so equivalent filters map to same cache key.
    normalized: dict[str, Any] = {}
    for key, value in sorted(params.items(), key=lambda item: item[0]):
        if value is None:
            continue
        if key == "role":
            value = normalize_cache_role(value)
            if value is None:
                continue
        elif key == "emp_id":
            value = normalize_cache_emp_id(value)
            if value is None:
                continue
        normalized[key] = value
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}:{payload}"


async def delete_by_pattern(pattern: str) -> int:
    if not is_redis_configured() or _redis_temporarily_disabled():
        _log_cache_step(
            "delete_by_pattern_bypass",
            pattern=pattern,
            redis_configured=is_redis_configured(),
            redis_cooldown=_redis_temporarily_disabled(),
        )
        return 0
    deleted = 0
    try:
        client = get_redis_client()
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                deleted += await client.delete(*keys)
            if cursor == 0:
                break
        _log_cache_step("delete_by_pattern_success", pattern=pattern, deleted=deleted)
    except Exception:
        _mark_redis_unhealthy()
        logger.warning("Redis pattern delete failed for pattern=%s", pattern, exc_info=True)
    return deleted


async def set_json_with_tags(
    cache_key: str,
    value: Any,
    ttl_seconds: int = 300,
    tags: Optional[Sequence[str]] = None,
) -> None:
    if not is_redis_configured() or _redis_temporarily_disabled():
        _log_cache_step(
            "set_json_with_tags_bypass",
            key=cache_key,
            ttl_seconds=ttl_seconds,
            redis_configured=is_redis_configured(),
            redis_cooldown=_redis_temporarily_disabled(),
        )
        return
    await set_json(cache_key, value, ttl_seconds=ttl_seconds)
    if not tags:
        _log_cache_step("set_json_with_tags_no_tags", key=cache_key, ttl_seconds=ttl_seconds)
        return
    try:
        client = get_redis_client()
        for tag in tags:
            await client.sadd(tag, cache_key)
            # Keep tag index alive well past entry TTL so invalidate_tag can find members.
            await client.expire(tag, max(86400, int(ttl_seconds * 12) + 3600))
            _log_cache_step("set_json_with_tags_tag_added", key=cache_key, tag=tag, ttl_seconds=ttl_seconds)
    except Exception:
        _mark_redis_unhealthy()
        logger.warning("Redis tag index update failed for key=%s", cache_key, exc_info=True)


async def invalidate_tag(tag: str) -> int:
    if not is_redis_configured() or _redis_temporarily_disabled():
        _log_cache_step(
            "invalidate_tag_bypass",
            tag=tag,
            redis_configured=is_redis_configured(),
            redis_cooldown=_redis_temporarily_disabled(),
        )
        return 0
    deleted = 0
    try:
        client = get_redis_client()
        keys = await client.smembers(tag)
        if keys:
            deleted += await client.delete(*keys)
        await client.delete(tag)
        _log_cache_step("invalidate_tag_success", tag=tag, indexed_keys=len(keys), deleted=deleted)
    except Exception:
        _mark_redis_unhealthy()
        logger.warning("Redis tag invalidation failed for tag=%s", tag, exc_info=True)
    return deleted


async def get_or_set_json(
    cache_key: str,
    loader: Callable[[], Awaitable[Any]],
    ttl_seconds: int = 300,
    tags: Optional[Sequence[str]] = None,
) -> Any:
    _log_cache_step("get_or_set_start", key=cache_key, ttl_seconds=ttl_seconds, has_tags=bool(tags))
    if not is_redis_configured() or _redis_temporarily_disabled():
        logger.debug("cache_status=bypass key=%s", cache_key)
        _log_cache_step(
            "get_or_set_bypass",
            key=cache_key,
            redis_configured=is_redis_configured(),
            redis_cooldown=_redis_temporarily_disabled(),
        )
        return await loader()

    cached = await get_json(cache_key)
    if cached is not None:
        logger.debug("cache_status=hit key=%s", cache_key)
        return cached
    logger.debug("cache_status=miss key=%s", cache_key)
    _log_cache_step("get_or_set_miss", key=cache_key)
    if _redis_temporarily_disabled():
        # get_json likely just failed and opened cooldown; skip second Redis attempt.
        logger.debug("cache_status=fallback key=%s reason=redis_cooldown", cache_key)
        _log_cache_step("get_or_set_fallback", key=cache_key, reason="redis_cooldown")
        return await loader()

    try:
        client = get_redis_client()
        lock_key = _loader_lock_redis_key(cache_key)
        # Unique per-owner token so the lock is released with compare-and-delete:
        # a loader that overruns the lock TTL must not delete a lock another worker
        # has since acquired.
        lock_token = secrets.token_hex(16)
        _log_cache_step("get_or_set_lock_attempt", key=cache_key, lock_key=lock_key)
        acquired = await client.set(lock_key, lock_token, nx=True, ex=_LOADER_LOCK_TTL_SEC)
        _log_cache_step("get_or_set_lock_result", key=cache_key, acquired=bool(acquired))
    except Exception:
        _mark_redis_unhealthy()
        logger.debug("cache_status=fallback key=%s reason=lock_acquire_failed", cache_key)
        _log_cache_step("get_or_set_fallback", key=cache_key, reason="lock_acquire_failed")
        logger.warning(
            "Redis lock acquisition failed for key=%s; using DB loader fallback",
            cache_key,
            exc_info=True,
        )
        return await loader()

    if acquired:
        try:
            cached_again = await get_json(cache_key)
            if cached_again is not None:
                logger.debug("cache_status=hit key=%s source=double_check", cache_key)
                _log_cache_step("get_or_set_hit_double_check", key=cache_key)
                return cached_again
            _log_cache_step("get_or_set_loader_run", key=cache_key, mode="lock_owner")
            value = await loader()
            ttl_with_jitter = max(30, int(ttl_seconds * (0.9 + random.random() * 0.2)))
            await set_json_with_tags(
                cache_key,
                value,
                ttl_seconds=ttl_with_jitter,
                tags=tags,
            )
            logger.debug("cache_status=miss key=%s action=stored", cache_key)
            _log_cache_step("get_or_set_store_complete", key=cache_key, ttl_seconds=ttl_with_jitter)
            return value
        finally:
            # Compare-and-delete (only release the lock if we still own it) so a
            # slow loader can't clobber a lock another worker already re-acquired.
            await release_lock(lock_key, lock_token)
            _log_cache_step("get_or_set_lock_released", key=cache_key, lock_key=lock_key)
    else:
        _log_cache_step("get_or_set_wait_loop_start", key=cache_key, attempts=_LOADER_WAIT_ATTEMPTS)
        try:
            for _ in range(_LOADER_WAIT_ATTEMPTS):
                await asyncio.sleep(_LOADER_WAIT_INTERVAL_SEC)
                hit = await get_json(cache_key)
                if hit is not None:
                    logger.debug("cache_status=hit key=%s source=wait_loop", cache_key)
                    _log_cache_step("get_or_set_hit_wait_loop", key=cache_key)
                    return hit
        except Exception:
            logger.debug("cache_status=fallback key=%s reason=wait_loop_failed", cache_key)
            _log_cache_step("get_or_set_fallback", key=cache_key, reason="wait_loop_failed")
            logger.warning(
                "Redis wait loop failed for key=%s; using DB loader fallback",
                cache_key,
                exc_info=True,
            )
            return await loader()
        # Rare: lock holder slow or failed after setting cache; avoid hanging forever.
        logger.debug("cache_status=fallback key=%s reason=wait_loop_timeout", cache_key)
        _log_cache_step("get_or_set_fallback", key=cache_key, reason="wait_loop_timeout")
        _log_cache_step("get_or_set_loader_run", key=cache_key, mode="wait_timeout")
        value = await loader()
        ttl_with_jitter = max(30, int(ttl_seconds * (0.9 + random.random() * 0.2)))
        await set_json_with_tags(
            cache_key,
            value,
            ttl_seconds=ttl_with_jitter,
            tags=tags,
        )
        _log_cache_step("get_or_set_store_complete", key=cache_key, ttl_seconds=ttl_with_jitter)
        return value
