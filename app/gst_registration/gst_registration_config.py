from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
import logging
from app.gst_registration.schemas import GSTConfigOut
from app.security.rbac import require_permission
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/gst-registration",
    tags=["GST Registration Config"]
)


@router.get(
    "/config/registration-type",
    response_model=List[GSTConfigOut],
    summary="Get Registration Type Config",
)
async def get_registration_type_config(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Fetching registration_type config")

    try:
        pool = await get_db_pool()

        sql = f"""
            SELECT value, display_name, sort_order
            FROM {DB_SCHEMA}.gst_registration_config
            WHERE upper(config_type) = 'REGISTRATION_TYPE'
              AND is_active = TRUE
            ORDER BY sort_order
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        log.info("registration_type config fetched count=%s", len(rows))

        return [dict(row) for row in rows]

    except asyncpg.PostgresError:
        log.exception("Database error while fetching registration_type config")
        raise HTTPException(status_code=500, detail="Database error.")

    except Exception:
        log.exception("Unexpected error while fetching registration_type config")
        raise HTTPException(status_code=500, detail="Internal server error.")


@router.get(
    "/config/ownership-category",
    response_model=List[GSTConfigOut],
    summary="Get Ownership Category Config",
)
async def get_ownership_category_config(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Fetching ownership_category config")

    try:
        pool = await get_db_pool()

        sql = f"""
            SELECT value, display_name, sort_order
            FROM {DB_SCHEMA}.gst_registration_config
            WHERE upper(config_type) = 'OWNERSHIP_CATEGORY'
              AND is_active = TRUE
            ORDER BY sort_order
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        log.info("ownership_category config fetched count=%s", len(rows))

        return [dict(row) for row in rows]

    except asyncpg.PostgresError:
        log.exception("Database error while fetching ownership_category config")
        raise HTTPException(status_code=500, detail="Database error.")

    except Exception:
        log.exception("Unexpected error while fetching ownership_category config")
        raise HTTPException(status_code=500, detail="Internal server error.")

@router.get(
    "/config/turnover-details",
    response_model=List[GSTConfigOut],
    summary="Get Turnover Details Config",
)
async def get_turnover_details_config(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Fetching turnover_details config")

    try:
        pool = await get_db_pool()

        sql = f"""
            SELECT value, display_name, sort_order
            FROM {DB_SCHEMA}.gst_registration_config
            WHERE upper(config_type) = 'TURNOVER_DETAILS'
              AND is_active = TRUE
            ORDER BY sort_order
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        log.info("turnover_details config fetched count=%s", len(rows))

        return [dict(row) for row in rows]

    except asyncpg.PostgresError:
        log.exception("Database error while fetching turnover_details config")
        raise HTTPException(status_code=500, detail="Database error.")

    except Exception:
        log.exception("Unexpected error while fetching turnover_details config")
        raise HTTPException(status_code=500, detail="Internal server error.")


@router.get(
    "/config/turnover-details",
    response_model=List[GSTConfigOut],
    summary="Get Turnover Details Config",
)
async def get_turnover_details_config(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Fetching turnover_details config")

    try:
        pool = await get_db_pool()

        sql = f"""
            SELECT value, display_name, sort_order
            FROM {DB_SCHEMA}.gst_registration_config
            WHERE upper(config_type) = 'TURNOVER_DETAILS'
              AND is_active = TRUE
            ORDER BY sort_order
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        log.info("turnover_details config fetched count=%s", len(rows))

        return [dict(row) for row in rows]

    except asyncpg.PostgresError:
        log.exception("Database error while fetching turnover_details config")
        raise HTTPException(status_code=500, detail="Database error.")

    except Exception:
        log.exception("Unexpected error while fetching turnover_details config")
        raise HTTPException(status_code=500, detail="Internal server error.")


@router.get(
    "/config/registration-status",
    response_model=List[GSTConfigOut],
    summary="Get Registration Status Config",
)
async def get_registration_status_config(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Fetching registration_status config")

    try:
        pool = await get_db_pool()

        sql = f"""
            SELECT value, display_name, sort_order
            FROM {DB_SCHEMA}.gst_registration_config
            WHERE upper(config_type) = 'REGISTRATION_STATUS'
              AND is_active = TRUE
            ORDER BY sort_order
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        log.info("registration_status config fetched count=%s", len(rows))

        return [dict(row) for row in rows]

    except asyncpg.PostgresError:
        log.exception("Database error while fetching registration_status config")
        raise HTTPException(status_code=500, detail="Database error.")

    except Exception:
        log.exception("Unexpected error while fetching registration_status config")
        raise HTTPException(status_code=500, detail="Internal server error.")

# -------------------------------------------------------------------
# GET STATE CONFIG (GST STATE CODE ORDER)
# -------------------------------------------------------------------
@router.get(
    "/config/state",
    response_model=List[GSTConfigOut],
    summary="Get State Config (GST State Code Order)",
    responses={
        200: {"description": "State config fetched successfully."},
        500: {"description": "Database or internal error."},
    },
)
async def get_state_config(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Fetching GST state config")

    # --------------------------------------------------
    # Database Pool Acquisition
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    # --------------------------------------------------
    # Query Execution
    # --------------------------------------------------
    try:
        sql = f"""
            SELECT value,
                   display_name,
                   sort_order
            FROM {DB_SCHEMA}.gst_registration_config
            WHERE upper(config_type) = 'STATE'
              AND is_active = TRUE
            ORDER BY sort_order ASC
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        log.info("GST state config fetched successfully count=%s", len(rows))

        return [dict(row) for row in rows]

    # --------------------------------------------------
    # Exception Handling (Production Coverage)
    # --------------------------------------------------
    except asyncpg.PostgresError:
        log.exception("Database error while fetching GST state config")
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception("Unexpected error while fetching GST state config")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )

@router.get(
    "/config/business-type",
    response_model=List[GSTConfigOut],
    summary="Get Business Type Config",
)
async def get_business_type_config(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Fetching business_type config")

    try:
        pool = await get_db_pool()

        sql = f"""
            SELECT value, display_name, sort_order
            FROM {DB_SCHEMA}.gst_registration_config
            WHERE upper(config_type) = 'BUSINESS_TYPE'
              AND is_active = TRUE
            ORDER BY sort_order
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        log.info("business_type config fetched count=%s", len(rows))

        return [dict(row) for row in rows]

    except asyncpg.PostgresError:
        log.exception("Database error while fetching business_type config")
        raise HTTPException(status_code=500, detail="Database error.")

    except Exception:
        log.exception("Unexpected error while fetching business_type config")
        raise HTTPException(status_code=500, detail="Internal server error.")