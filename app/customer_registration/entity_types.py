from typing import Optional
import logging
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.security.rbac import require_permission
from app.utils import DB_SCHEMA, generate_uuid, get_db_pool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/entity-types",
    tags=["Entity Types"],
)


@router.get(
    "",
    summary="Get entity types",
)
async def list_entity_types(
    is_active: Optional[bool] = Query(True, description="Filter by active status."),
    search: Optional[str] = Query(None, description="Search in entity_name/value."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "list_entity_types"},
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    params = []
    where = []
    idx = 1

    if is_active is not None:
        where.append(f"e.is_active = ${idx}")
        params.append(is_active)
        idx += 1

    if search and search.strip():
        token = f"%{search.strip()}%"
        where.append(f"(e.entity_name ILIKE ${idx} OR e.value ILIKE ${idx})")
        params.append(token)
        idx += 1

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    count_sql = f"""
        SELECT COUNT(*)::bigint
        FROM {DB_SCHEMA}.entity_types e
        {where_sql}
    """
    list_sql = f"""
        SELECT e.id, e.entity_name, e.value, e.is_active, e.created_at, e.updated_at
        FROM {DB_SCHEMA}.entity_types e
        {where_sql}
        ORDER BY e.id
        LIMIT ${idx} OFFSET ${idx + 1}
    """

    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval(count_sql, *params)
            rows = await conn.fetch(list_sql, *params, limit, offset)
    except asyncpg.PostgresError:
        log.exception("Database error while fetching entity types")
        raise HTTPException(status_code=500, detail="Database error.")
    except Exception:
        log.exception("Unexpected error while fetching entity types")
        raise HTTPException(status_code=500, detail="Internal server error.")

    return {
        "items": [dict(r) for r in rows],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "request_id": request_id,
    }
