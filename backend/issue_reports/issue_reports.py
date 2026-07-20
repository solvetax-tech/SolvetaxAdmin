"""In-app issue / bug reporting API.

Staff raise issues with a priority + optional photos. Visibility:
  ADMIN     -> every row
  MANAGER   -> own rows + rows raised by their direct reports
               (employees.manager_emp_id = caller's emp_id)
  EMPLOYEE  -> only their own rows

Photos are uploaded (multipart) to Azure Blob via POST /photo/upload, which
returns a blob URL the client sends back in `photo_urls` on create. Reading a
photo goes through GET /photo/view, which mints a short-lived read-SAS.
"""

import logging
from typing import List, Optional

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from backend.common.status_constants import ISSUE_PRIORITIES, ISSUE_STATUSES
from backend.issue_reports.schemas import (
    IssueReportCreateIn,
    IssueReportListItemOut,
    IssueReportOut,
    IssueReportPatchIn,
    IssueReportPhotoUploadOut,
)
from backend.logger import logger
from backend.security.rbac import require_permission
from backend.utils import (
    AZURE_STORAGE_CONTAINER,
    DB_SCHEMA,
    extract_blob_path,
    generate_blob_sas_url,
    generate_uuid,
    get_blob_service_client,
    get_db_pool,
)

router = APIRouter(
    prefix="/api/v1/issue-reports",
    tags=["Issue Reports"],
)

# Photos land here so the (gst-documents-scoped) read-SAS helper can sign them.
_PHOTO_FOLDER = "issue-photos"
_ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
_MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB


def _ctx(user: dict):
    role = (user.get("role") or "").strip().upper()
    raw = user.get("emp_id") or user.get("sub")
    emp_id = int(raw) if str(raw).isdigit() else 0
    return role, emp_id


def _require_emp(role: str, emp_id: int) -> None:
    if role == "ADMIN":
        return
    if emp_id <= 0:
        raise HTTPException(status_code=403, detail="Employee context required.")


def _raise_validation(fields: dict, message: str = "Validation failed", code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"error": {"type": "validation_error", "message": message, "fields": fields}},
    )


def _visibility_sql(role: str, emp_id: int, idx: int):
    """WHERE fragment + params scoping rows to what this caller may see.

    ADMIN -> no restriction. Everyone else -> own rows OR rows from their direct
    reports; the same $idx is referenced twice so it stays one bound param.
    """
    if role == "ADMIN":
        return "", [], idx
    sql = (
        f"(ir.reporter_emp_id = ${idx} OR ir.reporter_emp_id IN ("
        f"SELECT emp_id FROM {DB_SCHEMA}.employees WHERE manager_emp_id = ${idx}))"
    )
    return sql, [emp_id], idx + 1


async def _can_see(conn, role: str, emp_id: int, reporter_emp_id: int) -> bool:
    if role == "ADMIN":
        return True
    if reporter_emp_id == emp_id:
        return True
    # Is the caller the reporter's direct manager?
    return bool(
        await conn.fetchval(
            f"SELECT 1 FROM {DB_SCHEMA}.employees WHERE emp_id = $1 AND manager_emp_id = $2",
            reporter_emp_id,
            emp_id,
        )
    )


# Bare names for INSERT/UPDATE ... RETURNING (the modified table has no alias there).
_RETURNING_COLUMNS = """
    id, reporter_emp_id, title, description, priority, status,
    photo_urls, resolved_by_emp_id, resolved_at, resolution_note,
    is_active, created_at, updated_at
"""

# ir.-qualified for the list SELECT, which joins employees (shared column names
# like created_at / is_active would otherwise be ambiguous).
_LIST_COLUMNS = """
    ir.id, ir.reporter_emp_id, ir.title, ir.description, ir.priority, ir.status,
    ir.photo_urls, ir.resolved_by_emp_id, ir.resolved_at, ir.resolution_note,
    ir.is_active, ir.created_at, ir.updated_at
"""


@router.post("/create", response_model=IssueReportOut, status_code=201, summary="Raise an issue")
async def create_issue_report(
    payload: IssueReportCreateIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)
    if emp_id <= 0:
        _raise_validation({"reporter": "Could not resolve your employee id from the session."})

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                f"""
                INSERT INTO {DB_SCHEMA}.issue_reports
                    (reporter_emp_id, title, description, priority, photo_urls)
                VALUES ($1, $2, $3, COALESCE($4, 'MEDIUM'), $5)
                RETURNING {_RETURNING_COLUMNS}
                """,
                emp_id,
                payload.title,
                payload.description,
                payload.priority,
                payload.photo_urls,
            )
        except asyncpg.ForeignKeyViolationError:
            _raise_validation({"reporter": "Your employee record no longer exists."})

    logger.info("issue_report_created id=%s by emp_id=%s priority=%s", row["id"], emp_id, row["priority"])
    return IssueReportOut(**dict(row))


