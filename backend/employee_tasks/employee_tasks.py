"""Personal task calendar for staff (`employee_tasks`).

Owner-scoped: every read/write is filtered to emp_id = the caller (from JWT).
Time is quantised to fixed 15-minute slots; a task may block one or more of them
for a single piece of work (stored in time_slots). `available-slots` returns a
full 24h day of slots marked free/taken so the UI can offer a Google-Calendar-
style multi-select picker.
"""

from datetime import date as date_cls, datetime, time as time_cls, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.common.status_constants import (
    TASK_SLOT_MINUTES,
    TASK_STATUSES,
)
from backend.employee_tasks.schemas import (
    AvailableSlotsOut,
    TaskCreateIn,
    TaskListOut,
    TaskOut,
    TaskPatchIn,
)
from backend.logger import logger
from backend.security.rbac import require_permission
from backend.utils import DB_SCHEMA, get_db_pool

router = APIRouter(prefix="/api/v1/employee-tasks", tags=["Employee Tasks"])

IST = ZoneInfo("Asia/Kolkata")
_SLOTS_PER_DAY = 24 * 60 // TASK_SLOT_MINUTES  # 96

_COLUMNS = """
    id, emp_id, title, description, scheduled_at, time_slots, status,
    followup_at, followup_note, is_active, created_at, updated_at
"""


def _ctx(user: dict):
    role = (user.get("role") or "").strip().upper()
    raw = user.get("emp_id") or user.get("sub")
    emp_id = int(raw) if str(raw).isdigit() else 0
    return role, emp_id


def _require_emp(emp_id: int) -> None:
    if emp_id <= 0:
        raise HTTPException(status_code=403, detail="Employee context required.")


def _raise_validation(fields: dict, message: str = "Validation failed", code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"error": {"type": "validation_error", "message": message, "fields": fields}},
    )


