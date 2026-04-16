from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
import logging
import asyncpg
from app.gst_registration.schemas import GSTConfigOut
from app.security.rbac import require_permission
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/gst-registration",
    tags=["GST Registration Config"]
)


@router.get(
    "/config/{config_type}",
    response_model=List[GSTConfigOut],
    summary="Get GST Registration Config by Type",
)
async def get_gst_registration_config_by_type(
    config_type: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    normalized_type = config_type.strip().replace("-", "_").upper()

    log.info("Fetching config for type=%s", normalized_type)
    cache_key = build_cache_key(
        "gst_registration_config:get_by_type",
        config_type=normalized_type,
        emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Unexpected error while fetching config type=%s", normalized_type)
        raise HTTPException(status_code=500, detail="Internal server error.")

    async def _load_gst_registration_config_by_type():
        try:
            sql = f"""
                SELECT value, display_name, sort_order
                FROM {DB_SCHEMA}.gst_registration_config
                WHERE upper(config_type) = $1
                  AND is_active = TRUE
                ORDER BY sort_order
            """

            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, normalized_type)

            log.info("Config fetched successfully type=%s count=%s", normalized_type, len(rows))
            return [dict(row) for row in rows]

        except asyncpg.PostgresError:
            log.exception("Database error while fetching config type=%s", normalized_type)
            raise HTTPException(status_code=500, detail="Database error.")

        except Exception:
            log.exception("Unexpected error while fetching config type=%s", normalized_type)
            raise HTTPException(status_code=500, detail="Internal server error.")

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_gst_registration_config_by_type,
        ttl_seconds=300,
        tags=["gst_registration_config:get_by_type:index"],
    )