@router.get("/list", summary="List issues (scoped by role)")
async def list_issue_reports(
    status: Optional[str] = Query(None, description="Filter by status (OPEN/IN_PROGRESS/RESOLVED)"),
    priority: Optional[str] = Query(None, description="Filter by priority (LOW/MEDIUM/HIGH/URGENT)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)

    conditions = ["ir.is_active IS TRUE"]
    values: List = []
    idx = 1

    vis_sql, vis_params, idx = _visibility_sql(role, emp_id, idx)
    if vis_sql:
        conditions.append(vis_sql)
        values.extend(vis_params)

    if status:
        s = status.strip().upper()
        if s not in ISSUE_STATUSES:
            _raise_validation({"status": f"Unknown status. Allowed: {', '.join(ISSUE_STATUSES)}."})
        conditions.append(f"ir.status = ${idx}")
        values.append(s)
        idx += 1

    if priority:
        p = priority.strip().upper()
        if p not in ISSUE_PRIORITIES:
            _raise_validation({"priority": f"Unknown priority. Allowed: {', '.join(ISSUE_PRIORITIES)}."})
        conditions.append(f"ir.priority = ${idx}")
        values.append(p)
        idx += 1

    where_clause = " AND ".join(conditions)

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT count(*) FROM {DB_SCHEMA}.issue_reports ir WHERE {where_clause}",
            *values,
        )
        rows = await conn.fetch(
            f"""
            SELECT {_LIST_COLUMNS},
                   NULLIF(btrim(concat_ws(' ', er.first_name, er.last_name)), '') AS reporter_name,
                   er.username AS reporter_username,
                   NULLIF(btrim(concat_ws(' ', erb.first_name, erb.last_name)), '') AS resolved_by_name
            FROM {DB_SCHEMA}.issue_reports ir
            LEFT JOIN {DB_SCHEMA}.employees er  ON er.emp_id  = ir.reporter_emp_id
            LEFT JOIN {DB_SCHEMA}.employees erb ON erb.emp_id = ir.resolved_by_emp_id
            WHERE {where_clause}
            ORDER BY ir.created_at DESC, ir.id DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *values,
            limit,
            offset,
        )

    data = [IssueReportListItemOut(**dict(r)).model_dump() for r in rows]
    return {"data": data, "count": len(data), "total": total or 0, "limit": limit, "offset": offset}


@router.patch("/{issue_id}", response_model=IssueReportOut, summary="Update / resolve an issue")
async def patch_issue_report(
    issue_id: int,
    payload: IssueReportPatchIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)

    if payload.status is None and payload.priority is None and payload.resolution_note is None:
        _raise_validation({"_": "Nothing to update."})

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            f"SELECT reporter_emp_id FROM {DB_SCHEMA}.issue_reports WHERE id = $1 AND is_active IS TRUE",
            issue_id,
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Issue not found.")
        if not await _can_see(conn, role, emp_id, existing["reporter_emp_id"]):
            # Hide existence from callers who can't see it.
            raise HTTPException(status_code=404, detail="Issue not found.")

        sets = ["updated_at = now()"]
        vals: List = []
        i = 1

        if payload.priority is not None:
            sets.append(f"priority = ${i}")
            vals.append(payload.priority)
            i += 1
        if payload.resolution_note is not None:
            sets.append(f"resolution_note = ${i}")
            vals.append(payload.resolution_note)
            i += 1
        if payload.status is not None:
            sets.append(f"status = ${i}")
            vals.append(payload.status)
            i += 1
            if payload.status == "RESOLVED":
                sets.append(f"resolved_by_emp_id = ${i}")
                vals.append(emp_id)
                i += 1
                sets.append("resolved_at = now()")
            else:
                # Reopened -> clear the resolution trail.
                sets.append("resolved_by_emp_id = NULL")
                sets.append("resolved_at = NULL")

        vals.append(issue_id)
        row = await conn.fetchrow(
            f"UPDATE {DB_SCHEMA}.issue_reports SET {', '.join(sets)} WHERE id = ${i} "
            f"RETURNING {_RETURNING_COLUMNS}",
            *vals,
        )

    logger.info("issue_report_updated id=%s by emp_id=%s status=%s", issue_id, emp_id, row["status"])
    return IssueReportOut(**dict(row))


@router.post("/photo/upload", response_model=IssueReportPhotoUploadOut, status_code=201, summary="Upload an issue photo")
async def upload_issue_photo(
    file: UploadFile = File(...),
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)

    if not AZURE_STORAGE_CONTAINER:
        raise HTTPException(status_code=503, detail="Blob storage is not configured.")
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported type. Allowed: {', '.join(_ALLOWED_IMAGE_TYPES)}.",
        )
    contents = await file.read()
    if len(contents) > _MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds the 10MB limit.")
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file.")

    try:
        blob_service_client = get_blob_service_client()
        blob_path = f"{_PHOTO_FOLDER}/{generate_uuid()}_{file.filename or 'photo'}"
        blob_client = blob_service_client.get_blob_client(container=AZURE_STORAGE_CONTAINER, blob=blob_path)
        blob_client.upload_blob(contents, overwrite=True)
        blob_url = blob_client.url
    except Exception:
        logger.exception("issue photo blob upload failed (emp_id=%s)", emp_id)
        raise HTTPException(status_code=500, detail="Photo upload failed.")

    return IssueReportPhotoUploadOut(blob_url=blob_url, filename=file.filename)


@router.get("/photo/view", summary="Mint a short-lived read URL for an issue photo")
async def view_issue_photo(
    blob_url: str = Query(..., description="The stored blob URL of the photo"),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    role, emp_id = _ctx(current_user)
    _require_emp(role, emp_id)

    blob_path = extract_blob_path(blob_url)
    # Only ever sign issue photos through this endpoint, never arbitrary blobs.
    if not blob_path.startswith(f"{_PHOTO_FOLDER}/"):
        raise HTTPException(status_code=400, detail="Not an issue photo.")
    try:
        url = generate_blob_sas_url(blob_path, disposition="inline")
    except Exception:
        logger.exception("issue photo SAS mint failed")
        raise HTTPException(status_code=500, detail="Could not generate view URL.")
    return {"url": url}
