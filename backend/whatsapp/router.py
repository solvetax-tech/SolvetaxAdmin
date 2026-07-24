"""WhatsApp API endpoints.

Phase 1 endpoints
-----------------
POST /api/v1/whatsapp/send
    Staff-initiated send.  Auth: require_permission("EMPLOYEE", "READ") — same
    guard used for staff read endpoints in crm_leads_common.py.
    Calls send_service.send() with EvolutionSink.

GET /api/v1/whatsapp/instance/status
    Admin-only: resolves the single active wa_instance_config row and proxies
    connection_state from the Evolution API.

Not included (later slices)
---------------------------
- Webhook receiver (Phase 2 / doc 04)
- wa_outbox writes (Slice 1 per doc 09 §3.5) — see comment in send route below
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import utils as backend_utils
from backend.redis_cache import get_redis_client, is_redis_configured
from backend.security.rbac import require_admin, require_permission
from backend.whatsapp import client as evo_client
from backend.whatsapp.client import EvolutionAPIError
from backend.whatsapp.flows_router import flows_router
from backend.whatsapp.send_service import ConsentError, QuietHoursError, RateLimitError, send
from backend.whatsapp.sinks import EvolutionSink

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/whatsapp", tags=["whatsapp"])
router.include_router(flows_router)


class SendRequest(BaseModel):
    phone: str = Field(..., pattern=r"^\d{10}$", description="10-digit Indian mobile number")
    body: str = Field(..., min_length=1)


class SendResponse(BaseModel):
    message_id: str


class InstanceStatusResponse(BaseModel):
    instance: str
    state: dict


@router.post("/send", response_model=SendResponse)
async def whatsapp_send(
    payload: SendRequest,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """Staff-initiated WhatsApp message send.

    Runs all guardrails (consent → quiet hours → daily cap) via send_service,
    then dispatches through EvolutionSink to the Evolution API.

    TODO Slice 1: persist a wa_outbox row after successful send (doc 09 §3.5).
    """
    pool = await backend_utils.get_db_pool()

    if not is_redis_configured():
        raise HTTPException(status_code=503, detail="Redis is not configured; cannot enforce rate limits")

    redis = get_redis_client()
    sink = EvolutionSink()

    try:
        async with pool.acquire() as conn:
            message_id = await send(
                conn=conn,
                redis=redis,
                phone=payload.phone,
                body=payload.body,
                category="staff_manual",
                sink=sink,
            )
    except ConsentError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except QuietHoursError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except EvolutionAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return SendResponse(message_id=message_id)


@router.get("/instance/status", response_model=InstanceStatusResponse)
async def whatsapp_instance_status(
    current_user=Depends(require_admin()),
):
    """Return the connection state of the single active Evolution API instance.

    Resolves the active wa_instance_config row (exactly one must be active)
    and proxies GET /instance/connectionState/{instance} from Evolution API.

    Returns 409 if 0 or more than 1 active rows exist (mirrors the
    single-active-instance rule enforced in send_service).
    """
    pool = await backend_utils.get_db_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT instance_name FROM {backend_utils.DB_SCHEMA}.wa_instance_config"
            f" WHERE is_active = true"
        )

    if len(rows) == 0:
        raise HTTPException(
            status_code=409,
            detail="No active wa_instance_config row found; cannot determine active instance",
        )
    if len(rows) > 1:
        names = [r["instance_name"] for r in rows]
        raise HTTPException(
            status_code=409,
            detail=f"Multiple active wa_instance_config rows found: {names}; exactly one must be active",
        )

    instance_name: str = rows[0]["instance_name"]

    try:
        state = await evo_client.connection_state(instance_name)
    except EvolutionAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return InstanceStatusResponse(instance=instance_name, state=state)
