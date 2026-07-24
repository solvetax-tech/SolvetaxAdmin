"""Evolution API HTTP client — minimal wrapper for SolvetaxAdmin.

Only two operations are implemented (sendText + connectionState); everything
else (retries, outbox persistence, webhook receiver) belongs to later slices.

Auth: apikey header on every request (Evolution v2 model).
Env vars: EVOLUTION_API_URL, EVOLUTION_API_KEY — read at call time via os.getenv
so container env changes take effect without a reload.
Timeout: 10 seconds per eng-review decision (doc 06 §2.2).

Fail-open policy: errors are surfaced as EvolutionAPIError (a clear service
error), not as unhandled 500s, so a disconnected Evolution instance does not
break unrelated CRM routes.  The api key is NEVER included in error messages.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)


class EvolutionAPIError(Exception):
    """Raised on non-2xx, timeout, or connection failure from Evolution API.

    The message includes the HTTP status and a snippet of the response body
    (or error description), but never the api key.
    """


async def _make_client() -> httpx.AsyncClient:
    """Build an AsyncClient with the apikey header and 10-second timeout."""
    api_key = os.getenv("EVOLUTION_API_KEY", "")
    return httpx.AsyncClient(
        headers={"apikey": api_key},
        timeout=_TIMEOUT,
    )


async def _request(method: str, path: str, json: dict | None = None) -> httpx.Response:
    """Issue one request against EVOLUTION_API_URL; raise EvolutionAPIError on
    timeout, connection failure, or any non-2xx response."""
    base_url = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    url = f"{base_url}{path}"

    try:
        async with await _make_client() as client:
            response = await client.request(method, url, json=json)
    except httpx.RequestError as exc:
        # Covers timeouts, connection failures, and UnsupportedProtocol/InvalidURL
        # (e.g. EVOLUTION_API_URL unset) — all must surface as 502, never a 500.
        logger.error(
            "evolution_api_request_error type=%s url=%s error=%s",
            type(exc).__name__, url, exc,
        )
        raise EvolutionAPIError(
            f"Evolution API request failed ({type(exc).__name__}): {exc}"
        ) from exc

    if not response.is_success:
        snippet = response.text[:200]
        logger.error(
            "evolution_api_error method=%s url=%s status=%s snippet=%s",
            method,
            url,
            response.status_code,
            snippet,
        )
        raise EvolutionAPIError(
            f"Evolution API returned {response.status_code}: {snippet}"
        )

    return response


async def send_text(instance: str, jid: str, body: str) -> str:
    """POST /message/sendText/{instance}; return the Evolution message id (key.id).

    jid is 91XXXXXXXXXX@s.whatsapp.net.  Raises EvolutionAPIError on any failure.
    """
    response = await _request(
        "POST", f"/message/sendText/{instance}", json={"number": jid, "text": body}
    )

    data = response.json()
    try:
        message_id: str = data["key"]["id"]
    except (KeyError, TypeError) as exc:
        raise EvolutionAPIError(
            f"Unexpected Evolution API response shape: {data!r}"
        ) from exc

    logger.info(
        "evolution_send_ok instance=%s jid=%s message_id=%s", instance, jid, message_id
    )
    return message_id


async def connection_state(instance: str) -> dict:
    """GET /instance/connectionState/{instance}; return the raw state dict.

    Raises EvolutionAPIError on any failure.
    """
    response = await _request("GET", f"/instance/connectionState/{instance}")
    return response.json()
