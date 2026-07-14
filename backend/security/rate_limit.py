"""Shared Redis-backed rate limiting (fleet-wide, fail-open on Redis outage).

Built on the fixed-window ``incr_with_ttl`` helper so it works consistently
across every uvicorn worker and container instance — unlike an in-process dict,
which multiplies the effective limit by the worker/instance count and resets on
restart. When Redis is unavailable the limiter fails OPEN (never hard-locks the
API during an outage).
"""

from fastapi import HTTPException

from backend.redis_cache import incr_with_ttl


async def enforce_rate_limit(
    identifier: str,
    *,
    bucket: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    """Raise HTTP 429 when ``identifier`` exceeds ``max_requests`` per window.

    ``identifier`` is any stable key for the caller — client IP, ``ip:email``,
    ``emp:<id>``, etc. ``bucket`` namespaces the limit (e.g. ``login``, ``api``).
    """
    key = f"rl:{bucket}:{identifier}"
    count = await incr_with_ttl(key, window_seconds)
    if count is None:
        return  # Redis unavailable → fail open
    if count > max_requests:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please slow down and try again shortly.",
            headers={"Retry-After": str(window_seconds)},
        )
