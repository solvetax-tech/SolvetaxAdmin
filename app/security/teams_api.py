from fastapi import APIRouter, HTTPException, Depends, Query
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.security.rbac import require_permission
from app.logger import logger
import asyncpg
import logging
from typing import Optional

router = APIRouter(prefix="/app/v1/teams", tags=["Teams"])

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
# GET TEAMS (Dropdown)
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

    try:

        conditions = []
        values = []
        idx = 1

        # --------------------------------------------------
        # Active filter
        # --------------------------------------------------

        if not include_inactive:

            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # Search filter
        # --------------------------------------------------

        if search:

            conditions.append(f"(team_name ILIKE ${idx} OR team_code ILIKE ${idx})")

            values.append(f"%{search.strip()}%")

            idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            SELECT
                id,
                team_code,
                team_name
            FROM {DB_SCHEMA}.teams
            {where_clause}
            ORDER BY team_name ASC
        """

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