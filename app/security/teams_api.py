from fastapi import APIRouter, HTTPException, Depends, Query
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.security.rbac import require_permission
from app.logger import logger
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
import asyncpg
import logging
import json
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/app/v1/teams", tags=["Teams"])


def _teams_list_tag() -> str:
    return "teams:list:index"


def _team_members_tag(team_id: int) -> str:
    return f"teams:members:index:{team_id}"


async def _invalidate_teams_cache(team_id: Optional[int] = None) -> None:
    await redis_invalidate_tag(_teams_list_tag())
    if team_id is not None:
        await redis_invalidate_tag(_team_members_tag(team_id))

""" this is for team creation"""

@router.post(
    "/create",
    summary="Create Team",
    responses={
        201: {"description": "Team created successfully"},
        400: {"description": "Validation failed"},
        409: {"description": "Duplicate team"},
        500: {"description": "Database error"}
    }
)
async def create_team(
    team_code: str,
    team_name: str,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE"))
):

    request_id = generate_uuid()

    emp_id = current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_team"}
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(status_code=500, detail="Database connection error")

    async with pool.acquire() as conn:

        try:

            row = await conn.fetchrow(
                f"""
                INSERT INTO {DB_SCHEMA}.teams
                (team_code, team_name, created_at, updated_at)
                VALUES ($1,$2,NOW(),NOW())
                RETURNING *
                """,
                team_code.strip().upper(),
                team_name.strip()
            )

            log.info("Team created successfully id=%s", row["id"])
            await _invalidate_teams_cache()

            return dict(row)

        except asyncpg.exceptions.UniqueViolationError:

            raise HTTPException(
                status_code=409,
                detail={
                    "error":{
                        "type":"validation_error",
                        "message":"Validation failed",
                        "fields":{"team_code":"Team code already exists"}
                    }
                }
            )

        except Exception:

            log.exception("Unexpected error creating team")

            raise HTTPException(
                status_code=500,
                detail="Internal server error"
            )

# -------------------------------------------------------------------
# GET TEAMS (Dropdown + Member Count + Manager Info)
# -------------------------------------------------------------------

@router.get(
    "/teams",
    summary="Get Teams for Dropdown",
    responses={
        200: {"description": "Teams fetched successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
)
async def get_teams(
    search: Optional[str] = Query(None, description="Search team name/code"),
    include_inactive: bool = Query(False),
    current_user=Depends(require_permission("USER_ACCESS", "READ")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")

    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_teams"},
    )

    log.info("Incoming get teams request | search=%s", search)
    search_norm = search.strip() if isinstance(search, str) and search.strip() else None
    cache_key = build_cache_key(
        "teams:get_teams",
        search=search_norm,
        include_inactive=include_inactive,
        emp_id=emp_id,
    )

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------

    try:

        pool = await get_db_pool()

    except Exception:

        log.exception("Database pool acquisition failed")

        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async def _load_teams():
        conditions = []
        values = []
        idx = 1

        # --------------------------------------------------
        # Active filter
        # --------------------------------------------------

        if not include_inactive:

            conditions.append("t.is_active = TRUE")

        # --------------------------------------------------
        # Search filter
        # --------------------------------------------------

        if search_norm:

            conditions.append(
                f"(t.team_name ILIKE ${idx} OR t.team_code ILIKE ${idx})"
            )

            values.append(f"%{search_norm}%")

            idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # --------------------------------------------------
        # Query
        # --------------------------------------------------

        query = f"""
            SELECT
                t.id,
                t.team_code,
                t.team_name,
                COUNT(DISTINCT tm.emp_id) AS member_count,
                MAX(tman.manager_emp_id) AS manager_emp_id,
                MAX(e.username) AS manager_username
            FROM {DB_SCHEMA}.teams t
            LEFT JOIN {DB_SCHEMA}.team_members tm
                ON t.id = tm.team_id
                AND tm.is_active = TRUE
            LEFT JOIN {DB_SCHEMA}.team_managers tman
                ON t.id = tman.team_id
                AND tman.is_active = TRUE
            LEFT JOIN {DB_SCHEMA}.employees e
                ON tman.manager_emp_id = e.emp_id
            {where_clause}
            GROUP BY t.id, t.team_code, t.team_name
            ORDER BY t.team_name ASC
        """

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *values)

            log.info("Teams fetched successfully | count=%s", len(rows))
            return {
                "data": [dict(row) for row in rows],
                "request_id": request_id,
            }
        except asyncpg.PostgresError:
            log.exception("Database error during teams fetch")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )
        except HTTPException:
            raise
        except Exception:
            log.exception("Unexpected error during teams fetch")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_teams,
        ttl_seconds=300,
        tags=[_teams_list_tag()],
    )