def _as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Naive datetimes from the client are interpreted as IST (the app's zone)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt


def _parse_day(date_str: Optional[str]) -> date_cls:
    if not date_str:
        return datetime.now(IST).date()
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        _raise_validation({"date": "Expected date as YYYY-MM-DD."})


def _ist_day_bounds(day: date_cls):
    """[start, end) of the IST calendar day, as aware datetimes."""
    start = datetime.combine(day, time_cls(0, 0), tzinfo=IST)
    return start, start + timedelta(days=1)


async def _find_conflict(conn, emp_id: int, slots: List[datetime], exclude_id: Optional[int]):
    """Return the title of an existing active task that already blocks any of the
    given 15-min slots, or None. Uses array overlap (&&) on time_slots.
    """
    params = [emp_id, slots]
    exclude_sql = ""
    if exclude_id is not None:
        params.append(exclude_id)
        exclude_sql = f" AND id <> ${len(params)}"
    return await conn.fetchval(
        f"""
        SELECT title FROM {DB_SCHEMA}.employee_tasks
        WHERE emp_id = $1 AND is_active IS TRUE
          AND time_slots && $2::timestamptz[]
          {exclude_sql}
        ORDER BY scheduled_at
        LIMIT 1
        """,
        *params,
    )


@router.post("/create", response_model=TaskOut, status_code=201, summary="Create a task")
async def create_task(
    payload: TaskCreateIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(emp_id)

    slots = sorted(_as_aware(s) for s in payload.time_slots)
    scheduled_at = slots[0]  # earliest booked slot

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        conflict = await _find_conflict(conn, emp_id, slots, None)
        if conflict:
            raise HTTPException(status_code=409, detail=f"That time overlaps an existing task: “{conflict}”.")
        row = await conn.fetchrow(
            f"""
            INSERT INTO {DB_SCHEMA}.employee_tasks
                (emp_id, title, description, scheduled_at, time_slots, status, followup_at, followup_note)
            VALUES ($1, $2, $3, $4, $5, COALESCE($6, 'PENDING'), $7, $8)
            RETURNING {_COLUMNS}
            """,
            emp_id,
            payload.title,
            payload.description,
            scheduled_at,
            slots,
            payload.status,
            _as_aware(payload.followup_at),
            payload.followup_note,
        )

    logger.info("employee_task_created id=%s emp_id=%s slots=%s", row["id"], emp_id, len(slots))
    return TaskOut(**dict(row))


@router.get("/list", response_model=TaskListOut, summary="List my tasks for a day")
async def list_tasks(
    date: Optional[str] = Query(None, description="IST day as YYYY-MM-DD; default today"),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(emp_id)

    day = _parse_day(date)
    start, end = _ist_day_bounds(day)

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_COLUMNS} FROM {DB_SCHEMA}.employee_tasks
            WHERE emp_id = $1 AND is_active IS TRUE
              AND scheduled_at >= $2 AND scheduled_at < $3
            ORDER BY scheduled_at ASC, id ASC
            """,
            emp_id, start, end,
        )

    data = [TaskOut(**dict(r)) for r in rows]
    return TaskListOut(data=data, count=len(data), date=day.isoformat())


@router.get("/available-slots", response_model=AvailableSlotsOut, summary="Free 15-min slots for a day")
async def available_slots(
    date: Optional[str] = Query(None, description="IST day as YYYY-MM-DD; default today"),
    exclude_task_id: Optional[int] = Query(None, description="Ignore this task when marking slots (for reschedule)"),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(emp_id)

    day = _parse_day(date)
    day_start, day_end = _ist_day_bounds(day)

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        tasks = await conn.fetch(
            f"""
            SELECT id, title, time_slots FROM {DB_SCHEMA}.employee_tasks
            WHERE emp_id = $1 AND is_active IS TRUE
              AND scheduled_at >= $2 AND scheduled_at < $3
              AND ($4::bigint IS NULL OR id <> $4)
            """,
            emp_id, day_start, day_end, exclude_task_id,
        )

    # A slot is taken if it is one of the start-times blocked by an active task.
    # Key by the exact instant (UTC) so it matches the grid boundaries below.
    busy = {}
    for t in tasks:
        for slot in t["time_slots"]:
            busy.setdefault(slot.astimezone(timezone.utc), t["title"])

    slots = []
    for i in range(_SLOTS_PER_DAY):
        s_start = day_start + timedelta(minutes=TASK_SLOT_MINUTES * i)
        conflict_title = busy.get(s_start.astimezone(timezone.utc))
        slots.append({
            "time": s_start.strftime("%H:%M"),
            "iso": s_start.astimezone(timezone.utc).isoformat(),
            "available": conflict_title is None,
            "conflict_title": conflict_title,
        })

    return AvailableSlotsOut(date=day.isoformat(), slot_minutes=TASK_SLOT_MINUTES, slots=slots)


@router.patch("/{task_id}", response_model=TaskOut, summary="Edit / reschedule a task")
async def patch_task(
    task_id: int,
    payload: TaskPatchIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(emp_id)

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        _raise_validation({"_": "Nothing to update."})

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            f"SELECT scheduled_at FROM {DB_SCHEMA}.employee_tasks "
            f"WHERE id = $1 AND emp_id = $2 AND is_active IS TRUE",
            task_id, emp_id,
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Task not found.")

        # If the booked slots change, re-check for an overlap (excluding self).
        new_slots = None
        if "time_slots" in fields:
            new_slots = sorted(_as_aware(s) for s in fields["time_slots"])
            conflict = await _find_conflict(conn, emp_id, new_slots, task_id)
            if conflict:
                raise HTTPException(status_code=409, detail=f"That time overlaps an existing task: “{conflict}”.")

        sets = ["updated_at = now()"]
        vals: List = []
        i = 1
        for col in ("title", "description", "status", "followup_note"):
            if col in fields:
                sets.append(f"{col} = ${i}")
                vals.append(fields[col])
                i += 1
        if new_slots is not None:
            sets.append(f"time_slots = ${i}")
            vals.append(new_slots)
            i += 1
            sets.append(f"scheduled_at = ${i}")
            vals.append(new_slots[0])
            i += 1
        if "followup_at" in fields:
            sets.append(f"followup_at = ${i}")
            vals.append(_as_aware(fields["followup_at"]))
            i += 1

        vals.append(task_id)
        row = await conn.fetchrow(
            f"UPDATE {DB_SCHEMA}.employee_tasks SET {', '.join(sets)} WHERE id = ${i} RETURNING {_COLUMNS}",
            *vals,
        )

    logger.info("employee_task_updated id=%s emp_id=%s", task_id, emp_id)
    return TaskOut(**dict(row))


@router.delete("/{task_id}", summary="Delete (soft) a task")
async def delete_task(
    task_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(emp_id)

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        updated = await conn.execute(
            f"UPDATE {DB_SCHEMA}.employee_tasks SET is_active = FALSE, updated_at = now() "
            f"WHERE id = $1 AND emp_id = $2 AND is_active IS TRUE",
            task_id, emp_id,
        )
    if updated.endswith("0"):
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"deleted": True, "id": task_id}
