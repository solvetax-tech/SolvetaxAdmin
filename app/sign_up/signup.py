from fastapi import APIRouter, status, HTTPException, Depends
from app.sign_up.schemas import SignupRequest, SignupResponse, ErrorResponse
from app.utils import get_db_pool, hash_password, is_password_strong, DB_SCHEMA, generate_uuid
from app.security.rbac import require_permission
from app.logger import logger
from dotenv import load_dotenv
from typing import Optional
import os
import asyncpg
import logging
import json
from datetime import datetime, timezone  # ✅ ADDED

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

router = APIRouter(prefix="/app/v1", tags=["Signup"])


# --------------------------------------------------
# DB Helper Functions
# --------------------------------------------------

async def get_role_id(conn: asyncpg.Connection, role_code: str) -> Optional[int]:
    row = await conn.fetchrow(
        f"SELECT id FROM {DB_SCHEMA}.roles WHERE role_code = $1",
        role_code
    )
    if not row:
        return None
    return row["id"]


async def assign_role_to_employee(conn: asyncpg.Connection, emp_id: int, role_id: int) -> None:
    await conn.execute(
        f"""
        INSERT INTO {DB_SCHEMA}.employee_roles
        (emp_id, role_id, is_active, created_at, updated_at)
        VALUES ($1,$2,true,NOW(),NOW())
        ON CONFLICT DO NOTHING
        """,
        emp_id,
        role_id
    )


async def create_user(conn: asyncpg.Connection, user_data: dict) -> Optional[int]:
    row = await conn.fetchrow(
        f"""
        INSERT INTO {DB_SCHEMA}.employees
        (username,email,password_hash,first_name,last_name,phone_number,is_active,role,manager_emp_id,created_at,updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,true,$7,$8,NOW(),NOW())
        RETURNING emp_id
        """,
        user_data["username"],
        user_data["email"],
        user_data["password_hash"],
        user_data["first_name"],
        user_data["last_name"],
        user_data["phone_number"],
        user_data["role"],
        user_data["manager_emp_id"]
    )

    return row["emp_id"] if row else None


# --------------------------------------------------
# Signup API
# --------------------------------------------------