# -------------------------------------------------------------------
# EDIT TEAM
# -------------------------------------------------------------------


class TeamEditRequest(BaseModel):
    team_code: str
    team_name: str


class TeamAssignMemberRequest(BaseModel):
    team_id: int
    emp_id: int


class TeamSetManagerRequest(BaseModel):
    team_id: int
    manager_emp_id: int


@router.post(
    "/edit/{team_id}",
    summary="Edit Team",
    responses={
        200: {"description": "Team updated successfully"},
        400: {"description": "Validation failed"},
        404: {"description": "Team not found"},
        409: {"description": "Duplicate team code"},
        500: {"description": "Database error"}
    }
)
async def edit_team(
    team_id: int,
    payload: TeamEditRequest,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE"))
):

    request_id = generate_uuid()

    emp_id = current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "edit_team"}
    )

    team_code = payload.team_code
    team_name = payload.team_name

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

            # --------------------------------------------------
            # Normalize values
            # --------------------------------------------------

            team_code = team_code.strip().upper()
            team_name = team_name.strip()

            # --------------------------------------------------
            # Check if team exists
            # --------------------------------------------------

            exists = await conn.fetchval(
                f"""
                SELECT id
                FROM {DB_SCHEMA}.teams
                WHERE id = $1
                """,
                team_id
            )

            if not exists:

                raise HTTPException(
                    status_code=404,
                    detail="Team not found"
                )

            # --------------------------------------------------
            # Prevent no-change update
            # --------------------------------------------------

            old_row = await conn.fetchrow(
                f"""
                SELECT team_code, team_name
                FROM {DB_SCHEMA}.teams
                WHERE id = $1
                """,
                team_id
            )

            if (
                old_row["team_code"] == team_code
                and old_row["team_name"] == team_name
            ):
                raise HTTPException(
                    status_code=400,
                    detail="No changes detected."
                )

            # --------------------------------------------------
            # Update Team
            # --------------------------------------------------

            row = await conn.fetchrow(
                f"""
                UPDATE {DB_SCHEMA}.teams
                SET
                    team_code = $1,
                    team_name = $2,
                    updated_at = NOW()
                WHERE id = $3
                RETURNING *
                """,
                team_code,
                team_name,
                team_id
            )

            log.info("Team updated successfully id=%s", team_id)
            await _invalidate_teams_cache(team_id)

            return dict(row)

        except asyncpg.exceptions.UniqueViolationError:

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {
                            "team_code": "Team code already exists"
                        }
                    }
                }
            )

        except HTTPException:
            raise

        except Exception:

            log.exception("Unexpected error editing team")

            raise HTTPException(
                status_code=500,
                detail="Internal server error"
            )

# -------------------------------------------------------------------
# ADD MEMBER TO TEAM
# -------------------------------------------------------------------

