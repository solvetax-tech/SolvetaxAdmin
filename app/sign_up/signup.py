
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
import re

# Load environment variables from api/.env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

router = APIRouter(prefix="/app/v1", tags=["Signup"])

# --- DB Helper Functions ---
async def get_role_id(conn: asyncpg.Connection, role_code: str) -> Optional[int]:
    """Retrieve role_id for a given role_code."""
    row = await conn.fetchrow(
        f"SELECT id FROM {DB_SCHEMA}.roles WHERE role_code = $1",
        role_code
    )
    if not row:
        return None
    return row["id"]

async def assign_role_to_employee(conn: asyncpg.Connection, emp_id: int, role_id: int) -> None:
    """Assign a role to an employee."""
    await conn.execute(
        f"""
        INSERT INTO {DB_SCHEMA}.employee_roles(emp_id, role_id, is_active, created_at, updated_at)
        VALUES ($1, $2, true, NOW(), NOW())
        ON CONFLICT DO NOTHING
        """,
        emp_id, role_id
    )

async def create_user(conn: asyncpg.Connection, user_data: dict) -> Optional[int]:
    """Create a new employee user and return the emp_id."""
    row = await conn.fetchrow(
        f"""
        INSERT INTO {DB_SCHEMA}.employees
        (username, email, password_hash, first_name, last_name, phone_number, is_active, role, manager_emp_id, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, true, $7, $8, NOW(), NOW())
        RETURNING emp_id
        """,
        user_data["username"], user_data["email"], user_data["password_hash"], user_data["first_name"],
        user_data["last_name"], user_data["phone_number"], user_data["role"], user_data["manager_emp_id"]
    )
    return row["emp_id"] if row else None


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=SignupResponse,
    dependencies=[Depends(require_permission("USER_ACCESS", "WRITE"))],
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
        emp_id = "-"
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id})

    # Already normalized/trimmed by schema validators + BaseSchema config
    normalized_email = payload.email
    username = payload.username

    log.info("[signup] Incoming request username=%s email=%s", username, normalized_email)

    # Validate password strength (schema also validates, but utils requires special char)
    if not is_password_strong(payload.password):
        log.warning("[signup] Weak password for username=%s, email=%s", username, normalized_email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Validation failed", "fields": {"password": "Password is not secure enough"}}
        )
    
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # Get role_code from payload (defaults to "SE" per schema)
        role_code = payload.role
        role_id = await get_role_id(conn, role_code)
        if not role_id:
            log.warning("[signup] Invalid role code provided: %s", role_code)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Invalid role code: {role_code}"}
            )
        
        # Validate manager_emp_id if provided
        if payload.manager_emp_id is not None:
            manager_valid = await conn.fetchval(
                f"""
                SELECT EXISTS (
                    SELECT 1 FROM {DB_SCHEMA}.employees e
                    JOIN {DB_SCHEMA}.employee_roles er ON e.emp_id = er.emp_id
                    JOIN {DB_SCHEMA}.roles r ON er.role_id = r.id
                    WHERE e.emp_id = $1
                    AND e.is_active = TRUE
                    AND r.role_code IN ('ADMIN', 'SALES_MANAGER', 'OP_MANAGER')
                )
                """,
                payload.manager_emp_id
            )
            if not manager_valid:
                log.warning("[signup] Invalid, inactive, or unauthorized role for manager_emp_id: %s", payload.manager_emp_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Invalid or unauthorized manager_emp_id"}
                )

        # Hash password
        password_hash = hash_password(payload.password)
        
        # Phone number is already trimmed/validated by schema
        phone_number = payload.phone_number

        user_data = {
            "username": username,
            "email": normalized_email,
            "password_hash": password_hash,
            "first_name": payload.first_name,
            "last_name": payload.last_name,
            "phone_number": phone_number,
            "role": role_code,
            "manager_emp_id": payload.manager_emp_id
        }
        
        log.info("[signup] Creating user with username=%s, email=%s", username, normalized_email)
        try:
            # Transaction to create employee and assign role
            async with conn.transaction():
                created_id = await create_user(conn, user_data)
                if not created_id:
                    log.error("[signup] Failed to create user in DB for username=%s", username)
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Could not create employee"
                    )
                
                await assign_role_to_employee(conn, created_id, role_id)
        except asyncpg.exceptions.UniqueViolationError as e:
            log.error("[signup] Duplicate key error: %s", e)
            # Try to extract constraint name from exception
            constraint = getattr(e, "constraint_name", None)
            if not constraint:
                # Fallback: parse from error message
                constraint_match = re.search(r'constraint ["\'](.+?)["\']', str(e))
                if constraint_match:
                    constraint = constraint_match.group(1)
            
            # Map constraint names to user-friendly error messages
            if constraint == "employees_email_key":
                err = {"error": "Email already exists"}
            elif constraint == "employees_username_key":
                err = {"error": "Username already exists"}
            else:
                err = {"error": "Username or email already exists"}
            
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=err
            )
        except asyncpg.exceptions.ForeignKeyViolationError as e:
            log.error("[signup] Foreign key error on manager_emp_id: %s", e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Invalid manager_emp_id"}
            )
        except HTTPException:
            # Re-raise HTTPExceptions (they're already properly formatted)
            raise
        except Exception as e:
            log.error("[signup] Unexpected exception during user creation: %s", e, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "Service temporarily unavailable. Please try again later."}
            )
        
        log.info("[signup] Employee created successfully: id=%s", created_id)
        return SignupResponse(
            emp_id=created_id,
            username=username,
            message="Employee registered."
        )
