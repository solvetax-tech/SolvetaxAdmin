"""Tests for whatsapp/router.py error-mapping logic.

Design note: The TokenValidatorMiddleware validates JWT tokens against a live
database session table, making TestClient integration tests require a full DB
with seeded employee/session rows — disproportionate for what is essentially an
error-mapping layer.  We therefore test the error-mapping as plain async
functions (calling the FastAPI route handlers directly) with all dependencies
monkeypatched.  The valuable assertions are the HTTP status codes returned for
each guardrail error, which are the unique contract of this router.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from backend.whatsapp.send_service import ConsentError, QuietHoursError, RateLimitError
from backend.whatsapp.client import EvolutionAPIError
from backend.whatsapp.router import SendRequest, whatsapp_send, whatsapp_instance_status


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

_FAKE_USER = {"sub": "1", "role": "EMPLOYEE", "permissions": {"platform": {"EMPLOYEE": ["READ"]}}}
_ADMIN_USER = {"sub": "1", "role": "ADMIN", "permissions": {}}

_VALID_PAYLOAD = SendRequest(phone="9999999999", body="Hello")


def _mock_pool_conn():
    """Return a mock pool whose acquire() context manager yields a mock conn."""
    conn = AsyncMock()
    pool = MagicMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = cm
    return pool, conn


# ---------------------------------------------------------------------------
# send route — error mapping
# ---------------------------------------------------------------------------

async def test_send_consent_error_maps_to_403(monkeypatch):
    pool, _conn = _mock_pool_conn()
    monkeypatch.setattr("backend.whatsapp.router.backend_utils.get_db_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr("backend.whatsapp.router.is_redis_configured", lambda: True)
    monkeypatch.setattr("backend.whatsapp.router.get_redis_client", lambda: MagicMock())
    monkeypatch.setattr(
        "backend.whatsapp.router.send",
        AsyncMock(side_effect=ConsentError("no consent")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await whatsapp_send(_VALID_PAYLOAD, current_user=_FAKE_USER)

    assert exc_info.value.status_code == 403


async def test_send_quiet_hours_error_maps_to_422(monkeypatch):
    pool, _conn = _mock_pool_conn()
    monkeypatch.setattr("backend.whatsapp.router.backend_utils.get_db_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr("backend.whatsapp.router.is_redis_configured", lambda: True)
    monkeypatch.setattr("backend.whatsapp.router.get_redis_client", lambda: MagicMock())
    monkeypatch.setattr(
        "backend.whatsapp.router.send",
        AsyncMock(side_effect=QuietHoursError("quiet hours")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await whatsapp_send(_VALID_PAYLOAD, current_user=_FAKE_USER)

    assert exc_info.value.status_code == 422


async def test_send_rate_limit_error_maps_to_429(monkeypatch):
    pool, _conn = _mock_pool_conn()
    monkeypatch.setattr("backend.whatsapp.router.backend_utils.get_db_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr("backend.whatsapp.router.is_redis_configured", lambda: True)
    monkeypatch.setattr("backend.whatsapp.router.get_redis_client", lambda: MagicMock())
    monkeypatch.setattr(
        "backend.whatsapp.router.send",
        AsyncMock(side_effect=RateLimitError("cap hit")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await whatsapp_send(_VALID_PAYLOAD, current_user=_FAKE_USER)

    assert exc_info.value.status_code == 429


async def test_send_evolution_error_maps_to_502(monkeypatch):
    pool, _conn = _mock_pool_conn()
    monkeypatch.setattr("backend.whatsapp.router.backend_utils.get_db_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr("backend.whatsapp.router.is_redis_configured", lambda: True)
    monkeypatch.setattr("backend.whatsapp.router.get_redis_client", lambda: MagicMock())
    monkeypatch.setattr(
        "backend.whatsapp.router.send",
        AsyncMock(side_effect=EvolutionAPIError("evo down")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await whatsapp_send(_VALID_PAYLOAD, current_user=_FAKE_USER)

    assert exc_info.value.status_code == 502


async def test_send_success_returns_message_id(monkeypatch):
    pool, _conn = _mock_pool_conn()
    monkeypatch.setattr("backend.whatsapp.router.backend_utils.get_db_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr("backend.whatsapp.router.is_redis_configured", lambda: True)
    monkeypatch.setattr("backend.whatsapp.router.get_redis_client", lambda: MagicMock())
    monkeypatch.setattr(
        "backend.whatsapp.router.send",
        AsyncMock(return_value="evo-id-xyz"),
    )

    result = await whatsapp_send(_VALID_PAYLOAD, current_user=_FAKE_USER)
    assert result.message_id == "evo-id-xyz"


# ---------------------------------------------------------------------------
# instance/status route — error mapping
# ---------------------------------------------------------------------------

async def test_instance_status_no_active_rows_returns_409(monkeypatch):
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = cm

    monkeypatch.setattr("backend.whatsapp.router.backend_utils.get_db_pool", AsyncMock(return_value=pool))

    with pytest.raises(HTTPException) as exc_info:
        await whatsapp_instance_status(current_user=_ADMIN_USER)

    assert exc_info.value.status_code == 409


async def test_instance_status_multiple_active_rows_returns_409(monkeypatch):
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[
        {"instance_name": "primary"},
        {"instance_name": "secondary"},
    ])
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = cm

    monkeypatch.setattr("backend.whatsapp.router.backend_utils.get_db_pool", AsyncMock(return_value=pool))

    with pytest.raises(HTTPException) as exc_info:
        await whatsapp_instance_status(current_user=_ADMIN_USER)

    assert exc_info.value.status_code == 409


async def test_instance_status_evolution_error_returns_502(monkeypatch):
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"instance_name": "primary"}])
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = cm

    monkeypatch.setattr("backend.whatsapp.router.backend_utils.get_db_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(
        "backend.whatsapp.router.evo_client.connection_state",
        AsyncMock(side_effect=EvolutionAPIError("unreachable")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await whatsapp_instance_status(current_user=_ADMIN_USER)

    assert exc_info.value.status_code == 502


async def test_instance_status_success(monkeypatch):
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"instance_name": "primary"}])
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = cm

    state_data = {"instance": {"instanceName": "primary", "state": "open"}}
    monkeypatch.setattr("backend.whatsapp.router.backend_utils.get_db_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(
        "backend.whatsapp.router.evo_client.connection_state",
        AsyncMock(return_value=state_data),
    )

    result = await whatsapp_instance_status(current_user=_ADMIN_USER)
    assert result.instance == "primary"
    assert result.state == state_data