@router.post(
    "/add-member",
    summary="Add Member to Team",
    responses={
        200: {"description": "Member added successfully"},
        400: {"description": "Validation failed"},
        404: {"description": "Team or employee not found"},
        500: {"description": "Database error"}
    }
)
async def add_member(
    team_id: int,
    emp_id: int,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE"))
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id, "api": "add_member"}
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(status_code=500, detail="Database connection error")

    async with pool.acquire() as conn:
        try:

            async with conn.transaction():

                # --------------------------------------------------
                # 1. Check if team exists
                # --------------------------------------------------
                team_exists = await conn.fetchval(
                    f"SELECT id FROM {DB_SCHEMA}.teams WHERE id = $1",
                    team_id
                )

                if not team_exists:
                    raise HTTPException(status_code=404, detail="Team not found")

                # --------------------------------------------------
                # 2. Check if employee exists
                # --------------------------------------------------
                emp_exists = await conn.fetchval(
                    f"SELECT emp_id FROM {DB_SCHEMA}.employees WHERE emp_id = $1",
                    emp_id
                )

                if not emp_exists:
                    raise HTTPException(status_code=404, detail="Employee not found")

                # --------------------------------------------------
                # 3. Prevent moving manager
                # --------------------------------------------------
                is_manager = await conn.fetchval(
                    f"""
                    SELECT 1
                    FROM {DB_SCHEMA}.team_managers
                    WHERE manager_emp_id = $1
                    AND is_active = TRUE
                    """,
                    emp_id
                )

                if is_manager:
                    raise HTTPException(
                        status_code=400,
                        detail="Managers cannot be moved using add-member API. Change manager role first."
                    )

                # --------------------------------------------------
                # 4. Handle moving (deactivate old memberships)
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.team_members
                    SET is_active = FALSE,
                        updated_at = NOW()
                    WHERE emp_id = $1
                    """,
                    emp_id
                )

                # --------------------------------------------------
                # 5. Insert new membership
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.team_members
                    (team_id, emp_id, is_active, created_at, updated_at)
                    VALUES ($1, $2, TRUE, NOW(), NOW())
                    ON CONFLICT (team_id, emp_id) 
                    DO UPDATE SET
                        is_active = TRUE,
                        updated_at = NOW()
                    """,
                    team_id,
                    emp_id
                )

                log.info(
                    "Member added to team successfully | team_id=%s, emp_id=%s",
                    team_id,
                    emp_id
                )
                await _invalidate_teams_cache(team_id)

                return {"message": "Member added successfully"}

        except HTTPException:
            raise
        except Exception:
            log.exception("Unexpected error adding member to team")
            raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/assign-member",
    summary="Assign/Move Employee to Team (membership only)",
    responses={
        200: {"description": "Member assigned successfully"},
        400: {"description": "Validation failed"},
        404: {"description": "Team or employee not found"},
        500: {"description": "Database error"}
    }
)
async def assign_member(
    payload: TeamAssignMemberRequest,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE"))
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("sub")
    actor_emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id, "api": "assign_member"}
    )

    team_id = payload.team_id
    emp_id = payload.emp_id

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(status_code=500, detail="Database connection error")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                team_exists = await conn.fetchval(
                    f"SELECT id FROM {DB_SCHEMA}.teams WHERE id = $1 AND is_active = TRUE",
                    team_id
                )
                if not team_exists:
                    raise HTTPException(status_code=404, detail="Team not found")

                emp_exists = await conn.fetchval(
                    f"SELECT emp_id FROM {DB_SCHEMA}.employees WHERE emp_id = $1 AND is_active = TRUE",
                    emp_id
                )
                if not emp_exists:
                    raise HTTPException(status_code=404, detail="Employee not found")

                is_active_manager = await conn.fetchval(
                    f"""
                    SELECT 1
                    FROM {DB_SCHEMA}.team_managers
                    WHERE manager_emp_id = $1
                      AND is_active = TRUE
                    LIMIT 1
                    """,
                    emp_id
                )
                if is_active_manager:
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot move active team manager via assign-member. Reassign manager first.",
                    )

                old_team_id = await conn.fetchval(
                    f"""
                    SELECT team_id
                    FROM {DB_SCHEMA}.team_members
                    WHERE emp_id = $1
                      AND is_active = TRUE
                    LIMIT 1
                    """,
                    emp_id,
                )

                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.team_members
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE emp_id = $1
                    """,
                    emp_id
                )

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.team_members
                    (team_id, emp_id, is_active, created_at, updated_at)
                    VALUES ($1, $2, TRUE, NOW(), NOW())
                    ON CONFLICT (team_id, emp_id)
                    DO UPDATE SET is_active = TRUE, updated_at = NOW()
                    """,
                    team_id,
                    emp_id
                )

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    actor_emp_id,
                    "TEAM_MEMBER_ASSIGNMENT",
                    emp_id,
                    None,
                    "UPDATE",
                    json.dumps({"old_team_id": old_team_id, "emp_id": emp_id}, default=str),
                    json.dumps({"new_team_id": team_id, "emp_id": emp_id}, default=str),
                )

            await _invalidate_teams_cache(team_id)
            return {"message": "Member assigned successfully"}
        except HTTPException:
            raise
        except Exception:
            log.exception("Unexpected error assigning team member")
            raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/set-manager",
    summary="Set Team Manager (manager mapping only)",
    responses={
        200: {"description": "Team manager set successfully"},
        400: {"description": "Validation failed"},
        404: {"description": "Team or manager not found"},
        500: {"description": "Database error"}
    }
)
async def set_team_manager(
    payload: TeamSetManagerRequest,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE"))
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("sub")
    actor_emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id, "api": "set_team_manager"}
    )

    team_id = payload.team_id
    manager_emp_id = payload.manager_emp_id
    manager_roles = ("ADMIN", "SALES_MANAGER", "OP_MANAGER")
    normal_role = "NORMAL"

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(status_code=500, detail="Database connection error")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                team_exists = await conn.fetchval(
                    f"SELECT id FROM {DB_SCHEMA}.teams WHERE id = $1 AND is_active = TRUE",
                    team_id
                )
                if not team_exists:
                    raise HTTPException(status_code=404, detail="Team not found")

                manager_row = await conn.fetchrow(
                    f"""
                    SELECT emp_id, role, is_active
                    FROM {DB_SCHEMA}.employees
                    WHERE emp_id = $1
                    """,
                    manager_emp_id
                )
                if not manager_row or not manager_row["is_active"]:
                    raise HTTPException(status_code=404, detail="Manager employee not found")

                role_norm = (manager_row["role"] or "").strip().upper()
                if role_norm not in manager_roles:
                    raise HTTPException(
                        status_code=400,
                        detail="Manager must have role ADMIN/SALES_MANAGER/OP_MANAGER"
                    )

                is_member = await conn.fetchval(
                    f"""
                    SELECT 1
                    FROM {DB_SCHEMA}.team_members
                    WHERE team_id = $1 AND emp_id = $2 AND is_active = TRUE
                    LIMIT 1
                    """,
                    team_id,
                    manager_emp_id
                )
                if not is_member:
                    raise HTTPException(
                        status_code=400,
                        detail="Manager must be an active member of the same team"
                    )

                previous_manager_emp_id = await conn.fetchval(
                    f"""
                    SELECT manager_emp_id
                    FROM {DB_SCHEMA}.team_managers
                    WHERE team_id = $1 AND is_active = TRUE
                    LIMIT 1
                    """,
                    team_id
                )

                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.team_managers
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE team_id = $1 AND is_active = TRUE
                    """,
                    team_id
                )

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.team_managers
                    (team_id, manager_emp_id, is_active, created_at, updated_at)
                    VALUES ($1, $2, TRUE, NOW(), NOW())
                    ON CONFLICT DO NOTHING
                    """,
                    team_id,
                    manager_emp_id
                )

                # Previous manager becomes NORMAL when replaced.
                if previous_manager_emp_id and previous_manager_emp_id != manager_emp_id:
                    previous_role_norm = await conn.fetchval(
                        f"SELECT role FROM {DB_SCHEMA}.employees WHERE emp_id = $1",
                        previous_manager_emp_id,
                    )
                    previous_role_norm = (previous_role_norm or "").strip().upper()
                    # Never downgrade ADMIN automatically.
                    if previous_role_norm != "ADMIN":
                        await conn.execute(
                            f"""
                            UPDATE {DB_SCHEMA}.employees
                            SET role = $1, updated_at = NOW()
                            WHERE emp_id = $2
                            """,
                            normal_role,
                            previous_manager_emp_id
                        )

                # Make sure new manager keeps a manager-capable role.
                if role_norm != "ADMIN":
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.employees
                        SET role = 'SALES_MANAGER', updated_at = NOW()
                        WHERE emp_id = $1
                          AND role NOT IN ('ADMIN','SALES_MANAGER','OP_MANAGER')
                        """,
                        manager_emp_id
                    )

                # Cascade reporting manager for all active members in this team.
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.employees e
                    SET manager_emp_id = $1,
                        updated_at = NOW()
                    FROM {DB_SCHEMA}.team_members tm
                    WHERE tm.team_id = $2
                      AND tm.is_active = TRUE
                      AND tm.emp_id = e.emp_id
                      AND e.emp_id <> $1
                    """,
                    manager_emp_id,
                    team_id
                )

                # Manager should not report to self.
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.employees
                    SET manager_emp_id = NULL,
                        updated_at = NOW()
                    WHERE emp_id = $1
                    """,
                    manager_emp_id
                )

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    actor_emp_id,
                    "TEAM_MANAGER",
                    team_id,
                    None,
                    "UPDATE",
                    json.dumps(
                        {
                            "team_id": team_id,
                            "previous_manager_emp_id": previous_manager_emp_id,
                        },
                        default=str,
                    ),
                    json.dumps(
                        {
                            "team_id": team_id,
                            "new_manager_emp_id": manager_emp_id,
                        },
                        default=str,
                    ),
                )

            await _invalidate_teams_cache(team_id)
            return {"message": "Team manager set successfully"}
        except HTTPException:
            raise
        except Exception:
            log.exception("Unexpected error setting team manager")
            raise HTTPException(status_code=500, detail="Internal server error")
# -------------------------------------------------------------------
# REMOVE MEMBER FROM TEAM
# -------------------------------------------------------------------

@router.post(
    "/remove-member",
    summary="Remove Member from Team",
    responses={
        200: {"description": "Member removed successfully"},
        404: {"description": "Membership not found"},
        500: {"description": "Database error"}
    }
)
async def remove_member(
    team_id: int,
    emp_id: int,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE"))
):
    request_id = generate_uuid()
    current_emp_id = current_user.get("sub")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id, "api": "remove_member"}
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(status_code=500, detail="Database connection error")

    async with pool.acquire() as conn:
        try:

            async with conn.transaction():

                # --------------------------------------------------
                # Prevent removing manager
                # --------------------------------------------------
                is_manager = await conn.fetchval(
                    f"""
                    SELECT 1
                    FROM {DB_SCHEMA}.team_managers
                    WHERE manager_emp_id = $1
                    AND is_active = TRUE
                    """,
                    emp_id
                )

                if is_manager:
                    raise HTTPException(
                        status_code=400,
                        detail="Team manager cannot be removed. Change manager role first."
                    )

                # --------------------------------------------------
                # Deactivate membership
                # --------------------------------------------------
                res = await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.team_members
                    SET is_active = FALSE,
                        updated_at = NOW()
                    WHERE team_id = $1
                    AND emp_id = $2
                    """,
                    team_id,
                    emp_id
                )

                if "UPDATE 0" in res:
                    raise HTTPException(
                        status_code=404,
                        detail="Active membership not found"
                    )

                log.info(
                    "Member removed from team successfully | team_id=%s, emp_id=%s",
                    team_id,
                    emp_id
                )
                await _invalidate_teams_cache(team_id)

                return {"message": "Member removed successfully"}

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error removing member from team")
            raise HTTPException(status_code=500, detail="Internal server error")

