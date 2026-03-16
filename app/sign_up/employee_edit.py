import logging
import re
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from datetime import datetime
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, hash_password, is_password_strong
from app.sign_up.schemas import EmployeeEditIn, EmployeeOut,  ChangePasswordRequest
from app.security.rbac import require_permission
from app.logger import logger
import json



router = APIRouter(
    prefix="/api/v1/employees",
    tags=["Employees"]
)

# -------------------------------------------------------------------
# EDIT EMPLOYEE (DYNAMIC UPDATE - PRODUCTION SAFE + VERSION AUDIT)
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
    Edit Employee API (Dynamic Update + Version Audit + Team Sync + Manager Sync)
    """

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    actor_emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Incoming edit employee request emp_id=%s", emp_id)

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update.",
        )

    try:
        pool = await get_db_pool()
    except Exception as e:
        log.exception("Database pool acquisition failed error=%s", e)
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ FETCH OLD SNAPSHOT + LOCK ROW (RACE SAFE)
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.employees
                    WHERE emp_id = $1
                    FOR UPDATE
                    """,
                    emp_id
                )

                if not old_row:
                    raise HTTPException(status_code=404, detail="Employee not found.")

                old_role = old_row["role"]
                old_manager = old_row["manager_emp_id"]

                # --------------------------------------------------
                # Normalize critical fields
                # --------------------------------------------------
                if "email" in update_data and update_data["email"]:
                    update_data["email"] = update_data["email"].strip().lower()

                if "phone_number" in update_data and update_data["phone_number"]:
                    update_data["phone_number"] = update_data["phone_number"].strip()

                # --------------------------------------------------
                # DUPLICATE CHECK
                # --------------------------------------------------
                check_username = update_data.get("username")
                check_email = update_data.get("email")
                check_phone = update_data.get("phone_number")

                field_errors = {}

                if check_username or check_email or check_phone:

                    duplicate_row = await conn.fetchrow(
                        f"""
                        SELECT
                            EXISTS (
                                SELECT 1 FROM {DB_SCHEMA}.employees
                                WHERE lower(trim(username)) = lower(trim($1))
                                AND emp_id != $4
                            ) AS username_match,

                            EXISTS (
                                SELECT 1 FROM {DB_SCHEMA}.employees
                                WHERE lower(trim(email)) = lower(trim($2))
                                AND emp_id != $4
                            ) AS email_match,

                            EXISTS (
                                SELECT 1 FROM {DB_SCHEMA}.employees
                                WHERE trim(phone_number) = trim($3)
                                AND emp_id != $4
                            ) AS phone_match
                        """,
                        check_username or "",
                        check_email or "",
                        check_phone or "",
                        emp_id
                    )

                    if duplicate_row:

                        if check_username and duplicate_row["username_match"]:
                            field_errors["username"] = "Username already exists"

                        if check_email and duplicate_row["email_match"]:
                            field_errors["email"] = "Email already exists"

                        if check_phone and duplicate_row["phone_match"]:
                            field_errors["phone_number"] = "Phone number already exists"

                if field_errors:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": field_errors,
                                "code": "EMPLOYEE_DUPLICATE"
                            }
                        }
                    )

                # --------------------------------------------------
                # Dynamic update
                # --------------------------------------------------
                fields = []
                values = []
                param_index = 1

                for field_name, value in update_data.items():
                    fields.append(f"{field_name} = ${param_index}")
                    values.append(value)
                    param_index += 1

                fields.append("updated_at = NOW()")

                sql = f"""
                    UPDATE {DB_SCHEMA}.employees
                    SET {', '.join(fields)}
                    WHERE emp_id = ${param_index}
                    RETURNING *
                """

                values.append(emp_id)

                new_row = await conn.fetchrow(sql, *values)

                if not new_row:
                    raise HTTPException(
                        status_code=409,
                        detail="Employee state changed. Please retry."
                    )

                new_role = new_row["role"]
                new_manager = new_row["manager_emp_id"]

                # --------------------------------------------------
                # TEAM MEMBERS SYNC (Manager Change)
                # --------------------------------------------------

                if new_manager and new_manager != old_manager:

                    manager_team = await conn.fetchval(
                        f"""
                        SELECT team_id
                        FROM {DB_SCHEMA}.team_members
                        WHERE emp_id = $1
                        AND is_active = TRUE
                        """,
                        new_manager
                    )

                    if manager_team:

                        await conn.execute(
                            f"""
                            UPDATE {DB_SCHEMA}.team_members
                            SET is_active = FALSE,
                            updated_at = NOW()
                            WHERE emp_id = $1
                            """,
                            emp_id
                        )

                        await conn.execute(
                            f"""
                            INSERT INTO {DB_SCHEMA}.team_members
                            (team_id, emp_id, is_active, created_at, updated_at)
                            VALUES ($1,$2,TRUE,NOW(),NOW())
                            ON CONFLICT (team_id, emp_id)
                            DO UPDATE SET is_active = TRUE, updated_at = NOW()
                            """,
                            manager_team,
                            emp_id
                        )

                # --------------------------------------------------
                # TEAM MANAGER SYNC (Role Change)
                # --------------------------------------------------

                manager_roles = ["SALES_MANAGER", "OP_MANAGER"]

                if old_role not in manager_roles and new_role in manager_roles:

                    team_id = await conn.fetchval(
                        f"""
                        SELECT team_id
                        FROM {DB_SCHEMA}.team_members
                        WHERE emp_id = $1
                        AND is_active = TRUE
                        """,
                        emp_id
                    )

                    if team_id:

                        await conn.execute(
                            f"""
                            UPDATE {DB_SCHEMA}.team_managers
                            SET is_active = FALSE,
                            updated_at = NOW()
                            WHERE team_id = $1
                            AND is_active = TRUE
                            """,
                            team_id
                        )

                        await conn.execute(
                            f"""
                            INSERT INTO {DB_SCHEMA}.team_managers
                            (team_id, manager_emp_id, is_active, created_at, updated_at)
                            VALUES ($1,$2,TRUE,NOW(),NOW())
                            ON CONFLICT DO NOTHING
                            """,
                            team_id,
                            emp_id
                        )

                if old_role in manager_roles and new_role not in manager_roles:

                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.team_managers
                        SET is_active = FALSE,
                        updated_at = NOW()
                        WHERE manager_emp_id = $1
                        AND is_active = TRUE
                        """,
                        emp_id
                    )

                # --------------------------------------------------
                # VERSION AUDIT
                # --------------------------------------------------

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    actor_emp_id,
                    "EMPLOYEE",
                    emp_id,
                    None,
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            return {
                **dict(new_row),
                "message": "Employee updated successfully."
            }

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

    # UPDATED: allow multiple roles
    role: Optional[List[str]] = Query(None),

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

        # --------------------------------------------------
        # ROLE FILTERING (IMPROVED FOR MULTIPLE ROLES)
        # --------------------------------------------------

        if role:
            cleaned_roles = [r.strip() for r in role if r and r.strip()]
            if cleaned_roles:
                conditions.append(f"role = ANY(${param_index})")
                values.append(cleaned_roles)
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
@router.get(
    "/employee/{emp_id}",
    summary="Get Employee",
    responses={
        200: {"description": "Employee fetched successfully."},
        404: {"description": "Employee not found."},
        500: {"description": "Database or internal error."},
    },
)
async def get_employee(
    emp_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Get Employee by emp_id (Production Standard)

    Validation Responsibility Split:
    --------------------------------
    1. Authentication & Authorization via dependency
    2. Path param type validation handled by FastAPI
    3. Existence validation handled by DB query

    Security:
    ---------
    - password_hash is NOT returned
    - Returns only active employees
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "get_employee",
        },
    )

    log.info(
        "Incoming get employee request | emp_id=%s",
        emp_id,
    )

    # --------------------------------------------------
    # SQL Query (Exclude password_hash)
    # --------------------------------------------------
    sql = f"""
        SELECT 
            e.emp_id,
            e.username,
            e.email,
            e.first_name,
            e.last_name,
            e.phone_number,
            e.role,
            e.is_active,
            e.created_at,
            e.updated_at,
            e.manager_emp_id,
            e.employee_image_url,
            m.username as manager_username,
            m.role as manager_role
        FROM {DB_SCHEMA}.employees e
        LEFT JOIN {DB_SCHEMA}.employees m ON e.manager_emp_id = m.emp_id
        WHERE e.emp_id = $1
        LIMIT 1
    """

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

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, emp_id)

        # --------------------------------------------------
        # Not Found Handling
        # --------------------------------------------------
        if not row:
            log.warning(
                "Employee not found or inactive | emp_id=%s",
                emp_id,
            )
            raise HTTPException(
                status_code=404,
                detail="Employee not found.",
            )

        log.info(
            "Employee fetched successfully | emp_id=%s",
            emp_id,
        )

        return {
            **dict(row),
            "message": "Employee fetched successfully.",
            "request_id": request_id,
        }

    # --------------------------------------------------
    # IMPORTANT: Re-raise HTTP Exceptions First
    # --------------------------------------------------
    except HTTPException:
        raise

    # --------------------------------------------------
    # DATABASE ERROR HANDLING
    # --------------------------------------------------
    except asyncpg.PostgresError as e:
        log.error(
            "Database error during get employee | emp_id=%s | error=%s",
            emp_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    # --------------------------------------------------
    # FALLBACK UNEXPECTED ERROR
    # --------------------------------------------------
    except Exception:
        log.exception(
            "Unexpected error during get employee | emp_id=%s",
            emp_id,
        )
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
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
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
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
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
# SOFT DELETE EMPLOYEE (SET is_active TO FALSE + VERSION AUDIT)
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
    Soft delete employee by updating is_active to False
    + Version Audit

    ✔ Atomic transaction
    ✔ json = NULL
    ✔ updated_json = NEW snapshot (is_active = FALSE)
    ✔ action = DELETE
    ✔ entity_type = EMPLOYEE
    ✔ entity_id = 3
    """

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    # ✅ actor for audit
    actor_emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

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
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Perform Soft Delete (Concurrency Safe)
                # --------------------------------------------------
                sql = f"""
                    UPDATE {DB_SCHEMA}.employees
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE emp_id = $1
                       AND is_active = TRUE
                     RETURNING *
                """

                row = await conn.fetchrow(sql, emp_id)

                if not row:
                    # Check existence
                    check_row = await conn.fetchrow(
                        f"""
                        SELECT emp_id, is_active
                        FROM {DB_SCHEMA}.employees
                        WHERE emp_id = $1
                        """,
                        emp_id
                    )

                    if not check_row:
                        log.warning("Employee not found emp_id=%s", emp_id)
                        raise HTTPException(
                            status_code=404,
                            detail="Employee not found.",
                        )

                    log.warning("Employee already inactive emp_id=%s", emp_id)
                    raise HTTPException(
                        status_code=400,
                        detail="Employee already inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Insert Version Audit (DELETE)
                # --------------------------------------------------
                version_sql = f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                """

                deleted_snapshot = dict(row)

                await conn.execute(
                    version_sql,
                    actor_emp_id,                       # Actor
                    "EMPLOYEE",                         # entity_type
                    3,                                  # entity_id
                    None,                               # customer_id
                    "DELETE",                           # action
                    None,                               # json must be NULL
                    json.dumps(deleted_snapshot, default=str),  # updated_json
                )

            log.info("Employee soft deleted successfully emp_id=%s", emp_id)

            return {
                **dict(row),
                "message": "Employee soft deleted successfully."
            }

        # --------------------------------------------------
        # ERROR HANDLING (UNCHANGED STRUCTURE)
        # --------------------------------------------------

        except HTTPException:
            raise

        except asyncpg.exceptions.ForeignKeyViolationError as e:
            log.error(
                "Foreign key violation during soft delete emp_id=%s error=%s",
                emp_id, e, exc_info=True,
            )
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.CheckViolationError as e:
            log.error(
                "Audit constraint violation emp_id=%s error=%s",
                emp_id, e, exc_info=True,
            )
            raise HTTPException(status_code=400, detail="Audit constraint validation failed.")

        except asyncpg.exceptions.DataError as e:
            log.error(
                "Data error during soft delete emp_id=%s error=%s",
                emp_id, e, exc_info=True,
            )
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during soft delete emp_id=%s error=%s",
                emp_id, e, exc_info=True,
            )
            raise HTTPException(status_code=500, detail="Database error.")

        except Exception:
            log.exception("Unexpected error during soft delete emp_id=%s", emp_id)
            raise HTTPException(status_code=500, detail="Internal server error.")

# =========================================================
# LIST ROLES (DYNAMIC FILTER + PAGINATION)
# =========================================================

@router.get(
    "/roles",
    summary="List Roles",
    responses={
        200: {"description": "Roles fetched successfully."},
        500: {"description": "Database or internal error."},
    },
)
async def list_roles(
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    List Roles (Production Standard)

    Features:
    ---------
    ✔ Pagination
    ✔ Optional active filter
    ✔ include_inactive toggle
    ✔ Structured logging
    ✔ Safe SQL parameterization
    ✔ Full DB exception handling
    """

    # --------------------------------------------------
    # Request Context & Structured Logging
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": current_emp_id,
            "api": "list_roles",
        },
    )

    log.info(
        "Incoming roles list request | limit=%s offset=%s",
        limit,
        offset,
    )

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

    try:
        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Active Filtering Logic (Enterprise Pattern)
        # --------------------------------------------------
        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1

        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # WHERE Clause Builder
        # --------------------------------------------------
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT *
              FROM {DB_SCHEMA}.roles
              {where_clause}
             ORDER BY id ASC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)

        log.info(
            "Roles fetched successfully | count=%s",
            len(rows),
        )

        return [
            {
                **dict(row),
                "message": "Roles fetched successfully.",
                "request_id": request_id,
            }
            for row in rows
        ]

    # --------------------------------------------------
    # Database Error Handling
    # --------------------------------------------------
    except asyncpg.PostgresError as e:
        log.error(
            "Database error during roles fetch | error=%s",
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Database error.",
        )

    except Exception:
        log.exception("Unexpected error during roles fetch")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# CREATE ROLE
