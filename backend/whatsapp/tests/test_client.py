"""Tests for backend/whatsapp/client.py — all network-free via httpx.MockTransport.

Covers
------
- 201 response → returns key.id
- 401 / 500 response → EvolutionAPIError (api key not in message)
- Connect timeout → EvolutionAPIError (api key not in message)
"""
import httpx
import pytest

from backend.whatsapp.client import EvolutionAPIError, send_text, connection_state


# ---------------------------------------------------------------------------
# MockTransport helpers
# ---------------------------------------------------------------------------

def _make_transport(status_code: int, body: dict | None = None, text: str = "") -> httpx.MockTransport:
    """Return a MockTransport that always replies with the given status/body."""
    import json as _json

    content = _json.dumps(body).encode() if body is not None else text.encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            content=content,
            headers={"content-type": "application/json"},
        )

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# send_text tests
# ---------------------------------------------------------------------------

async def test_send_text_201_returns_key_id(monkeypatch):
    """201 response with valid key.id → returned as the message id."""
    fake_body = {"key": {"id": "ABC123XYZ", "fromMe": True, "remoteJid": "919999999999@s.whatsapp.net"}}
    transport = _make_transport(201, fake_body)

    monkeypatch.setenv("EVOLUTION_API_URL", "http://evo.local")
    monkeypatch.setenv("EVOLUTION_API_KEY", "secret-key")

    # Patch _make_client to inject our transport
    import backend.whatsapp.client as client_mod

    async def _patched_make_client():
        return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(10.0))

    monkeypatch.setattr(client_mod, "_make_client", _patched_make_client)

    result = await send_text("primary", "919999999999@s.whatsapp.net", "Hello")
    assert result == "ABC123XYZ"


async def test_send_text_401_raises_evolution_error(monkeypatch):
    """401 → EvolutionAPIError; api key must not appear in the message."""
    transport = _make_transport(401, text="Unauthorized")

    monkeypatch.setenv("EVOLUTION_API_URL", "http://evo.local")
    monkeypatch.setenv("EVOLUTION_API_KEY", "my-secret-api-key")

    import backend.whatsapp.client as client_mod

    async def _patched_make_client():
        return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(10.0))

    monkeypatch.setattr(client_mod, "_make_client", _patched_make_client)

    with pytest.raises(EvolutionAPIError) as exc_info:
        await send_text("primary", "919999999999@s.whatsapp.net", "Hello")

    assert "401" in str(exc_info.value)
    assert "my-secret-api-key" not in str(exc_info.value)


async def test_send_text_500_raises_evolution_error(monkeypatch):
    """500 → EvolutionAPIError; api key must not appear in the message."""
    transport = _make_transport(500, text="Internal Server Error")

    monkeypatch.setenv("EVOLUTION_API_URL", "http://evo.local")
    monkeypatch.setenv("EVOLUTION_API_KEY", "another-secret")

    import backend.whatsapp.client as client_mod

    async def _patched_make_client():
        return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(10.0))

    monkeypatch.setattr(client_mod, "_make_client", _patched_make_client)

    with pytest.raises(EvolutionAPIError) as exc_info:
        await send_text("primary", "919999999999@s.whatsapp.net", "Hello")

    assert "500" in str(exc_info.value)
    assert "another-secret" not in str(exc_info.value)


async def test_send_text_connect_timeout_raises_evolution_error(monkeypatch):
    """ConnectError → EvolutionAPIError; api key must not appear in the message."""
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evo.local")
    monkeypatch.setenv("EVOLUTION_API_KEY", "super-secret")

    import backend.whatsapp.client as client_mod

    def _timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    async def _patched_make_client():
        return httpx.AsyncClient(
            transport=httpx.MockTransport(_timeout_handler),
            timeout=httpx.Timeout(10.0),
        )

    monkeypatch.setattr(client_mod, "_make_client", _patched_make_client)

    with pytest.raises(EvolutionAPIError) as exc_info:
        await send_text("primary", "919999999999@s.whatsapp.net", "Hello")

    assert "super-secret" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# connection_state tests
# ---------------------------------------------------------------------------

async def test_connection_state_200_returns_dict(monkeypatch):
    """200 response → dict with state info returned."""
    state_body = {"instance": {"instanceName": "primary", "state": "open"}}
    transport = _make_transport(200, state_body)

    monkeypatch.setenv("EVOLUTION_API_URL", "http://evo.local")
    monkeypatch.setenv("EVOLUTION_API_KEY", "secret-key")

    import backend.whatsapp.client as client_mod

    async def _patched_make_client():
        return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(10.0))

    monkeypatch.setattr(client_mod, "_make_client", _patched_make_client)

    result = await connection_state("primary")
    assert result == state_body


async def test_connection_state_non_2xx_raises(monkeypatch):
    """Non-2xx response → EvolutionAPIError."""
    transport = _make_transport(404, text="Not Found")

    monkeypatch.setenv("EVOLUTION_API_URL", "http://evo.local")
    monkeypatch.setenv("EVOLUTION_API_KEY", "key")

    import backend.whatsapp.client as client_mod

    async def _patched_make_client():
        return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(10.0))

    monkeypatch.setattr(client_mod, "_make_client", _patched_make_client)

    with pytest.raises(EvolutionAPIError):
        await connection_state("primary")


async def test_missing_base_url_raises_evolution_error(monkeypatch):
    """EVOLUTION_API_URL unset → UnsupportedProtocol must map to EvolutionAPIError,
    not escape as an unhandled 500 (QA bug 2, 2026-07-24)."""
    from backend.whatsapp import client as client_mod

    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    with pytest.raises(client_mod.EvolutionAPIError) as exc_info:
        await client_mod.connection_state("primary")
    assert "UnsupportedProtocol" in str(exc_info.value) or "request failed" in str(exc_info.value)
