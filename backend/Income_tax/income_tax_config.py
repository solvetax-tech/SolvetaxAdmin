from typing import List

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.logger import logger
from backend.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
from backend.security.rbac import require_permission
from backend.utils import DB_SCHEMA, generate_uuid, get_db_pool

router = APIRouter(
    prefix="/api/v1/income-tax",
    tags=["Income Tax Config"],
)


class IncomeTaxConfigOut(BaseModel):
    value: str
    display_name: str
    sort_order: int


@router.get(
    "/config/{config_type}",
    response_model=List[IncomeTaxConfigOut],
    summary="Get Income Tax Config by Type",
)
async def get_income_tax_config_by_type(
    config_type: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    normalized_type = config_type.strip().replace("-", "_").upper()

    log = logger.getChild("income_tax_config")
    cache_key = build_cache_key(
        "income_tax_config:get_by_type",
        config_type=normalized_type,
        emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB pool error | request_id=%s type=%s", request_id, normalized_type)
        raise HTTPException(status_code=500, detail="Internal server error.")

    async def _loader():
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT value, display_name, sort_order
                    FROM {DB_SCHEMA}.income_tax_config
                    WHERE upper(config_type) = $1
                      AND is_active = TRUE
                    ORDER BY sort_order, id
                    """,
                    normalized_type,
                )
            return [dict(r) for r in rows]
        except asyncpg.PostgresError:
            log.exception("DB error | request_id=%s type=%s", request_id, normalized_type)
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key=cache_key,
        loader=_loader,
        ttl_seconds=300,
        tags=["income_tax_config:get_by_type:index"],
    )