@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=SignupResponse,
    responses={
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def signup(
    payload: SignupRequest,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE")),
):

    request_id = generate_uuid()

    emp_id = current_user.get("sub", "-")
    try:
        emp_id = int(emp_id)
    except (TypeError, ValueError):
        emp_id = None

    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    # --------------------------------------------------
    # Normalize Inputs
    # --------------------------------------------------

    normalized_email = payload.email.strip().lower() if payload.email else None
    username = payload.username.strip().lower() if payload.username else None

    first_name = payload.first_name.strip() if payload.first_name else None
    last_name = payload.last_name.strip() if payload.last_name else None
    phone_number = payload.phone_number.strip() if payload.phone_number else None

    log.info("[signup] Incoming request username=%s email=%s", username, normalized_email)

    # --------------------------------------------------
    # Password Strength Validation
    # --------------------------------------------------

    if not is_password_strong(payload.password):

        log.warning("[signup] Weak password for username=%s email=%s", username, normalized_email)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "type": "validation_error",
                    "message": "Validation failed",
                    "fields": {
                        "password": "Password is not secure enough"
                    }
                }
            }
        )

    # --------------------------------------------------
    # DB Connection
    # --------------------------------------------------

    try:
        pool = await get_db_pool()

    except Exception:

        log.error("[signup] DB pool initialization failed", exc_info=True)

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable."
        )

    async with pool.acquire() as conn:

        # --------------------------------------------------
        # EMAIL VERIFICATION CHECK (LATEST ROW ONLY)
        # --------------------------------------------------

        verification_row = await conn.fetchrow(
            f"""
            SELECT is_verified, expires_at
            FROM {DB_SCHEMA}.employee_email_verifications
            WHERE lower(trim(email)) = lower(trim($1))
            ORDER BY created_at DESC
            LIMIT 1
            """,
            normalized_email
        )

        if verification_row["is_verified"] is not True:
            raise HTTPException(
                status_code=400,
                detail={
                    "error":{
                        "type":"validation_error",
                        "message":"Email not verified",
                        "fields":{"email":"Please verify email before signup"}
                    }
                }
            )

        if verification_row["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=400,
                detail={
                    "error":{
                        "type":"validation_error",
                        "message":"Verification expired",
                        "fields":{"email":"Please verify email again verification time expired"}
                    }
                }
            )

        # --------------------------------------------------
        # FINAL TRUTH CHECK
        # --------------------------------------------------

        exists_email = await conn.fetchval(
            f"""
            SELECT EXISTS(
                SELECT 1 FROM {DB_SCHEMA}.employees
                WHERE lower(trim(email)) = lower(trim($1))
            )
            """,
            normalized_email
        )

        if exists_email:
            raise HTTPException(
                status_code=409,
                detail={
                    "error":{
                        "type":"validation_error",
                        "message":"Email already exists",
                        "fields":{"email":"Already registered"}
                    }
                }
            )

        # --------------------------------------------------
        # Validate Role
        # --------------------------------------------------

        role_code = payload.role

        role_id = await get_role_id(conn, role_code)

        if not role_id:

            log.warning("[signup] Invalid role code provided: %s", role_code)

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": f"Invalid role code: {role_code}",
                        "fields": {}
                    }
                }
            )

        # --------------------------------------------------
        # Validate Manager Role
        # --------------------------------------------------

        if payload.manager_emp_id is not None:

            manager_valid = await conn.fetchval(
                f"""
                SELECT EXISTS(
                    SELECT 1
                    FROM {DB_SCHEMA}.employees e
                    JOIN {DB_SCHEMA}.employee_roles er ON e.emp_id = er.emp_id
                    JOIN {DB_SCHEMA}.roles r ON er.role_id = r.id
                    WHERE e.emp_id = $1
                    AND e.is_active = TRUE
                    AND r.role_code IN ('ADMIN','SALES_MANAGER','OP_MANAGER')
                )
                """,
                payload.manager_emp_id
            )

            if not manager_valid:

                log.warning("[signup] Invalid manager_emp_id: %s", payload.manager_emp_id)

                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error":{
                            "type":"validation_error",
                            "message":"Invalid or unauthorized manager_emp_id",
                            "fields":{"manager_emp_id":"Invalid or unauthorized manager"}
                        }
                    }
                )

        password_hash = hash_password(payload.password)

        # --------------------------------------------------
        # Duplicate Check
        # --------------------------------------------------

        field_errors = {}

        duplicate_row = await conn.fetchrow(
            f"""
            SELECT
            EXISTS(
                SELECT 1 FROM {DB_SCHEMA}.employees
                WHERE lower(trim(username)) = lower(trim($1))
            ) AS username_match,

            EXISTS(
                SELECT 1 FROM {DB_SCHEMA}.employees
                WHERE lower(trim(email)) = lower(trim($2))
            ) AS email_match,

            EXISTS(
                SELECT 1 FROM {DB_SCHEMA}.employees
                WHERE trim(phone_number) = trim($3)
            ) AS phone_match
            """,
            username,
            normalized_email,
            phone_number
        )

        if duplicate_row:

            if duplicate_row["username_match"]:
                field_errors["username"] = "Username already exists"

            if duplicate_row["email_match"]:
                field_errors["email"] = "Email already exists"

            if duplicate_row["phone_match"]:
                field_errors["phone_number"] = "Phone number already exists"

        if field_errors:

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error":{
                        "type":"validation_error",
                        "message":"Validation failed",
                        "fields":field_errors
                    }
                }
            )

        user_data = {
            "username": username,
            "email": normalized_email,
            "password_hash": password_hash,
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": phone_number,
            "role": role_code,
            "manager_emp_id": payload.manager_emp_id
        }

        log.info("[signup] Creating user username=%s email=%s", username, normalized_email)

        try:

            async with conn.transaction():

                created_id = await create_user(conn, user_data)

                if not created_id:

                    log.error("[signup] Failed to create employee")

                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Could not create employee"
                    )

                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.employee_email_verifications
                    SET emp_id=$1
                    WHERE id = (
                        SELECT id
                        FROM {DB_SCHEMA}.employee_email_verifications
                        WHERE lower(trim(email)) = lower(trim($2))
                        ORDER BY created_at DESC
                        LIMIT 1
                    )
                    """,
                    created_id,
                    normalized_email
                )

                await assign_role_to_employee(conn, created_id, role_id)

                if payload.team_id:

                    team_exists = await conn.fetchval(
                        f"""
                        SELECT EXISTS(
                            SELECT 1
                            FROM {DB_SCHEMA}.teams
                            WHERE id = $1
                            AND is_active = TRUE
                        )
                        """,
                        payload.team_id
                    )

                    if not team_exists:

                        raise HTTPException(
                            status_code=400,
                            detail={
                                "error":{
                                    "type":"validation_error",
                                    "message":"Validation failed",
                                    "fields":{
                                        "team_id":"Invalid team id"
                                    }
                                }
                            }
                        )

                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.team_members
                        (team_id, emp_id, is_active, created_at, updated_at)
                        VALUES ($1,$2,TRUE,NOW(),NOW())
                        ON CONFLICT DO NOTHING
                        """,
                        payload.team_id,
                        created_id
                    )

                if payload.role in ["SALES_MANAGER","OP_MANAGER"] and payload.team_id:

                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.team_managers
                        (team_id, manager_emp_id, is_active, created_at, updated_at)
                        VALUES ($1,$2,TRUE,NOW(),NOW())
                        ON CONFLICT DO NOTHING
                        """,
                        payload.team_id,
                        created_id
                    )

                employee_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.employees
                    WHERE emp_id = $1
                    """,
                    created_id
                )

                employee_dict = dict(employee_row)
                employee_dict.pop("password_hash", None)

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id,entity_type,entity_id,customer_id,action,json,updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "SIGNUP",
                    created_id,
                    None,
                    "CREATE",
                    json.dumps(employee_dict, default=str),
                    None
                )

        except asyncpg.exceptions.UniqueViolationError as e:

            log.error("[signup] Duplicate constraint violation: %s", e)

            constraint = getattr(e, "constraint_name", None)

            if constraint == "uq_employees_email":
                err = {"error":{"type":"validation_error","message":"Validation failed","fields":{"email":"Email already exists"}}}

            elif constraint == "uq_employees_username":
                err = {"error":{"type":"validation_error","message":"Validation failed","fields":{"username":"Username already exists"}}}

            elif constraint == "uq_employees_phone":
                err = {"error":{"type":"validation_error","message":"Validation failed","fields":{"phone_number":"Phone number already exists"}}}

            else:
                err = {"error":{"type":"validation_error","message":"Validation failed","fields":{}}}

            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=err)

        except asyncpg.exceptions.ForeignKeyViolationError as e:

            log.error("[signup] Foreign key violation: %s", e)

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error":{
                        "type":"validation_error",
                        "message":"Invalid manager_emp_id",
                        "fields":{"manager_emp_id":"Invalid manager"}
                    }
                }
            )

        except HTTPException:
            raise

        except Exception as e:

            log.error("[signup] Unexpected error: %s", e, exc_info=True)

            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error":{
                        "type":"server_error",
                        "message":"Service temporarily unavailable. Please try again later.",
                        "fields":{}
                    }
                }
            )

        log.info("[signup] Employee created successfully id=%s", created_id)

        return SignupResponse(
            emp_id=created_id,
            username=username,
            message="Employee registered."
        )