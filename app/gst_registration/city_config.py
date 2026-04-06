from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
import logging
import asyncpg
from app.security.rbac import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/city-config",
    tags=["City Config"]
)


# ================= RESPONSE =================
class CityConfigOut(BaseModel):
    city_code: str
    city_name: str
    district: Optional[str]
    category: Optional[str]
    sort_order: int


# ================= GET API =================
@router.get(
    "",
    response_model=List[CityConfigOut],
    summary="Get City Dropdown (by state)",
)
async def get_cities(
    state_code: str = Query(..., description="State code (e.g., ANDHRA_PRADESH)"),
    search: Optional[str] = Query(None),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    normalized_state = state_code.strip().replace("-", "_").upper()

    log.info("Fetching cities state=%s search=%s", normalized_state, search)

    try:
        pool = await get_db_pool()

        sql = f"""
            SELECT city_code, city_name, district, category, sort_order
            FROM {DB_SCHEMA}.city_config
            WHERE upper(state_code) = $1
              AND is_active = TRUE
        """

        params = [normalized_state]

        if search:
            sql += " AND city_name ILIKE $2"
            params.append(f"%{search}%")

        sql += " ORDER BY sort_order, city_name"

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        log.info("Fetched %s cities for state=%s", len(rows), normalized_state)

        return [dict(row) for row in rows]

    except asyncpg.PostgresError:
        log.exception("Database error state=%s", normalized_state)
        raise HTTPException(500, "Database error")

    except Exception:
        log.exception("Unexpected error state=%s", normalized_state)
        raise HTTPException(500, "Internal server error")