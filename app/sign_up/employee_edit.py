import logging
import uuid
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import EmailStr, constr, validator
from typing import Optional, List
import re
from datetime import datetime
from app.utils import get_db_pool, DB_SCHEMA
from app.sign_up.schemas import EmployeeEditIn, EmployeeOut
from app.customer_registration.validators import validate_email, validate_mobile, validate_url
from fastapi.security import OAuth2PasswordBearer
from app.token_validator import validate_token

logger = logging.getLogger("employee")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

router = APIRouter(
    prefix="/api/v1/employees",
    tags=["Employees"]
)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    valid, reason = await validate_token(token)
    if not valid:
        raise HTTPException(status_code=401, detail=f"Invalid authentication credentials: {reason}")
    return {"token": token}

@router.post("/{emp_id}/edit", response_model=EmployeeOut, dependencies=[Depends(get_current_user)])
async def edit_employee(emp_id: int, payload: EmployeeEditIn):
    pool = await get_db_pool()
    fields, values = [], []

    if payload.username is not None:
        fields.append("username=$%d" % (len(values)+1))
        values.append(payload.username)

    if payload.email is not None:
        try:
            if not validate_email(payload.email):
                logger.warning("Invalid email format during update: %s", payload.email)
                raise HTTPException(status_code=400, detail="Invalid email format")
        except ValueError as e:
            logger.warning("Validation error validating email: %s", str(e))
            raise HTTPException(status_code=400, detail=str(e))
        # Check uniqueness excluding current employee
        existing_email = await pool.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.employees WHERE email=$1 AND emp_id<>$2 LIMIT 1",
            payload.email, emp_id
        )
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already in use by another employee")
        fields.append("email=$%d" % (len(values)+1))
        values.append(payload.email)

    if payload.first_name is not None:
        fields.append("first_name=$%d" % (len(values)+1))
        values.append(payload.first_name)

    if payload.last_name is not None:
        fields.append("last_name=$%d" % (len(values)+1))
        values.append(payload.last_name)

    if payload.phone_number is not None:
        try:
            if not validate_mobile(payload.phone_number):
                logger.warning("Invalid mobile format during update: %s", payload.phone_number)
                raise HTTPException(status_code=400, detail="Invalid mobile number format")
        except ValueError as e:
            logger.warning("Validation error validating mobile number: %s", str(e))
            raise HTTPException(status_code=400, detail=str(e))
        # Check uniqueness excluding current employee
        existing_phone = await pool.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.employees WHERE phone_number=$1 AND emp_id<>$2 LIMIT 1",
            payload.phone_number, emp_id
        )
        if existing_phone:
            raise HTTPException(status_code=400, detail="Phone number already in use by another employee")
        fields.append("phone_number=$%d" % (len(values)+1))
        values.append(payload.phone_number)

    if payload.role is not None:
        fields.append("role=$%d" % (len(values)+1))
        values.append(payload.role)

    if payload.is_active is not None:
        fields.append("is_active=$%d" % (len(values)+1))
        values.append(payload.is_active)

    if payload.employee_image_url is not None:
        try:
            validate_url(payload.employee_image_url)
        except ValueError as e:
            logger.warning("Invalid employee_image_url format during update: %s", str(e))
            raise HTTPException(status_code=400, detail="Invalid employee_image_url format")
        fields.append("employee_image_url=$%d" % (len(values)+1))
        values.append(payload.employee_image_url)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields.append("updated_at=NOW()")
    sql = f"""
        UPDATE {DB_SCHEMA}.employees
        SET {', '.join(fields)}
        WHERE emp_id=$%d
        RETURNING *
    """ % (len(values)+1)
    values.append(emp_id)

    try:
        row = await pool.fetchrow(sql, *values)
        if not row:
            raise HTTPException(status_code=404, detail="Employee not found")

        return {
            **dict(row),
            "emp_id": row["emp_id"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "message": "Employee updated successfully."
        }
    except Exception as e:
        logger.exception("Exception during edit_employee: %s", str(e))
        error_str = str(e).lower()
        if "undefinedcolumnerror" in error_str or "column" in error_str:
            detail_msg = "Database column error: " + str(e)
            raise HTTPException(status_code=400, detail=detail_msg)
        if "not found" in error_str:
            raise HTTPException(status_code=404, detail="Employee not found")
    fields.append("updated_at=NOW()")
    sql = f"""
        UPDATE {DB_SCHEMA}.employees
        SET {', '.join(fields)}
        WHERE emp_id=$%d
        RETURNING *
    """ % (len(values)+1)
    values.append(emp_id)

    try:
        row = await pool.fetchrow(sql, *values)
        if not row:
            raise HTTPException(status_code=404, detail="Employee not found")

        return {**dict(row), "emp_id": row["emp_id"], "message": "Employee updated successfully."}

    except Exception as e:
        logger.exception("Exception during edit_employee: %s", str(e))
        error_str = str(e).lower()
        if "undefinedcolumnerror" in error_str or "column" in error_str:
            detail_msg = "Database column error: " + str(e)
            raise HTTPException(status_code=400, detail=detail_msg)
        if "not found" in error_str:
            raise HTTPException(status_code=404, detail="Employee not found")
        if "email already in use" in error_str or "phone number already in use" in error_str:
            raise HTTPException(status_code=400, detail=str(e))
        raise HTTPException(status_code=500, detail="An unexpected error occurred during employee update")


@router.get("/filter", response_model=List[EmployeeOut], dependencies=[Depends(get_current_user)])
async def filter_employees(
    emp_id: Optional[int] = Query(None, alias="emp_id"),
    full_name: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    phone_number: Optional[str] = Query(None, alias="phone_number"),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    include_inactive: bool = Query(False, alias="include_inactive"),
    from_date: Optional[datetime] = Query(
        None, description="Start date (ISO 8601 format)"
    ),
    to_date: Optional[datetime] = Query(
        None, description="End date (ISO 8601 format)"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    pool = await get_db_pool()
    conditions = []
    values = []

    if emp_id is not None:
        conditions.append(f"emp_id = ${len(values)+1}")
        values.append(emp_id)

    if full_name is not None:
        conditions.append(f"(first_name || ' ' || last_name) ILIKE ${len(values)+1}")
        values.append(f"%{full_name}%")

    if email is not None:
        conditions.append(f"email ILIKE ${len(values)+1}")
        values.append(f"%{email}%")

    if phone_number is not None:
        conditions.append(f"phone_number = ${len(values)+1}")
        values.append(phone_number)

    if role is not None:
        conditions.append(f"role = ${len(values)+1}")
        values.append(role)

    if is_active is not None:
        conditions.append(f"is_active = ${len(values)+1}")
        values.append(is_active)

    if not include_inactive and is_active is None:
        conditions.append("is_active = TRUE")

    if from_date is not None:
        conditions.append(f"created_at >= ${len(values)+1}")
        values.append(from_date)

    if to_date is not None:
        conditions.append(f"created_at <= ${len(values)+1}")
        values.append(to_date)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.employees
          {where_clause}
         ORDER BY created_at DESC
         LIMIT ${len(values)+1} OFFSET ${len(values)+2}
    """
    values.extend([limit, offset])

    try:
        rows = await pool.fetch(sql, *values)
        return [
            {
                **dict(row),
                "emp_id": row["emp_id"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                "message": "Employee filtered successfully."
            }
            for row in rows
        ]
    except Exception as e:
        logger.exception("Exception during employee filtering: %s", str(e))
        raise
