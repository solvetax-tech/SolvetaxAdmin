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
    TaskPageOut,
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


def _norm_status(status: Optional[str]) -> Optional[str]:
    """Validate an optional status filter. Empty / 'ALL' -> no filter (None)."""
    if not status:
        return None
    s = status.strip().upper()
    if s in ("", "ALL"):
        return None
    if s not in TASK_STATUSES:
        _raise_validation({"status": f"status must be one of {list(TASK_STATUSES)} or ALL."})
    return s


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


def _date_today_ist() -> date_cls:
    """Return today's IST date.

    Extracted as a named function so tests can patch it without touching the
    stdlib datetime class.
    """
    return datetime.now(IST).date()


async def create_task_for_emp(
    conn,
    emp_id: int,
    title: str,
    description: Optional[str] = None,
    scheduled_at: Optional[datetime] = None,
) -> int:
    """Create a system-generated employee task; return its id.

    Called by the workflow engine's AssignTask node handler (doc 09 §3.3).
    Satisfies employee_tasks NOT NULL columns with a synthetic single slot:
      - scheduled_at  = provided value, or next business day 10:00 IST
      - time_slots    = [scheduled_at]
      - status        = 'PENDING'

    The human-calendar overlap-conflict check (_find_conflict) is
    intentionally SKIPPED for system-generated tasks.  System tasks are
    nudges / follow-up reminders, not calendar bookings; they must not be
    silently dropped because an employee happens to have that slot taken.
    """
    if scheduled_at is None:
        today = _date_today_ist()
        next_day = today + timedelta(days=1)
        # Skip Saturday (weekday 5) and Sunday (weekday 6)
        while next_day.weekday() in (5, 6):
            next_day += timedelta(days=1)
        scheduled_at = datetime.combine(next_day, time_cls(10, 0), tzinfo=IST)

    time_slots = [scheduled_at]
    task_id = await conn.fetchval(
        f"""
        INSERT INTO {DB_SCHEMA}.employee_tasks
            (emp_id, title, description, scheduled_at, time_slots, status)
        VALUES ($1, $2, $3, $4, $5, 'PENDING')
        RETURNING id
        """,
        emp_id,
        title,
        description,
        scheduled_at,
        time_slots,
    )
    logger.info(
        "system_task_created id=%s emp_id=%s scheduled_at=%s",
        task_id,
        emp_id,
        scheduled_at.isoformat(),
    )
    return task_id


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
    status: Optional[str] = Query(None, description="Filter by status; omit or ALL for any"),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(emp_id)

    day = _parse_day(date)
    start, end = _ist_day_bounds(day)
    st = _norm_status(status)

    params = [emp_id, start, end]
    status_sql = ""
    if st:
        params.append(st)
        status_sql = f" AND status = ${len(params)}"

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_COLUMNS} FROM {DB_SCHEMA}.employee_tasks
            WHERE emp_id = $1 AND is_active IS TRUE
              AND scheduled_at >= $2 AND scheduled_at < $3
              {status_sql}
            ORDER BY scheduled_at ASC, id ASC
            """,
            *params,
        )

    data = [TaskOut(**dict(r)) for r in rows]
    return TaskListOut(data=data, count=len(data), date=day.isoformat())


@router.get("/all", response_model=TaskPageOut, summary="List all my tasks (paginated)")
async def all_tasks(
    status: Optional[str] = Query(None, description="Filter by status; omit or ALL for any"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(emp_id)

    st = _norm_status(status)
    params = [emp_id]
    status_sql = ""
    if st:
        params.append(st)
        status_sql = f" AND status = ${len(params)}"

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT count(*) FROM {DB_SCHEMA}.employee_tasks "
            f"WHERE emp_id = $1 AND is_active IS TRUE {status_sql}",
            *params,
        )
        row_params = list(params)
        row_params.append(limit)
        limit_pos = len(row_params)
        row_params.append(offset)
        offset_pos = len(row_params)
        rows = await conn.fetch(
            f"""
            SELECT {_COLUMNS} FROM {DB_SCHEMA}.employee_tasks
            WHERE emp_id = $1 AND is_active IS TRUE {status_sql}
            ORDER BY scheduled_at DESC, id DESC
            LIMIT ${limit_pos} OFFSET ${offset_pos}
            """,
            *row_params,
        )

    data = [TaskOut(**dict(r)) for r in rows]
    return TaskPageOut(data=data, count=len(data), total=total or 0, limit=limit, offset=offset)


# Unfinished carry-over tasks: statuses that still need work.
_OPEN_STATUSES = ["PENDING", "IN_PROGRESS"]


@router.get("/previous", response_model=TaskPageOut, summary="Past unfinished tasks (pending / in-progress)")
async def previous_tasks(
    status: Optional[str] = Query(None, description="PENDING or IN_PROGRESS; omit / ALL for both"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(emp_id)

    # Scheduled before the start of today (IST) and still open. A specific status
    # filter is allowed, but only among the open statuses.
    today_start, _ = _ist_day_bounds(datetime.now(IST).date())
    st = _norm_status(status)
    if st and st not in _OPEN_STATUSES:
        _raise_validation({"status": f"status must be one of {_OPEN_STATUSES} or ALL."})
    statuses = [st] if st else _OPEN_STATUSES

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"""
            SELECT count(*) FROM {DB_SCHEMA}.employee_tasks
            WHERE emp_id = $1 AND is_active IS TRUE
              AND scheduled_at < $2 AND status = ANY($3::text[])
            """,
            emp_id, today_start, statuses,
        )
        rows = await conn.fetch(
            f"""
            SELECT {_COLUMNS} FROM {DB_SCHEMA}.employee_tasks
            WHERE emp_id = $1 AND is_active IS TRUE
              AND scheduled_at < $2 AND status = ANY($3::text[])
            ORDER BY scheduled_at DESC, id DESC
            LIMIT $4 OFFSET $5
            """,
            emp_id, today_start, statuses, limit, offset,
        )

    data = [TaskOut(**dict(r)) for r in rows]
    return TaskPageOut(data=data, count=len(data), total=total or 0, limit=limit, offset=offset)


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
