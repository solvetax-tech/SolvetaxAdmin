from fastapi import Request, HTTPException, status
from app.utils import get_db_pool, DB_SCHEMA
from app.security.rbac import get_current_user_payload

async def require_team_access(target_emp_id: int, request: Request):
    """
    Access allowed if:
    - user is ADMIN (full access)
    - user is accessing himself
    - target employee reports to user
    """
    payload = get_current_user_payload(request)
    current_emp_id = int(payload["sub"])

    # ✅ ADMIN bypass (full access)
    perms = payload.get("permissions", {}).get("platform", {})
    user_access_perms = perms.get("USER_ACCESS", [])
    if "WRITE" in user_access_perms:
        return True

    # ✅ allow self access
    if current_emp_id == target_emp_id:
        return True

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT 1
            FROM {DB_SCHEMA}.employees e
            WHERE e.emp_id = $1
              AND e.manager_emp_id = $2
              AND e.is_active = true
            """,
            target_emp_id,
            current_emp_id,
        )

        if not row:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: not allowed to access this employee (not your team member)"
            )

    return True
