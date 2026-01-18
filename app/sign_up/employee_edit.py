
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from app.utils import get_db_pool, DB_SCHEMA
from app.sign_up.schemas import EmployeeEditIn, EmployeeOut
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/employees",
    tags=["Employees"]
)


# -------------------------------------------------------------------
# LIST EMPLOYEES (with pagination, latest first)
# -------------------------------------------------------------------
@router.get("", response_model=List[EmployeeOut])
async def list_employees(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_inactive: bool = Query(False)
):
    pool = await get_db_pool()
    where_clause = "" if include_inactive else "WHERE is_active = TRUE"
    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.employees
          {where_clause}
         ORDER BY created_at DESC
         LIMIT $1 OFFSET $2
    """
    try:
        rows = await pool.fetch(sql, limit, offset)
        logger.info("Listed employees: count=%d", len(rows))
        return [
            {**dict(row), "emp_id": row["emp_id"], "message": "Employee listed successfully."}
            for row in rows
        ]
    except Exception as e:
        logger.exception("Exception during listing employees: %s", str(e))
        raise


# -------------------------------------------------------------------
# GET EMPLOYEE BY ID
# -------------------------------------------------------------------
@router.get("/{emp_id}", response_model=EmployeeOut)
async def get_employee(emp_id: int):
    pool = await get_db_pool()
    sql = f"""
        SELECT *
          FROM {DB_SCHEMA}.employees
         WHERE emp_id = $1
         LIMIT 1
    """
    try:
        row = await pool.fetchrow(sql, emp_id)
        if not row:
            logger.warning("Employee not found: id=%s", emp_id)
            raise HTTPException(status_code=404, detail="Employee not found")
        logger.info("Fetched employee: id=%s", emp_id)
        return {**dict(row), "emp_id": row["emp_id"], "message": "Employee fetched successfully."}
    except Exception as e:
        logger.exception("Exception during get_employee: %s", str(e))
        raise




@router.post("/{emp_id}/edit")
async def edit_employee(emp_id: int, payload: EmployeeEditIn):
    pool = await get_db_pool()
    fields, values = [], []
    if payload.username is not None:
        fields.append("username=$%d" % (len(values)+1))
        values.append(payload.username)
    if payload.email is not None:
        fields.append("email=$%d" % (len(values)+1))
        values.append(payload.email)
    if payload.first_name is not None:
        fields.append("first_name=$%d" % (len(values)+1))
        values.append(payload.first_name)
    if payload.last_name is not None:
        fields.append("last_name=$%d" % (len(values)+1))
        values.append(payload.last_name)
    if payload.phone_number is not None:
        fields.append("phone_number=$%d" % (len(values)+1))
        values.append(payload.phone_number)
    if payload.role is not None:
        fields.append("role=$%d" % (len(values)+1))
        values.append(payload.role)
    if payload.is_active is not None:
        fields.append("is_active=$%d" % (len(values)+1))
        values.append(payload.is_active)
    if payload.employee_image_url is not None:
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
    row = await pool.fetchrow(sql, *values)
    if not row:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {**dict(row), "emp_id": row["emp_id"]}