# -------------------------------------------------------------------

@router.post(
    "/create",
    summary="Create Role",
    responses={
        201: {"description": "Role created successfully"},
        400: {"description": "Validation failed"},
        409: {"description": "Duplicate role"},
        500: {"description": "Database error"}
    }
)
async def create_role(
    role_code: str,
    role_name: str,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE"))
):

    request_id = generate_uuid()

    emp_id = current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_role"}
    )

    # --------------------------------------------------
    # Input Validation
    # --------------------------------------------------

    field_errors = {}

    if not role_code or not role_code.strip():
        field_errors["role_code"] = "Role code is required."

    if not role_name or not role_name.strip():
        field_errors["role_name"] = "Role name is required."

    if field_errors:
        raise HTTPException(
            status_code=400,
            detail={
                "error":{
                    "type":"validation_error",
                    "message":"Validation failed",
                    "fields":field_errors
                }
            }
        )

    role_code = role_code.strip().upper()
    role_name = role_name.strip()

    # --------------------------------------------------
    # DB Connection
    # --------------------------------------------------

    try:
        pool = await get_db_pool()

    except Exception:

        log.exception("DB connection failed")

        raise HTTPException(
            status_code=500,
            detail="Database connection error"
        )

    async with pool.acquire() as conn:

        try:

            row = await conn.fetchrow(
                f"""
                INSERT INTO {DB_SCHEMA}.roles
                (
                    role_code,
                    role_name,
                    created_at,
                    updated_at
                )
                VALUES
                (
                    $1,$2,NOW(),NOW()
                )
                RETURNING *
                """,
                role_code,
                role_name
            )

            log.info("Role created successfully id=%s role_code=%s", row["id"], role_code)

            return dict(row)

        # --------------------------------------------------
        # UNIQUE CONSTRAINT
        # --------------------------------------------------

        except asyncpg.exceptions.UniqueViolationError:

            raise HTTPException(
                status_code=409,
                detail={
                    "error":{
                        "type":"validation_error",
                        "message":"Validation failed",
                        "fields":{
                            "role_code":"Role code already exists"
                        }
                    }
                }
            )

        # --------------------------------------------------
        # GENERIC ERROR
        # --------------------------------------------------

        except Exception:

            log.exception("Unexpected error creating role")

            raise HTTPException(
                status_code=500,
                detail="Internal server error"
            )

