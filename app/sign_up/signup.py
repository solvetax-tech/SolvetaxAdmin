
from fastapi import APIRouter, status, HTTPException, Request, Body, Depends
from fastapi.responses import JSONResponse
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
async def is_email_or_username_taken(conn, email, username):
    row = await conn.fetchrow(
        f"SELECT 1 FROM {DB_SCHEMA}.employees WHERE email = $1 OR username = $2",
        email, username
    )
    return row is not None

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
    response_model=SignupResponse,
    dependencies=[Depends(require_permission("USER_ACCESS", "WRITE"))],
    responses={
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def signup(
    request: Request,
    payload: SignupRequest,
):
    logging.info(f"[signup] Incoming request: {payload}")
    # Validate password strength
    if not is_password_strong(payload.password):
        logging.warning(f"[signup] Weak password for username={payload.username}, email={payload.email}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "Validation failed",
                "fields": {"password": "Password is not secure enough"}
            }
        )
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # Check for existing email or username
        try:
            logging.info(f"[signup] Checking for existing email or username: email={payload.email}, username={payload.username}")
            if await is_email_or_username_taken(conn, payload.email, payload.username):
                logging.warning(f"[signup] Username or email already exists: email={payload.email}, username={payload.username}")
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={"error": "Username or email already exists"}
                )
        except Exception as e:
            logging.error(f"[signup] Error checking for existing user: {e}")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": "Service temporarily unavailable. Please try again later."}
            )

        # Validate that role exists and retrieve role_id
        role_code = getattr(payload, "role", "SE")
        role_id = await get_role_id(conn, role_code)
        if not role_id:
            logging.warning(f"[signup] Invalid role code provided: {role_code}")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": f"Invalid role code: {role_code}"}
            )

        # Validate manager_emp_id if provided
        if payload.manager_emp_id is not None:
            manager_exists = await conn.fetchval(
                f"SELECT EXISTS (SELECT 1 FROM {DB_SCHEMA}.employees WHERE emp_id = $1)",
                payload.manager_emp_id
            )
            if not manager_exists:
                logging.warning(f"[signup] Invalid manager_emp_id: {payload.manager_emp_id}")
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"error": "Invalid manager_emp_id"}
                )

        # Hash password
        password_hash = hash_password(payload.password)
        # Use phone number as-is without checking or adding +91 prefix
        phone_number = str(payload.phone_number) if getattr(payload, "phone_number", None) is not None else None

        user_data = {
            "username": payload.username,
            "email": payload.email,
            "password_hash": password_hash,
            "first_name": payload.first_name,
            "last_name": payload.last_name,
            "phone_number": phone_number,
            "role": role_code,
            "manager_emp_id": payload.manager_emp_id
        }
        logging.info(f"[signup] Creating user with username={payload.username}, email={payload.email}")
        try:
            # Transaction to create employee and assign role
            async with conn.transaction():
                created_id = await create_user(conn, user_data)
                if not created_id:
                    logging.error(f"[signup] Failed to create user in DB for username={payload.username}")
                    return JSONResponse(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content={"error": "Service temporarily unavailable. Please try again later."}
                    )
                await assign_role_to_employee(conn, created_id, role_id)
        except asyncpg.exceptions.UniqueViolationError as e:
            logging.error(f"[signup] Duplicate key error: {e}")
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"error": "Username or email already exists"}
            )
        except Exception as e:
            logging.error(f"[signup] Exception during user creation: {e}")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": "Service temporarily unavailable. Please try again later."}
            )
        logging.info(f"[signup] Employee created successfully: id={created_id}")
        return SignupResponse(emp_id=created_id, message="Employee registered.")
