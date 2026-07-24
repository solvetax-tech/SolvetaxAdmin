"""WhatsApp flow definition CRUD endpoints.

Registered in router.py as a sub-router; resolves to:
  GET    /api/v1/whatsapp/flows
  POST   /api/v1/whatsapp/flows
  GET    /api/v1/whatsapp/flows/{flow_id}
  PUT    /api/v1/whatsapp/flows/{flow_id}/draft
  POST   /api/v1/whatsapp/flows/{flow_id}/validate
  POST   /api/v1/whatsapp/flows/{flow_id}/publish
  POST   /api/v1/whatsapp/flows/{flow_id}/simulate
  PATCH  /api/v1/whatsapp/flows/{flow_id}

Auth (doc 09 §6.7):
  GET, PUT /draft  → require_permission("EMPLOYEE", "READ")
  POST (create), validate, publish, simulate, PATCH  → require_admin()
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import utils as backend_utils
from backend.security.rbac import require_admin, require_permission
from backend.whatsapp.flow_validation import validate_flow
from backend.whatsapp.flow_engine import simulate_flow

logger = logging.getLogger(__name__)

flows_router = APIRouter(prefix="/flows", tags=["whatsapp-flows"])

_SCHEMA = backend_utils.DB_SCHEMA
_VALID_TRIGGER_TYPES = frozenset({"inbound_keyword", "scheduled_date", "crm_event"})


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class FlowListItem(BaseModel):
    id: UUID
    name: str
    trigger_type: str
    status: str
    is_active: bool
    version: int
    updated_at: str


class FlowDetail(BaseModel):
    id: UUID
    name: str
    trigger_type: str
    status: str
    is_active: bool
    draft_data: dict
    live_data: Optional[dict]
    version: int
    created_by: Optional[int]
    created_at: str
    updated_at: str


class FlowCreate(BaseModel):
    name: str = Field(..., min_length=1)
    trigger_type: str


class DraftUpdate(BaseModel):
    draft_data: dict


class IsActiveUpdate(BaseModel):
    is_active: bool


class ValidationResponse(BaseModel):
    issues: list[dict]


class PublishResponse(BaseModel):
    version: int


class OkResponse(BaseModel):
    ok: bool = True


class SimulateRequest(BaseModel):
    customer_id: Optional[int] = None
    context_overrides: dict = Field(default_factory=dict)
    simulated_replies: list = Field(default_factory=list)


class SimulateResponse(BaseModel):
    trace: list[dict]
    would_send: list[dict]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_jsonb(val: Any) -> Any:
    """asyncpg returns JSONB columns as str; parse to Python object."""
    if val is None:
        return None
    if isinstance(val, str):
        return json.loads(val)
    return val


def _row_to_list_item(row: Any) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "trigger_type": row["trigger_type"],
        "status": row["status"],
        "is_active": row["is_active"],
        "version": row["version"],
        "updated_at": row["updated_at"].isoformat(),
    }


def _row_to_detail(row: Any) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "trigger_type": row["trigger_type"],
        "status": row["status"],
        "is_active": row["is_active"],
        "draft_data": _parse_jsonb(row["draft_data"]) or {},
        "live_data": _parse_jsonb(row["live_data"]),
        "version": row["version"],
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@flows_router.get("", response_model=list[FlowListItem])
async def list_flows(
    current_user: dict = Depends(require_permission("EMPLOYEE", "READ")),
) -> list[dict]:
    pool = await backend_utils.get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id, name, trigger_type, status, is_active, version, updated_at"
            f" FROM {_SCHEMA}.wa_flows ORDER BY updated_at DESC"
        )
    return [_row_to_list_item(r) for r in rows]


@flows_router.post("", response_model=FlowDetail, status_code=201)
async def create_flow(
    payload: FlowCreate,
    current_user: dict = Depends(require_admin()),
) -> dict:
    if payload.trigger_type not in _VALID_TRIGGER_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"trigger_type must be one of {sorted(_VALID_TRIGGER_TYPES)}",
        )
    try:
        emp_id: Optional[int] = int(current_user.get("sub") or 0) or None
    except (TypeError, ValueError):
        emp_id = None

    pool = await backend_utils.get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"INSERT INTO {_SCHEMA}.wa_flows (name, trigger_type, created_by)"
            f" VALUES ($1, $2, $3)"
            f" RETURNING id, name, trigger_type, status, is_active,"
            f"           draft_data, live_data, version, created_by,"
            f"           created_at, updated_at",
            payload.name, payload.trigger_type, emp_id,
        )
    return _row_to_detail(row)


@flows_router.get("/{flow_id}", response_model=FlowDetail)
async def get_flow(
    flow_id: UUID,
    current_user: dict = Depends(require_permission("EMPLOYEE", "READ")),
) -> dict:
    pool = await backend_utils.get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT id, name, trigger_type, status, is_active,"
            f"       draft_data, live_data, version, created_by,"
            f"       created_at, updated_at"
            f" FROM {_SCHEMA}.wa_flows WHERE id = $1",
            flow_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    return _row_to_detail(row)


@flows_router.put("/{flow_id}/draft", response_model=OkResponse)
async def update_draft(
    flow_id: UUID,
    payload: DraftUpdate,
    current_user: dict = Depends(require_permission("EMPLOYEE", "READ")),
) -> OkResponse:
    pool = await backend_utils.get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"UPDATE {_SCHEMA}.wa_flows"
            f" SET draft_data = $1::jsonb, updated_at = now()"
            f" WHERE id = $2",
            json.dumps(payload.draft_data), flow_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Flow not found")
    return OkResponse()


@flows_router.post("/{flow_id}/validate", response_model=ValidationResponse)
async def validate_flow_endpoint(
    flow_id: UUID,
    current_user: dict = Depends(require_admin()),
) -> ValidationResponse:
    pool = await backend_utils.get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT draft_data FROM {_SCHEMA}.wa_flows WHERE id = $1",
            flow_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    draft = _parse_jsonb(row["draft_data"]) or {}
    return ValidationResponse(issues=validate_flow(draft))


@flows_router.post("/{flow_id}/publish", response_model=PublishResponse)
async def publish_flow(
    flow_id: UUID,
    current_user: dict = Depends(require_admin()),
) -> PublishResponse:
    pool = await backend_utils.get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"SELECT draft_data, version FROM {_SCHEMA}.wa_flows"
                f" WHERE id = $1 FOR UPDATE",
                flow_id,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="Flow not found")

            draft = _parse_jsonb(row["draft_data"]) or {}
            issues = validate_flow(draft)
            if issues:
                raise HTTPException(status_code=422, detail={"issues": issues})

            new_version: int = row["version"] + 1
            await conn.execute(
                f"UPDATE {_SCHEMA}.wa_flows"
                f" SET live_data = draft_data,"
                f"     status = 'published',"
                f"     version = $1,"
                f"     updated_at = now()"
                f" WHERE id = $2",
                new_version, flow_id,
            )
    return PublishResponse(version=new_version)


@flows_router.post("/{flow_id}/simulate", response_model=SimulateResponse)
async def simulate_flow_endpoint(
    flow_id: UUID,
    payload: SimulateRequest,
    current_user: dict = Depends(require_admin()),
) -> SimulateResponse:
    """Dry-run the published flow in-memory; no DB rows are persisted (doc 09 §3.8).

    Loads live_data (404 if unpublished), builds a synthetic context from
    defaults + context_overrides, executes handlers with no DB writes,
    fast-forwards Wait(delay), and returns the execution trace + would_send list.
    """
    pool = await backend_utils.get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT live_data FROM {_SCHEMA}.wa_flows WHERE id = $1",
            flow_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    live_data = _parse_jsonb(row["live_data"])
    if live_data is None:
        raise HTTPException(
            status_code=404,
            detail="Flow has not been published yet; live_data is NULL",
        )

    # Build initial context: defaults for all 12 tokens + caller overrides
    context: dict = {
        "customer_name": "Simulated Customer",
        "gst_number": "29AABCT1332L000",
        "gstr3b_due_date": "2026-08-20",
        "gstr1_due_date": "2026-08-11",
        "payment_amount_due": "5000",
        "payment_due_date": "2026-08-15",
        "rm_name": "RM Staff",
        "op_name": "OP Staff",
        "filing_status": "NOT_FILED",
        "pipeline_stage": "ACTIVE",
        "income_tax_year": "AY2025-26",
        "pending_documents_count": "2",
        "phone": "9000000000",
        "__flow_def": live_data,
    }
    context.update(payload.context_overrides)

    result = await simulate_flow(
        live_data=live_data,
        initial_context=context,
        simulated_replies=payload.simulated_replies,
    )
    return SimulateResponse(
        trace=result.get("trace", []),
        would_send=result.get("would_send", []),
    )


@flows_router.patch("/{flow_id}", response_model=OkResponse)
async def toggle_flow_active(
    flow_id: UUID,
    payload: IsActiveUpdate,
    current_user: dict = Depends(require_admin()),
) -> OkResponse:
    pool = await backend_utils.get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"UPDATE {_SCHEMA}.wa_flows"
            f" SET is_active = $1, updated_at = now()"
            f" WHERE id = $2",
            payload.is_active, flow_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Flow not found")
    return OkResponse()
