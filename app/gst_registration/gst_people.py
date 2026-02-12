import uuid
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from app.security.rbac import require_permission
from app.gst_registration.schemas import (
    RegistrationPersonIn,
    RegistrationPersonEditIn,
    RegistrationPersonOut
)
from app.utils import get_db_pool, DB_SCHEMA
from app.logger import logger
import logging


router = APIRouter(
    prefix="/api/v1/gst-people",
    tags=["GST Registration People"]
)

# -------------------------------------------------------------------
# CREATE REGISTRATION PERSON
# -------------------------------------------------------------------

@router.post(
    "",
    response_model=RegistrationPersonOut,
    summary="Create Registration Person",
)
async def create_registration_person(
    payload: RegistrationPersonIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Creating registration person gstin=%s role=%s", payload.gstin, payload.role)

    pool = await get_db_pool()

    async with pool.acquire() as conn:
        try:
            # Validate GSTIN exists
            gst_exists = await conn.fetchval(
                f"SELECT 1 FROM {DB_SCHEMA}.gst_registration WHERE gstin=$1",
                payload.gstin,
            )
            if not gst_exists:
                raise HTTPException(status_code=400, detail="GSTIN not found.")

            # Validate Customer (if provided)
            if payload.customer_id:
                cust_exists = await conn.fetchval(
                    f"""
                    SELECT 1 FROM {DB_SCHEMA}.customers
                    WHERE customer_id=$1 AND is_active=TRUE
                    """,
                    payload.customer_id,
                )
                if not cust_exists:
                    raise HTTPException(status_code=400, detail="Customer not found.")

            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.registration_persons
                    (customer_id, gstin, full_name, role, pan, aadhaar,
                     email, mobile, is_primary_customer, created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW(),NOW())
                    RETURNING *
                    """,
                    payload.customer_id,
                    payload.gstin,
                    payload.full_name,
                    payload.role,
                    payload.pan,
                    payload.aadhaar,
                    payload.email,
                    payload.mobile,
                    payload.is_primary_customer,
                )

            response = RegistrationPersonOut.model_validate(row)

            log.info("Registration person created person_id=%s", row["person_id"])

            return response.model_copy(
                update={"message": "Registration person created successfully."}
            )

        except asyncpg.exceptions.UniqueViolationError:
            log.warning("Duplicate registration person data")
            raise HTTPException(
                status_code=409,
                detail="Duplicate registration person data.",
            )

        except asyncpg.PostgresError:
            log.exception("Database error during registration person create")
            raise HTTPException(status_code=500, detail="Database error.")

        except Exception:
            log.exception("Unexpected error during registration person create")
            raise HTTPException(status_code=500, detail="Internal server error.")


# -------------------------------------------------------------------
# LIST REGISTRATION PERSONS (DYNAMIC FILTER)
# -------------------------------------------------------------------

@router.get(
    "/dynamic_filter",
    response_model=List[RegistrationPersonOut],
    summary="List Registration Persons",
)
async def list_registration_persons(
    gstin: Optional[str] = None,
    customer_id: Optional[int] = None,
    mobile: Optional[str] = None,
    full_name: Optional[str] = None,
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

    log.info("Listing registration persons")

    pool = await get_db_pool()

    conditions = []
    values = []
    param_index = 1

    if gstin:
        conditions.append(f"gstin = ${param_index}")
        values.append(gstin)
        param_index += 1

    if customer_id:
        conditions.append(f"customer_id = ${param_index}")
        values.append(customer_id)
        param_index += 1

    if mobile:
        conditions.append(f"mobile = ${param_index}")
        values.append(mobile)
        param_index += 1

    if full_name:
        conditions.append(f"full_name ILIKE ${param_index}")
        values.append(f"%{full_name}%")
        param_index += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.registration_persons
          {where_clause}
         ORDER BY updated_at DESC
         LIMIT ${param_index} OFFSET ${param_index + 1}
    """

    values.extend([limit, offset])

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info("Registration persons listed count=%s", len(rows))

        return [
            RegistrationPersonOut.model_validate(row).model_copy(
                update={"message": "Registration persons listed successfully."}
            )
            for row in rows
        ]

    except asyncpg.PostgresError:
        log.exception("Database error during listing")
        raise HTTPException(status_code=500, detail="Database error.")

    except Exception:
        log.exception("Unexpected error during listing")
        raise HTTPException(status_code=500, detail="Internal server error.")


# -------------------------------------------------------------------
# EDIT REGISTRATION PERSON (DYNAMIC UPDATE)
# -------------------------------------------------------------------

@router.post(
    "/{person_id}/edit",
    response_model=RegistrationPersonOut,
    summary="Edit Registration Person",
)
async def edit_registration_person(
    person_id: int,
    payload: RegistrationPersonEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = str(uuid.uuid4())
    emp_id = current_user.get("emp_id")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update.")

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
                UPDATE {DB_SCHEMA}.registration_persons
                SET {', '.join(fields)}
                WHERE person_id = ${len(values) + 1}
                RETURNING *
            """

            values.append(person_id)

            async with conn.transaction():
                row = await conn.fetchrow(sql, *values)

            if not row:
                raise HTTPException(status_code=404, detail="Registration person not found.")

            log.info("Registration person updated person_id=%s", person_id)

            return RegistrationPersonOut.model_validate(row).model_copy(
                update={"message": "Registration person updated successfully."}
            )

        except asyncpg.PostgresError:
            log.exception("Database error during update")
            raise HTTPException(status_code=500, detail="Database error.")

        except Exception:
            log.exception("Unexpected error during update")
            raise HTTPException(status_code=500, detail="Internal server error.")
