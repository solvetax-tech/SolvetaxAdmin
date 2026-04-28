import os
import time
from fastapi import HTTPException, Request

from app.redis_cache import get_redis_client, is_redis_configured


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_public_rate_limit(
    request: Request,
    bucket: str,
    max_requests: int = 20,
    window_seconds: int = 60,
    block_seconds: int = 300,
) -> None:
    """
    Lightweight in-memory limiter for public endpoints.
    - buckets by endpoint + IP
    - sliding time window
    - temporary block on repeated abuse
    """
    now_epoch = int(time.time())
    ip = get_client_ip(request)
    identifier = f"{bucket}:{ip}"

    if not hasattr(request.app.state, "public_rate_limit_store"):
        request.app.state.public_rate_limit_store = {}
    store = request.app.state.public_rate_limit_store

    record = store.get(identifier) or {"hits": [], "blocked_until": 0}

    blocked_until = int(record.get("blocked_until") or 0)
    if blocked_until > now_epoch:
        retry_after = blocked_until - now_epoch
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Retry after {retry_after} seconds.",
        )

    hits = [t for t in (record.get("hits") or []) if t > now_epoch - window_seconds]
    if len(hits) >= max_requests:
        store[identifier] = {"hits": hits, "blocked_until": now_epoch + block_seconds}
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
        )

    hits.append(now_epoch)
    store[identifier] = {"hits": hits, "blocked_until": 0}


async def _enforce_public_rate_limit_redis(
    request: Request,
    bucket: str,
    max_requests: int,
    window_seconds: int,
    block_seconds: int,
) -> None:
    now_epoch = int(time.time())
    ip = get_client_ip(request)
    identifier = f"{bucket}:{ip}"
    key_hits = f"public:rl:hits:{identifier}"
    key_block = f"public:rl:block:{identifier}"

    client = get_redis_client()
    blocked_ttl = await client.ttl(key_block)
    if blocked_ttl and blocked_ttl > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Retry after {blocked_ttl} seconds.",
        )

    min_ts = now_epoch - window_seconds
    await client.zremrangebyscore(key_hits, 0, min_ts)
    count = await client.zcard(key_hits)
    if count >= max_requests:
        await client.setex(key_block, block_seconds, "1")
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
        )

    # member must be unique; use timestamp + millis
    member = f"{now_epoch}:{int(time.time_ns() % 1_000_000)}"
    await client.zadd(key_hits, {member: now_epoch})
    await client.expire(key_hits, max(window_seconds + 30, 60))


def _get_required_public_api_key() -> str:
    return (os.getenv("PUBLIC_API_KEY") or "").strip()


def enforce_public_api_key(request: Request) -> None:
    required_key = _get_required_public_api_key()
    if not required_key:
        raise HTTPException(status_code=503, detail="Public API is not configured.")
    provided_key = (request.headers.get("X-Public-Api-Key") or "").strip()
    if not provided_key or provided_key != required_key:
        raise HTTPException(status_code=401, detail="Invalid or missing public API key.")


async def enforce_public_security(
    request: Request,
    bucket: str,
    max_requests: int = 20,
    window_seconds: int = 60,
    block_seconds: int = 300,
) -> None:
    enforce_public_api_key(request)

    if is_redis_configured():
        try:
            await _enforce_public_rate_limit_redis(
                request=request,
                bucket=bucket,
                max_requests=max_requests,
                window_seconds=window_seconds,
                block_seconds=block_seconds,
            )
            return
        except HTTPException:
            raise
        except Exception:
            # Redis issue should not take public API down; fallback to memory limiter.
            pass

    await enforce_public_rate_limit(
        request=request,
        bucket=bucket,
        max_requests=max_requests,
        window_seconds=window_seconds,
        block_seconds=block_seconds,
    )
