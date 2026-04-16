from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
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
    search_norm = search.strip() if isinstance(search, str) else None

    log.info("Fetching cities state=%s search=%s", normalized_state, search_norm)
    cache_key = build_cache_key(
        "city_config:get_cities",
        state_code=normalized_state,
        search=search_norm or None,
        emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Unexpected error state=%s", normalized_state)
        raise HTTPException(500, "Internal server error")

    async def _load_cities():
        try:
            sql = f"""
                SELECT city_code, city_name, district, category, sort_order
                FROM {DB_SCHEMA}.city_config
                WHERE upper(state_code) = $1
                  AND is_active = TRUE
            """

            params = [normalized_state]

            if search_norm:
                sql += " AND city_name ILIKE $2"
                params.append(f"%{search_norm}%")

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

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_cities,
        ttl_seconds=300,
        tags=["city_config:get_cities:index"],
    )