@router.get(
    "/{team_id}/members",
    summary="Get Team Members",
    responses={
        200: {"description": "Team members fetched successfully"},
        404: {"description": "Team not found"},
        500: {"description": "Database error"}
    }
)
async def get_team_members(
    team_id: int,
    current_user=Depends(require_permission("USER_ACCESS", "READ"))
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")

    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_team_members"}
    )
    cache_key = build_cache_key(
        "teams:get_members",
        team_id=team_id,
        emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()

    except Exception:

        log.exception("Database pool acquisition failed")

        raise HTTPException(
            status_code=500,
            detail="Database connection error"
        )

    async def _load_team_members():
        async with pool.acquire() as conn:
            try:
                team = await conn.fetchrow(
                    f"""
                    SELECT id, team_name
                    FROM {DB_SCHEMA}.teams
                    WHERE id=$1
                    AND is_active=TRUE
                    """,
                    team_id
                )

                if not team:
                    raise HTTPException(
                        status_code=404,
                        detail="Team not found"
                    )

                rows = await conn.fetch(
                    f"""
                    SELECT
                        e.emp_id,
                        e.username,
                        e.role,
                        CASE
                            WHEN tmgr.manager_emp_id IS NOT NULL THEN TRUE
                            ELSE FALSE
                        END AS is_manager
                    FROM {DB_SCHEMA}.team_members tm
                    JOIN {DB_SCHEMA}.employees e
                        ON tm.emp_id = e.emp_id
                    LEFT JOIN {DB_SCHEMA}.team_managers tmgr
                        ON tmgr.manager_emp_id = e.emp_id
                        AND tmgr.team_id = tm.team_id
                        AND tmgr.is_active = TRUE
                    WHERE tm.team_id = $1
                    AND tm.is_active = TRUE
                    ORDER BY is_manager DESC, e.username
                    """,
                    team_id
                )

                manager = None
                members = []

                for r in rows:
                    data = dict(r)
                    if data["is_manager"]:
                        manager = data
                    members.append(data)

                return {
                    "team_id": team["id"],
                    "team_name": team["team_name"],
                    "manager": manager,
                    "members": members,
                    "request_id": request_id
                }
            except asyncpg.PostgresError:
                log.exception("Database error fetching team members")
                raise HTTPException(
                    status_code=500,
                    detail="Database error occurred"
                )
            except HTTPException:
                raise
            except Exception:
                log.exception("Unexpected error fetching team members")
                raise HTTPException(
                    status_code=500,
                    detail="Internal server error"
                )

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_team_members,
        ttl_seconds=300,
        tags=[_team_members_tag(team_id)],
    )