
from fastapi import APIRouter, status, HTTPException, Depends
from app.sign_up.schemas import SignupRequest, SignupResponse, ErrorResponse
from app.utils import get_db_pool, hash_password, is_password_strong, DB_SCHEMA
from app.security.rbac import require_permission
from dotenv import load_dotenv
import os
import asyncpg
import logging

# Load environment variables from api/.env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

router = APIRouter(prefix="/app/v1", tags=["Signup"])

# --- DB Helper Functions ---
async def get_role_id(conn, role_code: str):
    row = await conn.fetchrow(
        f"SELECT id FROM {DB_SCHEMA}.roles WHERE role_code = $1",
        role_code
    )
    if not row:
        return None
    return row["id"]

async def assign_role_to_employee(conn, emp_id: int, role_id: int):
    await conn.execute(
        f"""
        INSERT INTO {DB_SCHEMA}.employee_roles(emp_id, role_id, is_active, created_at, updated_at)
        VALUES ($1, $2, true, NOW(), NOW())
        ON CONFLICT DO NOTHING
        """,
        emp_id, role_id
    )

async def create_user(conn, user_data):
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
):
    # Normalize email to lowercase and strip spaces to avoid duplicates
    normalized_email = payload.email.strip().lower()
    username = payload.username.strip()

    logging.info("[signup] Incoming request username=%s email=%s", username, normalized_email)
    # Validate password strength
    if not is_password_strong(payload.password):
        logging.warning(f"[signup] Weak password for username={payload.username}, email={normalized_email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Validation failed", "fields": {"password": "Password is not secure enough"}}
        )
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # Validate that role exists and retrieve role_id
        role_code = getattr(payload, "role", "NORMAL")
        role_id = await get_role_id(conn, role_code)
        if not role_id:
            logging.warning(f"[signup] Invalid role code provided: {role_code}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": f"Invalid role code: {role_code}"}
            )
        # Check if manager_emp_id is provided, if so validate emp_id exists, is_active, and role is ADMIN or SALES_MANAGER or OP_MANAGER
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
                logging.warning(f"[signup] Invalid, inactive, or unauthorized role for manager_emp_id: {payload.manager_emp_id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": "Invalid or unauthorized manager_emp_id"}
                )

        # Hash password
        password_hash = hash_password(payload.password)
        phone_number = None
        if getattr(payload, "phone_number", None) is not None:
            phone_number = str(payload.phone_number).strip() if str(payload.phone_number).strip() else None

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
        logging.info(f"[signup] Creating user with username={username}, email={normalized_email}")
        try:
            # Transaction to create employee and assign role
            async with conn.transaction():
                created_id = await create_user(conn, user_data)
                if not created_id:
                    logging.error(f"[signup] Failed to create user in DB for username={payload.username}")
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Could not create employee"
                    )
                # Check if manager_emp_id is the same as created employee id
                if payload.manager_emp_id == created_id:
                    # Deactivate the employee by setting is_active to false
                    await conn.execute(
                        f"UPDATE {DB_SCHEMA}.employees SET is_active = false WHERE emp_id = $1",
                        created_id
                    )
                    logging.warning(f"[signup] manager_emp_id is same as employee id: {created_id}. Employee deactivated.")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="manager_emp_id cannot be same as employee. The employee has been deactivated. Please update the manager_emp_id."
                    )
                await assign_role_to_employee(conn, created_id, role_id)
        except asyncpg.exceptions.UniqueViolationError as e:
            logging.error(f"[signup] Duplicate key error: {e}")
            constraint = getattr(e, "constraint_name", None)
            if not constraint:
                import re
                m = re.search(r'constraint \"(.+?)\"', str(e))
                if m:
                    constraint = m.group(1)
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
            logging.error(f"[signup] Foreign key error on manager_emp_id: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "Invalid manager_emp_id"}
            )
        except Exception as e:
            logging.error(f"[signup] Exception during user creation: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "Service temporarily unavailable. Please try again later."}
            )
        logging.info(f"[signup] Employee created successfully: id={created_id}")
        return SignupResponse(emp_id=created_id, message="Employee registered.")
