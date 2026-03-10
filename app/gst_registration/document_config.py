import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.payments.schemas import RegistrationPaymentIn, RegistrationPaymentEditIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.logger import logger
from datetime import datetime
from zoneinfo import ZoneInfo
import json

router = APIRouter(
    prefix="/api/v1/document-config",
    tags=["Document Config"]
)
@router.get(
    "/gst-registration/{gst_id}/required-documents",
    summary="Get Required Documents for GST Registration Person",
)
async def get_required_documents(
    gst_id: int,
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id}
    )

    log.info(
        "Fetching required documents | gst_id=%s person_id=%s",
        gst_id,
        person_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error."
        )

    async with pool.acquire() as conn:
        try:

            documents = await conn.fetch(
                f"""
                SELECT
                    dc.value,
                    dc.display_name,
                    dc.description,
                    dc.is_mandatory
                FROM {DB_SCHEMA}.gst_registration g
                JOIN {DB_SCHEMA}.gst_registration_persons p
                    ON p.gst_registration_id = g.id
                JOIN {DB_SCHEMA}.document_config dc
                    ON dc.ownership_category = g.ownership_category
                    AND dc.registration = 'GST_REGISTRATION'
                    AND dc.is_active = TRUE
                WHERE g.id = $1
                AND p.person_id = $2
                AND g.is_active = TRUE
                AND p.is_active = TRUE
                AND NOT EXISTS (
                    SELECT 1
                    FROM {DB_SCHEMA}.gst_registration_documents gd
                    WHERE gd.document_type = dc.value
                    AND gd.is_active = TRUE
                    AND (
                        gd.gstin = g.gstin
                        OR gd.person_id = p.person_id
                    )
                )
                ORDER BY dc.sort_order
                """,
                gst_id,
                person_id,
            )

            log.info(
                "Documents fetched successfully | count=%s",
                len(documents),
            )

            return {
                "gst_id": gst_id,
                "person_id": person_id,
                "documents": [dict(d) for d in documents],
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            log.exception("Database error while fetching documents")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred."
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error while fetching documents")
            raise HTTPException(
                status_code=500,
                detail="Internal server error."
            )
@router.get(
    "/document-config",
    summary="Filter Document Configurations",
    responses={
        200: {"description": "Document configs fetched successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
)
async def list_document_configs(
    id: Optional[int] = None,
    entity_type: Optional[str] = None,
    ownership_category: Optional[str] = None,
    config_type: Optional[str] = None,
    value: Optional[str] = None,
    is_mandatory: Optional[bool] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info(
        "Incoming document config filter | limit=%s offset=%s",
        limit,
        offset,
    )

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    try:

        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Exact Filters
        # --------------------------------------------------

        if id is not None:
            conditions.append(f"id = ${param_index}")
            values.append(id)
            param_index += 1

        if entity_type and entity_type.strip():
            conditions.append(f"upper(entity_type) = ${param_index}")
            values.append(entity_type.strip().upper())
            param_index += 1

        if ownership_category and ownership_category.strip():
            conditions.append(f"upper(ownership_category) = ${param_index}")
            values.append(ownership_category.strip().upper())
            param_index += 1

        if config_type and config_type.strip():
            conditions.append(f"upper(config_type) = ${param_index}")
            values.append(config_type.strip().upper())
            param_index += 1

        if value and value.strip():
            conditions.append(f"upper(value) = ${param_index}")
            values.append(value.strip().upper())
            param_index += 1

        if is_mandatory is not None:
            conditions.append(f"is_mandatory = ${param_index}")
            values.append(is_mandatory)
            param_index += 1

        # --------------------------------------------------
        # Active Filtering Pattern
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # WHERE CLAUSE
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.document_config
            {where_clause}
        """

        data_sql = f"""
            SELECT *
            FROM {DB_SCHEMA}.document_config
            {where_clause}
            ORDER BY entity_type, ownership_category, sort_order, id
            LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:

            total = await conn.fetchval(count_sql, *values)

            rows = await conn.fetch(data_sql, *values_with_pagination)

        log.info(
            "Document configs fetched successfully | returned=%s total=%s",
            len(rows),
            total,
        )

        return {
            "data": [dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "request_id": request_id,
        }

    except asyncpg.PostgresError:
        log.exception("Database error during document config filtering")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error during document config filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )