"""Staff APIs for `service_config` (dropdown / catalog reads)."""

import logging
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.customer_service.schemas import ServiceConfigDropdownResponse, ServiceConfigDropdownRow
from app.logger import logger
from app.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
from app.security.rbac import require_permission
from app.utils import DB_SCHEMA, generate_uuid, get_db_pool

router = APIRouter(
    prefix="/api/v1/customer-service",
    tags=["Service config"],
)


def _service_config_dropdown_cache_key(
    service_category_cleaned: Optional[str],
    role: Optional[str],
    emp_id: Optional[int],
) -> str:
    return build_cache_key(
        "service_config:get_services",
        service_category=service_category_cleaned,
        role=(role or "").strip().upper() or None,
        emp_id=emp_id,
    )


@router.get(
    "/service-config/services",
    response_model=ServiceConfigDropdownResponse,
    summary="service_config rows for staff dropdown (was /api/v1/services-config/services)",
)
async def get_service_config_dropdown(
    service_category: Optional[str] = None,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id if emp_id is not None else "-"},
    )

    service_category_cleaned = (
        service_category.strip().upper()
        if service_category and service_category.strip()
        else None
    )

    log.info("Fetching services dropdown | category=%s", service_category_cleaned)
    cache_key = _service_config_dropdown_cache_key(service_category_cleaned, role, emp_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    try:

        async def _load_services_dropdown():
            conditions = ["is_active = TRUE"]
            values = []
            param_index = 1

            if service_category_cleaned:
                conditions.append(f"service_category = ${param_index}")
                values.append(service_category_cleaned)
                param_index += 1

            where_clause = f"WHERE {' AND '.join(conditions)}"

            sql = f"""
                SELECT
                    id,
                    service_category,
                    service_code,
                    service_name,
                    description
                FROM {DB_SCHEMA}.service_config
                {where_clause}
                ORDER BY service_category, service_name
            """

            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *values)

            log.info("Services fetched successfully | count=%s", len(rows))

            data = [ServiceConfigDropdownRow(**dict(row)) for row in rows]

            return ServiceConfigDropdownResponse(
                data=data,
                count=len(data),
                request_id=request_id,
            ).model_dump()

        return await redis_get_or_set_json(
            cache_key,
            loader=_load_services_dropdown,
            ttl_seconds=300,
            tags=["service_config:get_services:index"],
        )

    except asyncpg.PostgresError as e:
        log.error(
            "Database error while fetching services | error=%s",
            str(e),
            exc_info=True,
        )

        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error while fetching services")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