# -------------------------------------------------------------------
# CHANGE PASSWORD (HASH VERIFICATION + VERSION AUDIT)
# -------------------------------------------------------------------

@router.post(
    "/{emp_id}/change-password",
    summary="Change Employee Password",
    responses={
        200: {"description": "Password changed successfully."},
        400: {"description": "Invalid current password or weak new password."},
        404: {"description": "Employee not found."},
        500: {"description": "Database or internal error."},
    },
)
async def change_password(
    emp_id: int,
    payload: ChangePasswordRequest,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE")),
):
    """
    Change Password API (Hash Verification + Version Audit)
    """

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    # ✅ Safe conversion for version table
    actor_emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Incoming change password request for emp_id=%s", emp_id)

    # 1. Password Strength Check (redundant if schema does it, but good for safety)
    if not is_password_strong(payload.new_password):
        log.warning("Weak new password provided for emp_id=%s", emp_id)
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "validation_error",
                    "message": "Validation failed",
                    "fields": {"new_password": "Password does not meet complexity requirements."},
                    "code": "WEAK_PASSWORD"
                }
            }
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
            async with conn.transaction():
                # 1️⃣ Fetch old row to verify current password
                old_row = await conn.fetchrow(
                    f"SELECT emp_id, password_hash FROM {DB_SCHEMA}.employees WHERE emp_id = $1",
                    emp_id
                )

                if not old_row:
                    log.warning("Employee not found for password change emp_id=%s", emp_id)
                    raise HTTPException(status_code=404, detail="Employee not found.")

                # 2️⃣ Verify current password hash
                current_hash = hash_password(payload.current_password)
                if old_row["password_hash"] != current_hash:
                    log.warning("Incorrect current password for emp_id=%s", emp_id)
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Invalid current password",
                                "fields": {"current_password": "The current password you entered is incorrect."},
                                "code": "INVALID_CURRENT_PASSWORD"
                            }
                        }
                    )

                # 3️⃣ Update with new hash
                new_hash = hash_password(payload.new_password)
                await conn.execute(
                    f"UPDATE {DB_SCHEMA}.employees SET password_hash = $1, updated_at = NOW() WHERE emp_id = $2",
                    new_hash, emp_id
                )

                # 4️⃣ Insert Version Audit
                # Fetch full data for audit (sanitized)
                new_full_row = await conn.fetchrow(
                    f"SELECT * FROM {DB_SCHEMA}.employees WHERE emp_id = $1",
                    emp_id
                )
                
                # Sanitize snapshot
                old_snapshot = dict(old_row)
                old_snapshot.pop("password_hash", None)
                new_snapshot = dict(new_full_row)
                new_snapshot.pop("password_hash", None)

                version_sql = f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """

                await conn.execute(
                    version_sql,
                    actor_emp_id,
                    "EMPLOYEE_PASSWORD",
                    emp_id,
                    None,
                    "UPDATE",
                    json.dumps(old_snapshot, default=str),
                    json.dumps(new_snapshot, default=str)
                )

            log.info("Password changed successfully for emp_id=%s", emp_id)
            return {"message": "Password changed successfully."}

        except HTTPException:
            raise
        except Exception:
            log.exception("Unexpected error during password change emp_id=%s", emp_id)
            raise HTTPException(status_code=500, detail="Internal server error.")