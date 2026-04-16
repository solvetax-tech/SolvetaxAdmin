import json
import logging
import asyncio
import random
import hashlib
import time
from typing import Any, Awaitable, Callable, Optional, Sequence

import redis.asyncio as redis

from app.utils import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None

# Cross-worker / cross-task loader coordination (replaces per-key asyncio.Lock growth).
_LOADER_LOCK_KEY_PREFIX = "cache:loader:"
_LOADER_LOCK_TTL_SEC = 25
_LOADER_WAIT_ATTEMPTS = 200
_LOADER_WAIT_INTERVAL_SEC = 0.05
_REDIS_CONNECT_TIMEOUT_SEC = 0.5
_REDIS_COOLDOWN_SEC = 30
_redis_skip_until_ts = 0.0


def _log_cache_step(step: str, **fields: Any) -> None:
    parts = [f"cache_step={step}"]
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    logger.info(" ".join(parts))


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
            ssl=True,
            connect_timeout_sec=_REDIS_CONNECT_TIMEOUT_SEC,
        )
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            ssl=True,
            decode_responses=True,
            socket_connect_timeout=_REDIS_CONNECT_TIMEOUT_SEC,
            socket_timeout=_REDIS_CONNECT_TIMEOUT_SEC,
            retry_on_timeout=False,
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
    try:
        await get_redis_client().setex(
            cache_key,
            ttl_seconds,
            json.dumps(value, default=_json_default_serializer),
        )
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


def build_cache_key(prefix: str, **params: Any) -> str:
    # Canonical, order-stable key so equivalent filters map to same cache key.
    normalized = {
        k: v for k, v in sorted(params.items(), key=lambda item: item[0]) if v is not None
    }
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
        logger.info("cache_status=bypass key=%s", cache_key)
        _log_cache_step(
            "get_or_set_bypass",
            key=cache_key,
            redis_configured=is_redis_configured(),
            redis_cooldown=_redis_temporarily_disabled(),
        )
        return await loader()

    cached = await get_json(cache_key)
    if cached is not None:
        logger.info("cache_status=hit key=%s", cache_key)
        return cached
    logger.info("cache_status=miss key=%s", cache_key)
    _log_cache_step("get_or_set_miss", key=cache_key)
    if _redis_temporarily_disabled():
        # get_json likely just failed and opened cooldown; skip second Redis attempt.
        logger.info("cache_status=fallback key=%s reason=redis_cooldown", cache_key)
        _log_cache_step("get_or_set_fallback", key=cache_key, reason="redis_cooldown")
        return await loader()

    try:
        client = get_redis_client()
        lock_key = _loader_lock_redis_key(cache_key)
        _log_cache_step("get_or_set_lock_attempt", key=cache_key, lock_key=lock_key)
        acquired = await client.set(lock_key, "1", nx=True, ex=_LOADER_LOCK_TTL_SEC)
        _log_cache_step("get_or_set_lock_result", key=cache_key, acquired=bool(acquired))
    except Exception:
        _mark_redis_unhealthy()
        logger.info("cache_status=fallback key=%s reason=lock_acquire_failed", cache_key)
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
                logger.info("cache_status=hit key=%s source=double_check", cache_key)
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
            logger.info("cache_status=miss key=%s action=stored", cache_key)
            _log_cache_step("get_or_set_store_complete", key=cache_key, ttl_seconds=ttl_with_jitter)
            return value
        finally:
            try:
                await client.delete(lock_key)
                _log_cache_step("get_or_set_lock_released", key=cache_key, lock_key=lock_key)
            except Exception:
                logger.warning("Redis loader lock release failed for key=%s", cache_key, exc_info=True)
    else:
        _log_cache_step("get_or_set_wait_loop_start", key=cache_key, attempts=_LOADER_WAIT_ATTEMPTS)
        try:
            for _ in range(_LOADER_WAIT_ATTEMPTS):
                await asyncio.sleep(_LOADER_WAIT_INTERVAL_SEC)
                hit = await get_json(cache_key)
                if hit is not None:
                    logger.info("cache_status=hit key=%s source=wait_loop", cache_key)
                    _log_cache_step("get_or_set_hit_wait_loop", key=cache_key)
                    return hit
        except Exception:
            logger.info("cache_status=fallback key=%s reason=wait_loop_failed", cache_key)
            _log_cache_step("get_or_set_fallback", key=cache_key, reason="wait_loop_failed")
            logger.warning(
                "Redis wait loop failed for key=%s; using DB loader fallback",
                cache_key,
                exc_info=True,
            )
            return await loader()
        # Rare: lock holder slow or failed after setting cache; avoid hanging forever.
        logger.info("cache_status=fallback key=%s reason=wait_loop_timeout", cache_key)
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
