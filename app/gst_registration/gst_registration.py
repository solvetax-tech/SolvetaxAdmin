import logging
import uuid
import asyncpg
from fastapi import Request
from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import BaseModel
from typing import Optional, List
import uuid
from datetime import datetime
from app.gst_registration.schemas import GSTRegistrationIn, GSTRegistrationOut, GSTRegistrationEditIn
from app.utils import get_db_pool, DB_SCHEMA
from app.security.rbac import require_permission
from app.logger import logger

router = APIRouter(
    prefix="/api/v1/gst-registrations",
    tags=["GST Registration"]
)

# -------------------------------------------------------------------
# CREATE GST REGISTRATION (PRODUCTION SAFE - CLEAN VERSION)
# -------------------------------------------------------------------

@router.post(
    "",
    response_model=GSTRegistrationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create GST Registration",
)
async def create_gst_registration(
    payload: GSTRegistrationIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    # ------------------ Mask Sensitive Fields ------------------

    mask = lambda v, s=2, e=2: (
        "" if not v else (v[:s] + "*" * max(len(v) - s - e, 0) + v[-e:] if len(v) > s + e else "*" * len(v))
    )

    log.info(
        "GST registration request customer_id=%s username=%s mobile=%s email=%s "
        "secondary_email=%s gstin=%s pan=%s password=%s",
        payload.customer_id,
        payload.username,
        mask(payload.mobile),
        mask(payload.email),
        mask(payload.secondary_email),
        mask(payload.gstin),
        mask(payload.pan, 2, 1),
        "*" * len(payload.password) if payload.password else "",
    )

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        try:
            # ------------------ Validate Customer ------------------

            if not await conn.fetchrow(
                f"""SELECT 1 FROM {DB_SCHEMA}.customers
                    WHERE customer_id=$1 AND mobile=$2 AND is_active=TRUE LIMIT 1""",
                payload.customer_id,
                payload.mobile,
            ):
                log.warning("Customer not found for GST registration")
                raise HTTPException(400, "Customer not found with given customer_id and mobile.")

            # ------------------ GSTIN Uniqueness ------------------

            if payload.gstin and await conn.fetchrow(
                f"""SELECT 1 FROM {DB_SCHEMA}.gst_registration
                    WHERE gstin=$1 AND customer_id<>$2 LIMIT 1""",
                payload.gstin,
                payload.customer_id,
            ):
                log.warning("GSTIN already exists for another customer")
                raise HTTPException(409, "GST number already exists for another customer.")

            # ------------------ Insert GST ------------------

            insert_sql = f"""
                INSERT INTO {DB_SCHEMA}.gst_registration (
                    customer_id, username, password, pan, registration_type,
                    ownership_category, business_type, state, turnover_details,
                    created_by, rm_id, gstin, registration_status,
                    is_filing_needed, mobile, is_active, email,
                    secondary_email, created_at, updated_at
                )
                VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,
                    'DRAFT',$13,$14,$15,$16,$17,NOW(),NOW()
                )
                RETURNING *
            """

            async with conn.transaction():
                row = await conn.fetchrow(
                    insert_sql,
                    payload.customer_id,
                    payload.username.strip(),
                    payload.password,  # plain as requested
                    payload.pan,
                    payload.registration_type,
                    payload.ownership_category,
                    payload.business_type,
                    payload.state,
                    payload.turnover_details,
                    payload.created_by or emp_id,
                    payload.rm_id,
                    payload.gstin,
                    payload.is_filing_needed,
                    payload.mobile,
                    payload.is_active,
                    payload.email,
                    payload.secondary_email,
                )

            if not row:
                log.error("GST registration insert returned empty row")
                raise HTTPException(500, "GST registration creation failed.")

            log.info("GST registration created id=%s customer_id=%s", row["id"], row["customer_id"])

            return GSTRegistrationOut.model_validate(row).model_copy(
                update={"message": "GST registration created successfully."}
            )

        # ------------------ DB Validations ------------------

        except asyncpg.exceptions.UniqueViolationError as e:
            c = getattr(e, "constraint_name", "")
            detail = (
                "Username already exists." if "username" in c else
                "GST number already exists." if "gstin" in c else
                "Duplicate GST registration."
            )
            log.warning("Unique violation: %s", detail)
            raise HTTPException(409, detail)

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Invalid foreign key reference")
            raise HTTPException(400, "Invalid customer_id or rm_id reference.")

        except asyncpg.PostgresError:
            log.exception("Database error during GST registration")
            raise HTTPException(500, "Database error.")

        except Exception:
            log.exception("Unexpected error during GST registration")
            raise HTTPException(500, "Internal server error.")
# -------------------------------------------------------------------
# LIST GST REGISTRATIONS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------

@router.get(
    "/dynamic_filter",
    response_model=List[GSTRegistrationOut],
    summary="List GST Registrations",
)
async def list_gst_registrations(
    customer_id: Optional[int] = None,
    gstin: Optional[str] = None,
    mobile: Optional[str] = None,
    email: Optional[str] = None,
    secondary_email: Optional[str] = None,
    rm_id: Optional[int] = None,
    business_type: Optional[str] = None,
    registration_status: Optional[str] = None,
    is_active: Optional[bool] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming GST list request limit=%s offset=%s", limit, offset)

    if from_date and to_date and from_date > to_date:
        raise HTTPException(400, "from_date cannot be greater than to_date.")

    pool = await get_db_pool()

    conditions = []
    values = []
    param_index = 1

    filters = {
        "customer_id": customer_id,
        "gstin": gstin,
        "mobile": mobile,
        "email": email,
        "secondary_email": secondary_email,
        "rm_id": rm_id,
        "business_type": business_type,
        "registration_status": registration_status,
        "is_active": is_active,
    }

    for field, value in filters.items():
        if value is not None:
            conditions.append(f"{field} = ${param_index}")
            values.append(value)
            param_index += 1

    if from_date:
        conditions.append(f"created_at >= ${param_index}")
        values.append(from_date)
        param_index += 1

    if to_date:
        conditions.append(f"created_at <= ${param_index}")
        values.append(to_date)
        param_index += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.gst_registration
          {where_clause}
         ORDER BY created_at DESC
         LIMIT ${param_index} OFFSET ${param_index + 1}
    """

    values.extend([limit, offset])

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info("GST registrations listed count=%s", len(rows))

        return [
            GSTRegistrationOut.model_validate(row).model_copy(
                update={"message": "GST registrations listed successfully."}
            )
            for row in rows
        ]

    except asyncpg.PostgresError:
        log.exception("Database error during GST listing")
        raise HTTPException(500, "Database error.")

    except Exception:
        log.exception("Unexpected error during GST listing")
        raise HTTPException(500, "Internal server error.")

# -------------------------------------------------------------------
# GET GST REGISTRATION BY GSTIN
# -------------------------------------------------------------------

@router.get(
    "/{gstin}/single_filter",
    response_model=GSTRegistrationOut,
    summary="Get GST Registration",
)
async def get_gst_registration(
    gstin: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Fetching GST registration gstin=%s", gstin)

    pool = await get_db_pool()

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT *
                  FROM {DB_SCHEMA}.gst_registration
                 WHERE gstin = $1
                 LIMIT 1
                """,
                gstin,
            )

        if not row:
            log.warning("GST registration not found gstin=%s", gstin)
            raise HTTPException(404, "GST registration not found.")

        log.info("GST registration fetched gstin=%s", gstin)

        return GSTRegistrationOut.model_validate(row).model_copy(
            update={"message": "GST registration fetched successfully."}
        )

    except asyncpg.PostgresError:
        log.exception("Database error during GST fetch")
        raise HTTPException(500, "Database error.")

    except Exception:
        log.exception("Unexpected error during GST fetch")
        raise HTTPException(500, "Internal server error.")

# -------------------------------------------------------------------
# EDIT GST REGISTRATION (DYNAMIC UPDATE)
# -------------------------------------------------------------------

@router.post(
    "/{gstin}/edit",
    response_model=GSTRegistrationOut,
    summary="Edit GST Registration",
)
async def edit_gst_registration(
    gstin: str,
    payload: GSTRegistrationEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming GST update request gstin=%s", gstin)

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        log.warning("No fields provided for update")
        raise HTTPException(400, "At least one field must be provided for update.")

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        try:
            fields = []
            values = []

            for index, (key, value) in enumerate(update_data.items(), start=1):
                fields.append(f"{key} = ${index}")
                values.append(value)

            fields.append("updated_at = NOW()")

            sql = f"""
                UPDATE {DB_SCHEMA}.gst_registration
                SET {', '.join(fields)}
                WHERE gstin = ${len(values) + 1}
                RETURNING *
            """

            values.append(gstin)

            async with conn.transaction():
                row = await conn.fetchrow(sql, *values)

            if not row:
                log.warning("GST registration not found for update")
                raise HTTPException(404, "GST registration not found.")

            log.info("GST registration updated successfully gstin=%s", gstin)

            return GSTRegistrationOut.model_validate(row).model_copy(
                update={"message": "GST registration updated successfully."}
            )

        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Duplicate field value violates unique constraint")
            raise HTTPException(409, "Duplicate field value violates unique constraint.")

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Invalid foreign key reference")
            raise HTTPException(400, "Invalid foreign key reference.")

        except asyncpg.PostgresError:
            log.exception("Database error during GST update")
            raise HTTPException(500, "Database error.")

        except Exception:
            log.exception("Unexpected error during GST update")
            raise HTTPException(500, "Internal server error.")
