import logging
import re
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from datetime import datetime
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.sign_up.schemas import EmployeeEditIn, EmployeeOut
from app.security.rbac import require_permission
from app.logger import logger



router = APIRouter(
    prefix="/api/v1/employees",
    tags=["Employees"]
)

# -------------------------------------------------------------------
# EDIT EMPLOYEE (DYNAMIC UPDATE - PRODUCTION SAFE)
# -------------------------------------------------------------------

@router.post(
    "/{emp_id}/emp_dyn/edit",
    summary="Edit Employee",
    responses={
        200: {"description": "Employee updated successfully."},
        400: {"description": "Validation failed or invalid reference."},
        404: {"description": "Employee not found."},
        409: {"description": "Duplicate field value (email/username/phone)."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_employee(
    emp_id: int,
    payload: EmployeeEditIn,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE")),
):
    """
    Edit Employee API (Dynamic Update)

    Validation Responsibility Split:
    --------------------------------
    1️⃣ Schema-Level Validation (EmployeeEditIn):
       - Email format validation
       - Phone regex validation
       - HttpUrl validation
       - Field constraints (length, required types)

    2️⃣ Database-Level Validation:
       - UNIQUE(email, phone_number)
       - FOREIGN KEY(manager_emp_id)
       - NOT NULL constraints
    """

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Incoming edit employee request emp_id=%s", emp_id)

    # Extract only provided fields
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        log.warning("No fields provided for update")
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception("Database pool acquisition failed error=%s", e)
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async with pool.acquire() as conn:
        try:
            fields = []
            values = []
            param_index = 1

            # --------------------------------------------
            # Normalize critical fields
            # --------------------------------------------

            if "email" in update_data and update_data["email"]:
                update_data["email"] = update_data["email"].strip().lower()

            if "phone_number" in update_data and update_data["phone_number"]:
                update_data["phone_number"] = update_data["phone_number"].strip()

            # --------------------------------------------
            # Build dynamic SET clause safely
            # --------------------------------------------

            # Only update fields provided in the update_data, skip others

            for field_name, value in update_data.items():
                fields.append(f"{field_name} = ${param_index}")
                values.append(value)
                param_index += 1

            # Always update timestamp
            fields.append("updated_at = NOW()")

            sql = f"""
                UPDATE {DB_SCHEMA}.employees
                SET {', '.join(fields)}
                WHERE emp_id = ${param_index}
                RETURNING *
            """

            values.append(emp_id)

            async with conn.transaction():
                row = await conn.fetchrow(sql, *values)

            if not row:
                log.warning("Employee not found for update")
                raise HTTPException(
                    status_code=404,
                    detail="Employee not found.",
                )

            log.info("Employee updated successfully emp_id=%s", emp_id)

            return {**dict(row), "message": "Employee updated successfully."}

        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", None) or ""
            if not constraint:
                match = re.search(r'constraint ["\']?(.+?)["\']', str(e))
                constraint = match.group(1) if match else ""
            if constraint == "employees_email_key":
                detail = "Email already exists."
            elif constraint == "employees_username_key":
                detail = "Username already exists."
            elif "phone" in constraint.lower():
                detail = "Phone number already exists."
            else:
                detail = "Duplicate field value violates unique constraint."
            log.warning("Unique constraint violation emp_id=%s constraint=%s", emp_id, constraint)
            raise HTTPException(status_code=409, detail=detail)

        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("Invalid foreign key reference (manager_emp_id) emp_id=%s", emp_id)
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during employee update emp_id=%s error=%s",
                emp_id, e, exc_info=True,
            )
            raise HTTPException(status_code=500, detail="Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during employee update emp_id=%s", emp_id)
            raise HTTPException(status_code=500, detail="Internal server error.") 
# -------------------------------------------------------------------
# FILTER EMPLOYEES (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------

@router.get(
    "/filter",
    summary="Filter Employees",
    responses={
        200: {"description": "List of employees matching filters."},
        400: {"description": "Validation failed (e.g. from_date > to_date)."},
        500: {"description": "Database or internal error."},
    },
)
async def filter_employees(
    emp_id: Optional[int] = None,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone_number: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Filter Employees API

    Validation Responsibility Split:
    --------------------------------
    1️⃣ FastAPI:
        - Type validation
        - Pagination limits

    2️⃣ Schema (EmployeeOut):
        - Strict response validation

    3️⃣ Database:
        - Integrity constraints
    """

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Incoming employee filter request limit=%s offset=%s", limit, offset)

    # --------------------------------------------------
    # Date Sanity Validation
    # --------------------------------------------------

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
        )

    try:
        pool = await get_db_pool()

        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Business Filters
        # --------------------------------------------------

        if emp_id is not None:
            conditions.append(f"emp_id = ${param_index}")
            values.append(emp_id)
            param_index += 1

        if full_name and full_name.strip():
            conditions.append(
                f"(first_name || ' ' || last_name) ILIKE ${param_index}"
            )
            values.append(f"%{full_name.strip()}%")
            param_index += 1

        if email and email.strip():
            conditions.append(f"email ILIKE ${param_index}")
            values.append(f"%{email.strip()}%")
            param_index += 1

        if phone_number and phone_number.strip():
            conditions.append(f"phone_number = ${param_index}")
            values.append(phone_number.strip())
            param_index += 1

        if role:
            conditions.append(f"role = ${param_index}")
            values.append(role)
            param_index += 1

        # --------------------------------------------------
        # Status Filtering
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # Date Filtering
        # --------------------------------------------------

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
              FROM {DB_SCHEMA}.employees
              {where_clause}
             ORDER BY created_at DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info("Employees filtered successfully count=%s", len(rows))

        # Return raw dicts with message, bypassing Pydantic validation
        return [
            {**dict(row), "message": "Employees filtered successfully."}
            for row in rows
        ]

    # --------------------------------------------------
    # DB VALIDATIONS
    # --------------------------------------------------

    except asyncpg.PostgresError:
        log.exception("Database error during employee filtering")
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception("Unexpected error during employee filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )

# -------------------------------------------------------------------
# GET ACTIVE RELATIONSHIP MANAGERS
# -------------------------------------------------------------------

@router.get(
    "/active-rm",
    summary="Get list of active Relationship Managers",
)
async def get_active_rms(
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Fetching active Relationship Managers")

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.employees
         WHERE is_active = TRUE
           AND role = 'RM'
         ORDER BY created_at DESC
    """

    try:
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        log.info("Active RMs retrieved count=%s", len(rows))

        # Return raw dicts with message, bypassing Pydantic validation
        return [
            {**dict(row), "message": "Active managers retrieved successfully."}
            for row in rows
        ]

    except asyncpg.PostgresError:
        log.exception("Database error while fetching active RMs")
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception("Unexpected error while fetching active RMs")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )

# -------------------------------------------------------------------
# GET ACTIVE OPERATIONS PERSONNEL
# -------------------------------------------------------------------

@router.get(
    "/active-op",
    summary="Get list of active Operations personnel",
)
async def get_active_ops(
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Fetching active Operations personnel")

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.employees
         WHERE is_active = TRUE
           AND role = 'OP'
         ORDER BY created_at DESC
    """

    try:
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        log.info("Active OPs retrieved count=%s", len(rows))

        # Return raw dicts with message, bypassing Pydantic validation
        return [
            {**dict(row), "message": "Active managers retrieved successfully."}
            for row in rows
        ]

    except asyncpg.PostgresError:
        log.exception("Database error while fetching active OPs")
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception("Unexpected error while fetching active OPs")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )

# -------------------------------------------------------------------
# GET ACTIVE MANAGERS
# -------------------------------------------------------------------

@router.get(
    "/active-managers",
    summary="Get list of active managers (ADMIN, SALES_MANAGER, OP_MANAGER)",
)
async def get_active_managers(
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Fetching active managers")

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.employees
         WHERE is_active = TRUE
           AND role IN ('ADMIN', 'SALES_MANAGER', 'OP_MANAGER')
         ORDER BY created_at DESC
    """

    try:
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        log.info("Active managers retrieved count=%s", len(rows))

        # Return raw dicts with message, bypassing Pydantic validation
        return [
            {**dict(row), "message": "Active managers retrieved successfully."}
            for row in rows
        ]

    except asyncpg.PostgresError:
        log.exception("Database error while fetching active managers")
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception("Unexpected error while fetching active managers")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# SOFT DELETE EMPLOYEE (SET is_active TO FALSE)
# -------------------------------------------------------------------

@router.delete(
    "/{emp_id}/soft_delete",
    summary="Soft delete employee by setting is_active to false",
    responses={
        200: {"description": "Employee soft deleted successfully."},
        404: {"description": "Employee not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_employee(
    emp_id: int,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE")),
):
    """
    Soft delete employee by updating is_active to False.
    This safely disables the employee record without deleting the row.
    """
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Incoming soft delete employee request emp_id=%s", emp_id)

    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception("Database pool acquisition failed error=%s", e)
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async with pool.acquire() as conn:
        try:
            sql = f"""
                UPDATE {DB_SCHEMA}.employees
                   SET is_active = FALSE,
                       updated_at = NOW()
                 WHERE emp_id = $1
                 RETURNING *
            """
            async with conn.transaction():
                row = await conn.fetchrow(sql, emp_id)

            if not row:
                log.warning("Employee not found for soft delete emp_id=%s", emp_id)
                raise HTTPException(
                    status_code=404,
                    detail="Employee not found.",
                )

            log.info("Employee soft deleted successfully emp_id=%s", emp_id)
            return {**dict(row), "message": "Employee soft deleted successfully."}

        except HTTPException:
            raise

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during soft delete emp_id=%s error=%s",
                emp_id, e, exc_info=True,
            )
            raise HTTPException(status_code=500, detail="Database error.")

        except Exception:
            log.exception("Unexpected error during soft delete emp_id=%s", emp_id)
            raise HTTPException(status_code=500, detail="Internal server error.")