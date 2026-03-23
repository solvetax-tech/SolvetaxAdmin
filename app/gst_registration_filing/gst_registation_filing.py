import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from datetime import datetime
from app.gst_registration_filing.schemas import GSTFilingIn, GSTFilingEditIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_gst_filing_visibility
from app.security.rbac import require_permission
from app.logger import logger
from zoneinfo import ZoneInfo
import json
import uuid
from datetime import datetime
import re

router = APIRouter(
    prefix="/api/v1/gst-filings",
    tags=["GST Filings"]
)


# -------------------------------------------------------------------
# FILTER GST FILINGS (ENTERPRISE PRODUCTION READY)
# -------------------------------------------------------------------
@router.get(
    "/gst-filings/filter",
    summary="Filter GST Filings",
)
async def filter_gst_filings(

    # PRIMARY
    id: Optional[int] = None,
    customer_id: Optional[int] = None,
    gst_registration_id: Optional[int] = None,
    gstin: Optional[str] = None,

    # SERVICE / TYPE
    service_id: Optional[int] = None,
    filing_type: Optional[str] = None,
    filing_category: Optional[str] = None,
    filing_period: Optional[str] = None,

    # STATUS
    status: Optional[str] = None,
    statuses: Optional[List[str]] = Query(None),

    # USERS
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,

    # DATE FILTERS
    due_from: Optional[datetime] = None,
    due_to: Optional[datetime] = None,

    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,

    # FLAGS
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),

    is_overdue: Optional[bool] = None,
    is_upcoming: Optional[bool] = None,

    # ✅ NEW FLAGS
    is_auto_enabled: Optional[bool] = None,
    is_auto_generated: Optional[bool] = None,

    # PAGINATION
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),

    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "filter_gst_filings"},
    )

    log.info("Incoming GST filings filter | limit=%s offset=%s", limit, offset)

    # --------------------------------------------------
    # DATE VALIDATION (ADDED)
    # --------------------------------------------------
    if due_from and due_to and due_from > due_to:
        raise HTTPException(400, "due_from cannot be greater than due_to")

    if created_from and created_to and created_from > created_to:
        raise HTTPException(400, "created_from cannot be greater than created_to")

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, "Database connection error")

    try:
        conditions = []
        values = []
        idx = 1

        # ----------------------------
        # BASIC FILTERS
        # ----------------------------

        if id:
            conditions.append(f"f.id = ${idx}")
            values.append(id)
            idx += 1

        if customer_id:
            conditions.append(f"f.customer_id = ${idx}")
            values.append(customer_id)
            idx += 1

        if gst_registration_id:
            conditions.append(f"f.gst_registration_id = ${idx}")
            values.append(gst_registration_id)
            idx += 1

        if gstin and gstin.strip():
            conditions.append(f"upper(f.gstin) = ${idx}")
            values.append(gstin.strip().upper())
            idx += 1

        if service_id:
            conditions.append(f"f.service_id = ${idx}")
            values.append(service_id)
            idx += 1

        if filing_type and filing_type.strip():
            conditions.append(f"f.filing_type = ${idx}")
            values.append(filing_type.strip().upper())
            idx += 1

        if filing_category and filing_category.strip():
            conditions.append(f"f.filing_category = ${idx}")
            values.append(filing_category.strip().upper())
            idx += 1

        if filing_period and filing_period.strip():
            conditions.append(f"f.filing_period = ${idx}")
            values.append(filing_period.strip().upper())
            idx += 1

        # ----------------------------
        # STATUS
        # ----------------------------

        if status:
            conditions.append(f"f.status = ${idx}")
            values.append(status.upper())
            idx += 1

        if statuses:
            conditions.append(f"f.status = ANY(${idx})")
            values.append([s.upper() for s in statuses])
            idx += 1

        # ----------------------------
        # USERS
        # ----------------------------

        if rm_id:
            conditions.append(f"f.rm_id = ${idx}")
            values.append(rm_id)
            idx += 1

        if op_id:
            conditions.append(f"f.op_id = ${idx}")
            values.append(op_id)
            idx += 1

        # ----------------------------
        # DATE FILTERS
        # ----------------------------

        if due_from:
            conditions.append(f"f.due_date >= ${idx}")
            values.append(due_from)
            idx += 1

        if due_to:
            conditions.append(f"f.due_date <= ${idx}")
            values.append(due_to)
            idx += 1

        if created_from:
            conditions.append(f"f.created_at >= ${idx}")
            values.append(created_from)
            idx += 1

        if created_to:
            conditions.append(f"f.created_at <= ${idx}")
            values.append(created_to)
            idx += 1

        # ----------------------------
        # FLAGS
        # ----------------------------

        if is_active is not None:
            conditions.append(f"f.is_active = ${idx}")
            values.append(is_active)
            idx += 1
        elif not include_inactive:
            conditions.append("f.is_active = TRUE")

        if is_overdue:
            conditions.append("(f.status != 'FILED' AND f.due_date < NOW())")

        if is_upcoming:
            conditions.append("(f.status = 'PENDING' AND f.due_date >= NOW())")

        # ✅ NEW FLAGS FILTER
        if is_auto_enabled is not None:
            conditions.append(f"f.is_auto_enabled = ${idx}")
            values.append(is_auto_enabled)
            idx += 1

        if is_auto_generated is not None:
            conditions.append(f"f.is_auto_generated = ${idx}")
            values.append(is_auto_generated)
            idx += 1

        # ----------------------------
        # VISIBILITY
        # ----------------------------

        visibility_sql, visibility_values, idx = build_gst_filing_visibility(
            role, emp_id, idx, DB_SCHEMA
        )

        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        # ----------------------------
        # QUERY BUILD
        # ----------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.gst_filings f
            {where_clause}
        """

        data_sql = f"""
            SELECT f.*,
                   rm.first_name AS rm_name,
                   op.first_name AS op_name
            FROM {DB_SCHEMA}.gst_filings f
            LEFT JOIN {DB_SCHEMA}.employees rm
                ON rm.emp_id = f.rm_id
            LEFT JOIN {DB_SCHEMA}.employees op
                ON op.emp_id = f.op_id
            {where_clause}
            ORDER BY f.due_date ASC, f.id DESC
            LIMIT ${idx} OFFSET ${idx+1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:
            total = await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(data_sql, *values_with_pagination)

        log.info("GST filings filter success | returned=%s total=%s", len(rows), total)

        return {
            "data": [dict(r) for r in rows],
            "count": total,
            "limit": limit,          # ✅ ADDED
            "offset": offset,        # ✅ ADDED
            "request_id": request_id # ✅ ADDED
        }

    except Exception:
        log.exception("Error filtering GST filings")
        raise HTTPException(500, "Internal server error")
# -------------------------------------------------------------------
# CREATE GST FILING + SERVICE (FINAL PRODUCTION)
# -------------------------------------------------------------------
@router.post(
    "/gst-filings",
    status_code=status.HTTP_201_CREATED,
    summary="Create GST Filing",
)
async def create_gst_filing(
    payload: GSTFilingIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    # Normalize
    filing_type = payload.filing_type.upper()
    filing_category = payload.filing_category.upper() if payload.filing_category else None
    filing_period = payload.filing_period.upper()
    status = payload.status.upper()

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB connection failed")
        raise HTTPException(500, "Database connection error")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # ---------------- CUSTOMER VALIDATION ----------------
                customer = await conn.fetchrow(
                    f"""
                    SELECT customer_id, is_active
                    FROM {DB_SCHEMA}.customers
                    WHERE customer_id = $1
                    """,
                    payload.customer_id,
                )

                if not customer:
                    raise HTTPException(400, "Customer not found")

                if not customer["is_active"]:
                    raise HTTPException(400, "Customer inactive")

                # ---------------- GST VALIDATION (ADDED) ----------------
                if payload.gst_registration_id:
                    gst = await conn.fetchrow(
                        f"""
                        SELECT id, gstin, is_active
                        FROM {DB_SCHEMA}.gst_registration
                        WHERE id = $1
                        """,
                        payload.gst_registration_id,
                    )

                    if not gst:
                        raise HTTPException(400, "Invalid GST registration")

                    if not gst["is_active"]:
                        raise HTTPException(400, "GST registration inactive")

                # ---------------- DUPLICATE CHECK ----------------
                duplicate = await conn.fetchval(
                    f"""
                    SELECT 1
                    FROM {DB_SCHEMA}.gst_filings
                    WHERE gst_registration_id IS NOT DISTINCT FROM $1
                      AND gstin IS NOT DISTINCT FROM $2
                      AND filing_type = $3
                      AND filing_period = $4
                      AND is_active = TRUE
                    """,
                    payload.gst_registration_id,
                    payload.gstin,
                    filing_type,
                    filing_period,
                )

                if duplicate:
                    raise HTTPException(409, "Filing already exists")

                # ---------------- INSERT GST FILING ----------------
                filing_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.gst_filings (
                        customer_id,
                        gst_registration_id,
                        gstin,
                        filing_type,
                        filing_category,
                        filing_period,
                        due_date,
                        status,
                        service_id,
                        priority,
                        remarks,
                        rm_id,
                        op_id,
                        is_auto_generated,
                        is_auto_enabled,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                        $11,$12,$13,$14,$15,$16,$17
                    )
                    RETURNING *
                    """,
                    payload.customer_id,
                    payload.gst_registration_id,
                    payload.gstin,
                    filing_type,
                    filing_category,
                    filing_period,
                    payload.due_date,
                    status,
                    payload.service_id,
                    payload.priority,
                    payload.remarks,
                    payload.rm_id or emp_id,
                    payload.op_id,
                    False,  # SYSTEM CONTROLLED
                    payload.is_auto_enabled,
                    now,
                    now,
                )

                # ---------------- CUSTOMER SERVICE ----------------
                service_row = None
                if payload.service_id:
                    service_row = await conn.fetchrow(
                        f"""
                        INSERT INTO {DB_SCHEMA}.customer_services (
                            customer_id,
                            service_id,
                            service_status,
                            rm_id,
                            op_id,
                            entity_type,
                            entity_id,
                            created_at
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                        RETURNING *
                        """,
                        payload.customer_id,
                        payload.service_id,
                        "PENDING",
                        payload.rm_id or emp_id,
                        payload.op_id,
                        "GST_FILING",
                        filing_row["id"],
                        now,
                    )

                # ---------------- VERSION ----------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions (
                        emp_id, entity_type, entity_id,
                        customer_id, action,
                        json, created_at
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "GST_FILING",
                    filing_row["id"],
                    payload.customer_id,
                    "CREATE",
                    json.dumps(dict(filing_row), default=str),
                    now,
                )

                return {
                    "data": {
                        "filing": dict(filing_row),
                        "service": dict(service_row) if service_row else None,
                    },
                    "message": "GST filing created successfully",
                    "request_id": request_id,
                }

        except asyncpg.exceptions.UniqueViolationError:
            raise HTTPException(409, "Duplicate filing")

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Invalid reference")

        except HTTPException:
            raise

        except Exception:
            log.exception("Create GST filing failed")
            raise HTTPException(500, "Internal server error")

# -------------------------------------------------------------------
# UPDATE GST FILING (FINAL)
# -------------------------------------------------------------------
@router.patch("/gst-filings/{filing_id}")
async def update_gst_filing(
    filing_id: int,
    payload: GSTFilingEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()

    emp_id = int(current_user.get("emp_id") or current_user.get("sub") or 0)

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    try:
        pool = await get_db_pool()
    except Exception:
        raise HTTPException(500, "Database connection error")

    async with pool.acquire() as conn:
        async with conn.transaction():

            old = await conn.fetchrow(
                f"SELECT * FROM {DB_SCHEMA}.gst_filings WHERE id=$1 FOR UPDATE",
                filing_id,
            )

            if not old:
                raise HTTPException(404, "GST filing not found")

            update_data = payload.model_dump(exclude_unset=True)

            if not update_data:
                raise HTTPException(400, "No fields to update")

            # Normalize
            if "filing_type" in update_data:
                update_data["filing_type"] = update_data["filing_type"].upper()

            if "filing_category" in update_data and update_data["filing_category"]:
                update_data["filing_category"] = update_data["filing_category"].upper()

            if "filing_period" in update_data:
                update_data["filing_period"] = update_data["filing_period"].upper()

            if "status" in update_data:
                update_data["status"] = update_data["status"].upper()

            # STATUS TRANSITION
            VALID = {
                "PENDING": ["FILED", "FAILED"],
                "IN_PROGRESS": ["FILED", "FAILED"],
                "FILED": [],
            }

            if "status" in update_data:
                if update_data["status"] not in VALID.get(old["status"], []):
                    raise HTTPException(400, "Invalid status transition")

                if update_data["status"] == "FILED":
                    update_data["filed_at"] = now

            # GST SAFETY
            new_reg = update_data.get("gst_registration_id", old["gst_registration_id"])
            new_gstin = update_data.get("gstin", old["gstin"])

            if not new_reg and not new_gstin:
                raise HTTPException(400, "GST reference required")

            # BUILD QUERY
            fields, values, idx = [], [], 1
            for k, v in update_data.items():
                fields.append(f"{k}=${idx}")
                values.append(v)
                idx += 1

            fields.append(f"updated_at=${idx}")
            values.append(now)
            idx += 1

            values.append(filing_id)

            new = await conn.fetchrow(
                f"""
                UPDATE {DB_SCHEMA}.gst_filings
                SET {', '.join(fields)}
                WHERE id=${idx}
                RETURNING *
                """,
                *values,
            )

            # VERSION
            await conn.execute(
                f"""
                INSERT INTO {DB_SCHEMA}.versions
                (emp_id, entity_type, entity_id, customer_id, action, json, updated_json, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                emp_id,
                "GST_FILING",
                filing_id,
                new["customer_id"],
                "UPDATE",
                json.dumps(dict(old), default=str),
                json.dumps(dict(new), default=str),
                now,
            )

            return {
                "data": dict(new),
                "message": "Updated successfully",
                "request_id": request_id,
            }
@router.delete(
    "/{gst_id}/soft_delete",
    summary="Soft delete GST registration (Enterprise + Cascade + Auto Filing Sync + Audit)",
)
async def soft_delete_gst_registration(
    gst_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB pool error")
        raise HTTPException(500, "Database connection error")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # 1️⃣ LOCK GST
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.gst_registration
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    gst_id,
                )

                if not gst_row:
                    raise HTTPException(404, "GST not found")

                if not gst_row["is_active"]:
                    raise HTTPException(400, "Already inactive")

                # 2️⃣ DEACTIVATE GST
                deleted_gst = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                    SET is_active = FALSE,
                        updated_at = NOW()
                    WHERE id = $1
                    RETURNING *
                    """,
                    gst_id,
                )

                # 3️⃣ CASCADE PERSONS
                deleted_persons = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_persons
                    SET is_active = FALSE,
                        updated_at = NOW()
                    WHERE gst_registration_id = $1
                    RETURNING person_id
                    """,
                    gst_id,
                )

                # 4️⃣ CASCADE DOCUMENTS
                deleted_documents = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents d
                    SET is_active = FALSE,
                        updated_at = NOW()
                    FROM {DB_SCHEMA}.gst_registration_persons p
                    WHERE d.person_id = p.person_id
                      AND p.gst_registration_id = $1
                    RETURNING d.document_id
                    """,
                    gst_id,
                )

                # 🔥 5️⃣ DISABLE AUTO FILINGS (NEW)
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings
                    SET is_auto_enabled = FALSE,
                        updated_at = NOW()
                    WHERE gst_registration_id = $1
                    """,
                    gst_id,
                )

                # 6️⃣ VERSION
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action)
                    VALUES ($1,$2,$3,$4,$5)
                    """,
                    emp_id,
                    "GST_REGISTRATION",
                    gst_id,
                    gst_row["customer_id"],
                    "DELETE",
                )

            return {
                "data": dict(deleted_gst),
                "persons_deactivated": len(deleted_persons),
                "documents_deactivated": len(deleted_documents),
                "auto_filings_disabled": True,
                "message": "GST deactivated successfully",
                "request_id": request_id,
            }

        except Exception:
            log.exception("Delete failed")
            raise HTTPException(500, "Internal server error")

@router.post(
    "/{gst_id}/activate",
    summary="Activate GST (Enterprise + Cascade + Auto Filing Sync)",
)
async def activate_gst_registration(
    gst_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()
    emp_id = int(current_user.get("emp_id") or current_user.get("sub") or 0)

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("DB pool error")
        raise HTTPException(500, "Database connection error")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # 1️⃣ LOCK + VALIDATE
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT g.*, c.is_active AS customer_active
                    FROM {DB_SCHEMA}.gst_registration g
                    JOIN {DB_SCHEMA}.customers c
                      ON g.customer_id = c.customer_id
                    WHERE g.id = $1
                    FOR UPDATE
                    """,
                    gst_id,
                )

                if not gst_row:
                    raise HTTPException(404, "GST not found")

                if gst_row["is_active"]:
                    raise HTTPException(400, "Already active")

                if not gst_row["customer_active"]:
                    raise HTTPException(400, "Customer inactive")

                # 2️⃣ ACTIVATE GST
                activated_gst = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                    SET is_active = TRUE,
                        updated_at = NOW()
                    WHERE id = $1
                    RETURNING *
                    """,
                    gst_id,
                )

                # 3️⃣ CASCADE PERSONS
                activated_persons = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_persons
                    SET is_active = TRUE,
                        updated_at = NOW()
                    WHERE gst_registration_id = $1
                    RETURNING person_id
                    """,
                    gst_id,
                )

                # 4️⃣ CASCADE DOCUMENTS
                activated_documents = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents d
                    SET is_active = TRUE,
                        updated_at = NOW()
                    FROM {DB_SCHEMA}.gst_registration_persons p
                    WHERE d.person_id = p.person_id
                      AND p.gst_registration_id = $1
                    RETURNING d.document_id
                    """,
                    gst_id,
                )

                # 🔥 5️⃣ ENABLE AUTO FILINGS (NEW)
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_filings
                    SET is_auto_enabled = TRUE,
                        updated_at = NOW()
                    WHERE gst_registration_id = $1
                    """,
                    gst_id,
                )

                # 6️⃣ VERSION
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action)
                    VALUES ($1,$2,$3,$4,$5)
                    """,
                    emp_id,
                    "GST_REGISTRATION",
                    gst_id,
                    gst_row["customer_id"],
                    "ACTIVATE",
                )

            return {
                "data": dict(activated_gst),
                "persons_activated": len(activated_persons),
                "documents_activated": len(activated_documents),
                "auto_filings_enabled": True,
                "message": "GST activated successfully",
                "request_id": request_id,
            }

        except Exception:
            log.exception("Activation failed")
            raise HTTPException(500, "Internal server error")