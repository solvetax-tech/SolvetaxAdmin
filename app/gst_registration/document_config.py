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
    summary="Get Required Documents for GST Registration",
    responses={
        200: {"description": "Document list fetched successfully"},
        404: {"description": "GST registration not found"},
        500: {"description": "Database error"}
    }
)
async def get_required_documents(
    gst_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "get_required_documents"
        }
    )

    log.info("Fetching required documents | gst_id=%s", gst_id)

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

            # --------------------------------------------------
            # 1️⃣ Fetch ownership category from GST
            # --------------------------------------------------
            gst_row = await conn.fetchrow(
                f"""
                SELECT ownership_category
                FROM {DB_SCHEMA}.gst_registration
                WHERE id = $1
                AND is_active = TRUE
                """,
                gst_id,
            )

            if not gst_row:
                raise HTTPException(
                    status_code=404,
                    detail="GST registration not found."
                )

            ownership_category = gst_row["ownership_category"]

            # --------------------------------------------------
            # 2️⃣ Fetch document configuration
            # --------------------------------------------------
            documents = await conn.fetch(
                f"""
                SELECT
                    value,
                    display_name,
                    description,
                    is_mandatory
                FROM {DB_SCHEMA}.document_config
                WHERE entity_type = 'GST_REGISTRATION'
                AND ownership_category = $1
                AND is_active = TRUE
                ORDER BY sort_order
                """,
                ownership_category,
            )

            log.info(
                "Document configuration fetched | ownership_category=%s | count=%s",
                ownership_category,
                len(documents),
            )

            return {
                "ownership_category": ownership_category,
                "documents": [dict(d) for d in documents],
                "request_id": request_id
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