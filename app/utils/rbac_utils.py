from typing import Dict
from app.utils import get_db_pool
import os

DB_SCHEMA = os.getenv("DB_SCHEMA", "solvetax")

async def get_user_roles(emp_id: int, conn) -> list[int]:
    """
    Fetch all role IDs for an employee (direct and via group membership).
    """
    role_ids = set()
    # Direct employee-role assignments
    rows = await conn.fetch(f"""
        SELECT role_id FROM {DB_SCHEMA}.employee_roles WHERE emp_id = $1
    """, emp_id)
    for row in rows:
        role_ids.add(row["role_id"])
    # Roles via group membership (if you have groups managed in your system)
    rows = await conn.fetch(f"""
        SELECT ra.role_id
        FROM {DB_SCHEMA}.group_members gm
        JOIN {DB_SCHEMA}.role_assignments ra ON gm.group_id = ra.group_id
        WHERE gm.emp_id = $1
    """, emp_id)
    for row in rows:
        role_ids.add(row["role_id"])
    return list(role_ids)

async def get_user_permissions(emp_id: int, conn) -> Dict[str, str]:
    """
    Fetch all permissions for a user based on their roles.
    Returns a dict suitable for embedding in JWT.
    """
    role_ids = await get_user_roles(emp_id, conn)
    if not role_ids:
        return {"platform": {}}
    rows = await conn.fetch(f"""
        SELECT p.feature_code, rp.permission_code 
        FROM {DB_SCHEMA}.permissions p
        JOIN {DB_SCHEMA}.role_permissions rp ON p.id = rp.permission_id
        WHERE rp.role_id = ANY($1::int[])
    """, role_ids)
    permissions = {"platform": {}}
    for row in rows:
        permissions["platform"][row["feature_code"]] = row["permission_code"]
    return permissions
