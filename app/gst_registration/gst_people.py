import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.gst_registration.schemas import (
    RegistrationPersonIn,
    RegistrationPersonEditIn,
)
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.logger import logger
from datetime import datetime
from zoneinfo import ZoneInfo
import json

router = APIRouter(
    prefix="/api/v1/gst-people",
    tags=["GST Registration People"]
)
# -------------------------------------------------------------------
# CREATE REGISTRATION PERSON (Production Standard + Version Audit + IST)
# -------------------------------------------------------------------
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Registration Person",
    responses={
        201: {"description": "Registration person created successfully."},
        400: {"description": "Validation failed or GST not found."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def create_registration_person(
    payload: RegistrationPersonIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Create Registration Person
    --------------------------
    ✔ Atomic transaction (Person + Version)
    ✔ GST must exist & active
    ✔ gst_registration_id is the source of truth
    ✔ GSTIN auto-derived (can be NULL)
    ✔ ownership_category auto-derived from GST
    ✔ One primary per GST enforced by DB
    ✔ PAN/Aadhaar uniqueness scoped per GST
    ✔ Enterprise-grade structured logging
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info(
        "Incoming Registration Person create | gst_registration_id=%s | designation=%s",
        payload.gst_registration_id,
        payload.designation,
    )

    # --------------------------------------------------
    # IST Timestamp
    # --------------------------------------------------
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Validate GST Exists & Active
                # --------------------------------------------------
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT id,
                           customer_id,
                           gstin,
                           ownership_category,
                           is_active
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE id = $1
                     LIMIT 1
                    """,
                    payload.gst_registration_id,
                )

                if not gst_row:
                    raise HTTPException(
                        status_code=400,
                        detail="GST registration not found.",
                    )

                if not gst_row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="GST registration is inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Derive Values From GST (Source of Truth)
                # --------------------------------------------------
                derived_customer_id = gst_row["customer_id"]
                derived_gstin = gst_row["gstin"]          # Can be NULL ✅
                derived_ownership = gst_row["ownership_category"]

                # --------------------------------------------------
                # 3️⃣ Insert Registration Person
                # --------------------------------------------------
                person_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.registration_persons (
                        customer_id,
                        gstin,
                        full_name,
                        designation,
                        pan,
                        aadhaar,
                        email,
                        mobile,
                        is_primary_customer,
                        is_active,
                        created_at,
                        updated_at,
                        ownership_category,
                        gst_registration_id
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,TRUE,$10,$11,$12,$13
                    )
                    RETURNING *
                    """,
                    derived_customer_id,
                    derived_gstin,                     # NULL allowed
                    payload.full_name,
                    payload.designation,
                    payload.pan,
                    payload.aadhaar,
                    payload.email,
                    payload.mobile,
                    payload.is_primary_customer,
                    now,
                    now,
                    derived_ownership,                 # Auto-filled
                    payload.gst_registration_id,
                )

                if not person_row:
                    raise HTTPException(
                        status_code=500,
                        detail="Registration person creation failed.",
                    )

                # --------------------------------------------------
                # 4️⃣ Version Audit Insert
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "REGISTRATION_PERSON",
                    person_row["person_id"],
                    derived_customer_id,
                    "CREATE",
                    json.dumps(dict(person_row), default=str),
                    None,
                )

            log.info(
                "Registration person created successfully | person_id=%s",
                person_row["person_id"],
            )

            return {
                **dict(person_row),
                "message": "Registration person created successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # UNIQUE CONSTRAINT HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                "uq_reg_person_gstid_pan_active":
                    "This PAN already exists for this GST (active).",
                "uq_reg_person_gstid_aadhaar_active":
                    "This Aadhaar already exists for this GST (active).",
                "uq_reg_primary_per_gstid":
                    "Only one active primary person is allowed per GST.",
            }

            log.warning(
                "Unique constraint violation | constraint=%s",
                constraint,
                exc_info=True,
            )

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    f"Duplicate value violates constraint: {constraint}",
                ),
            )

        # --------------------------------------------------
        # FOREIGN KEY
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        # --------------------------------------------------
        # CHECK CONSTRAINT HANDLING
        # --------------------------------------------------
        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_pan_format": "Invalid PAN format.",
                "chk_person_aadhaar_format": "Invalid Aadhaar format.",
                "chk_person_gst_format": "Invalid GSTIN format.",
                "chk_person_mobile_format": "Invalid mobile number format.",
            }

            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                ),
            )

        # --------------------------------------------------
        # GENERAL DB ERROR
        # --------------------------------------------------
        except asyncpg.PostgresError as e:
            log.error("Database error | %s", str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during Registration Person creation")
            raise HTTPException(status_code=500, detail="Internal server error.")
# -------------------------------------------------------------------
# LIST REGISTRATION PERSONS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------
@router.get(
    "/dynamic_filter",
    summary="Filter Registration Persons (Table Only)",
    responses={
        200: {"description": "Registration persons filtered successfully."},
        400: {"description": "Validation failed (e.g. invalid date range)."},
        500: {"description": "Database or internal error."},
    },
)
async def list_registration_persons(
    person_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    gst_registration_id: Optional[int] = None,
    gstin: Optional[str] = None,
    gstin_is_null: Optional[bool] = None,
    pan: Optional[str] = None,
    aadhaar: Optional[str] = None,
    mobile: Optional[str] = None,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    designation: Optional[str] = None,
    is_primary_customer: Optional[bool] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Enterprise Registration Person Filtering

    ✔ Filters only from registration_persons table
    ✔ Supports gst_registration_id (FK safe)
    ✔ Supports GSTIN null filtering
    ✔ Trim + uppercase safe
    ✔ Partial match for name/designation
    ✔ Active filtering pattern aligned
    ✔ Pagination safe
    ✔ Structured logging
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info(
        "Incoming registration persons filter | limit=%s offset=%s",
        limit,
        offset,
    )

    # --------------------------------------------------
    # Date Validation
    # --------------------------------------------------
    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
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

    try:
        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Exact Match Filters
        # --------------------------------------------------

        if person_id is not None:
            conditions.append(f"person_id = ${param_index}")
            values.append(person_id)
            param_index += 1

        if customer_id is not None:
            conditions.append(f"customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if gst_registration_id is not None:
            conditions.append(f"gst_registration_id = ${param_index}")
            values.append(gst_registration_id)
            param_index += 1

        # ---------------- GSTIN ----------------
        if gstin_is_null:
            conditions.append("gstin IS NULL")
        elif gstin and gstin.strip():
            conditions.append(f"upper(gstin) = ${param_index}")
            values.append(gstin.strip().upper())
            param_index += 1

        if pan and pan.strip():
            conditions.append(f"upper(pan) = ${param_index}")
            values.append(pan.strip().upper())
            param_index += 1

        if aadhaar and aadhaar.strip():
            conditions.append(f"trim(aadhaar) = ${param_index}")
            values.append(aadhaar.strip())
            param_index += 1

        if mobile and mobile.strip():
            conditions.append(f"mobile = ${param_index}")
            values.append(mobile.strip())
            param_index += 1

        if email and email.strip():
            conditions.append(f"lower(email) = ${param_index}")
            values.append(email.strip().lower())
            param_index += 1

        if is_primary_customer is not None:
            conditions.append(f"is_primary_customer = ${param_index}")
            values.append(is_primary_customer)
            param_index += 1

        # --------------------------------------------------
        # Partial Match Filters
        # --------------------------------------------------

        if full_name and full_name.strip():
            conditions.append(f"full_name ILIKE ${param_index}")
            values.append(f"%{full_name.strip()}%")
            param_index += 1

        if designation and designation.strip():
            conditions.append(f"designation ILIKE ${param_index}")
            values.append(f"%{designation.strip()}%")
            param_index += 1

        # --------------------------------------------------
        # Active Filtering Pattern
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # Date Filters
        # --------------------------------------------------

        if from_date:
            conditions.append(f"created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        # --------------------------------------------------
        # WHERE Builder
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_sql = f"""
            SELECT COUNT(*)
              FROM {DB_SCHEMA}.registration_persons
              {where_clause}
        """

        data_sql = f"""
            SELECT *
              FROM {DB_SCHEMA}.registration_persons
              {where_clause}
             ORDER BY created_at DESC, person_id DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:
            total_count = await conn.fetchval(count_sql, *values)
            rows = await conn.fetch(data_sql, *values_with_pagination)

        log.info(
            "Registration persons filter success | returned=%s total=%s",
            len(rows),
            total_count,
        )

        return {
            "data": [dict(row) for row in rows]
        }

    except asyncpg.PostgresError as e:
        log.error(
            "Database error during registration persons filtering | error=%s",
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Database error occurred during filtering.",
        )

    except HTTPException:
        raise

    except Exception:
        log.exception("Unexpected error during registration persons filtering")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )


def mask_gstin(gstin: str) -> str:
    if not gstin or len(gstin) < 6:
        return "****"
    return f"{gstin[:2]}******{gstin[-3:]}"
# -------------------------------------------------------------------
# EDIT REGISTRATION PERSON (PERSON_ID ONLY + ACTIVE)
# -------------------------------------------------------------------
@router.post(
    "/{person_id}/edit",
    summary="Edit Registration Person (Production Ready + Version Audit)",
    responses={
        200: {"description": "Registration person updated successfully."},
        400: {"description": "Validation failed or invalid data."},
        404: {"description": "Registration person not found or inactive."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_registration_person(
    person_id: int,
    payload: RegistrationPersonEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Edit Registration Person
    ------------------------
    ✔ Dynamic update of only provided fields
    ✔ Only active persons can be updated
    ✔ Mobile update propagates to registration_documents
    ✔ Primary logic aligned with gst_registration_id (ID-based)
    ✔ Version audit created
    ✔ Fully NULL safe
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "edit_registration_person"},
    )
    log.info("Incoming edit registration person | person_id=%s", person_id)

    # --------------------------------------------------
    # Extract and normalize update payload
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        log.exception("Payload serialization failed")
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update.")

    # --------------------------------------------------
    # Normalize Fields (DB index safe)
    # --------------------------------------------------
    try:
        if "pan" in update_data and update_data["pan"]:
            update_data["pan"] = update_data["pan"].strip().upper()

        if "aadhaar" in update_data and update_data["aadhaar"]:
            update_data["aadhaar"] = update_data["aadhaar"].strip()

        if "email" in update_data and update_data["email"]:
            update_data["email"] = update_data["email"].strip().lower()

        if "mobile" in update_data and update_data["mobile"]:
            update_data["mobile"] = update_data["mobile"].strip()

        if "full_name" in update_data and update_data["full_name"]:
            update_data["full_name"] = update_data["full_name"].strip()

        if "designation" in update_data and update_data["designation"]:
            update_data["designation"] = update_data["designation"].strip()

    except Exception:
        log.exception("Normalization failed")
        raise HTTPException(status_code=400, detail="Invalid field values provided.")

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch existing person (active only)
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.registration_persons
                     WHERE person_id = $1
                       AND is_active = TRUE
                     LIMIT 1
                    """,
                    person_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration person not found or inactive.",
                    )

                # --------------------------------------------------
                # 2️⃣ Handle primary person logic (ID-based)
                # --------------------------------------------------
                if (
                    "is_primary_customer" in update_data
                    and update_data["is_primary_customer"] is True
                ):
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.registration_persons
                           SET is_primary_customer = FALSE,
                               updated_at = NOW()
                         WHERE gst_registration_id = $1
                           AND is_primary_customer = TRUE
                           AND is_active = TRUE
                        """,
                        old_row["gst_registration_id"],
                    )

                # --------------------------------------------------
                # 3️⃣ Build dynamic UPDATE for registration_persons
                # --------------------------------------------------
                fields, values, idx = [], [], 1

                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1

                fields.append("updated_at = NOW()")
                values.append(person_id)

                sql = f"""
                    UPDATE {DB_SCHEMA}.registration_persons
                       SET {', '.join(fields)}
                     WHERE person_id = ${idx}
                       AND is_active = TRUE
                     RETURNING *
                """

                new_row = await conn.fetchrow(sql, *values)

                if not new_row:
                    raise HTTPException(
                        status_code=409,
                        detail="Person state changed. Please retry.",
                    )

                # --------------------------------------------------
                # 4️⃣ Propagate mobile change to registration_documents
                # --------------------------------------------------
                if "mobile" in update_data and update_data["mobile"]:
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.registration_documents
                           SET mobile = $1,
                               updated_at = NOW()
                         WHERE person_id = $2
                           AND is_active = TRUE
                        """,
                        update_data["mobile"],
                        person_id,
                    )

                # --------------------------------------------------
                # 5️⃣ Version Audit
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "REGISTRATION_PERSON",
                    person_id,
                    old_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info(
                "Registration person updated successfully | person_id=%s",
                person_id,
            )

            return {
                **dict(new_row),
                "message": "Registration person updated successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # UNIQUE CONSTRAINT HANDLING (Correct Names)
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint_name = getattr(e, "constraint_name", "")

            UNIQUE_MAP = {
                "uq_reg_person_gstid_aadhaar_active": "Aadhaar already exists for this GST (active).",
                "uq_reg_person_gstid_pan_active": "PAN already exists for this GST (active).",
                "uq_reg_primary_per_gstid": "Only one active primary person allowed per GST.",
            }

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint_name,
                    f"Duplicate value violates constraint: {constraint_name}",
                ),
            )

        # --------------------------------------------------
        # FOREIGN KEY
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        # --------------------------------------------------
        # CHECK CONSTRAINTS
        # --------------------------------------------------
        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_pan_format": "Invalid PAN format. Expected: ABCDE1234F",
                "chk_person_aadhaar_format": "Invalid Aadhaar format (12 digits required).",
                "chk_person_mobile_format": "Invalid mobile format (10 digits required).",
            }

            raise HTTPException(
                status_code=400,
                detail=CHECK_MAP.get(
                    constraint,
                    f"Data violates constraint: {constraint}",
                ),
            )

        # --------------------------------------------------
        # GENERAL DB ERRORS
        # --------------------------------------------------
        except asyncpg.PostgresError:
            log.exception("Database error during registration person update")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration person update")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
# -------------------------------------------------------------------
# SOFT DELETE REGISTRATION PERSON (Enterprise + Audit + Cascade Docs)
# -------------------------------------------------------------------

@router.delete(
    "/{person_id}/soft_delete",
    summary="Soft delete Registration Person (Enterprise + Audit + Cascade Docs)",
    responses={
        200: {"description": "Registration person soft deleted successfully."},
        400: {"description": "Business validation failed."},
        404: {"description": "Registration person not found."},
        500: {"description": "Database or internal error."},
    },
)

async def soft_delete_registration_person(
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Soft delete a registration person and cascade deactivate all associated documents.

    ✔ Atomic transaction
    ✔ Concurrency safe
    ✔ Cascade soft delete for person's documents
    ✔ Version audit for person only (documents audit skipped)
    ✔ Primary person protection
    ✔ Structured logging
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "soft_delete_registration_person",
        },
    )

    log.info("Incoming soft delete registration person | person_id=%s", person_id)

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch Existing Person
                # --------------------------------------------------
                person_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.registration_persons
                     WHERE person_id = $1
                     LIMIT 1
                    """,
                    person_id,
                )

                if not person_row:
                    raise HTTPException(status_code=404, detail="Registration person not found.")

                if person_row["is_active"] is False:
                    raise HTTPException(status_code=400, detail="Registration person is already inactive.")

                # --------------------------------------------------
                # 2️⃣ Primary Person Protection
                # --------------------------------------------------
                if person_row["is_primary_customer"]:
                    other_active_count = await conn.fetchval(
                        f"""
                        SELECT COUNT(*)
                          FROM {DB_SCHEMA}.registration_persons
                         WHERE customer_id = $1
                           AND is_active = TRUE
                           AND person_id <> $2
                        """,
                        person_row["customer_id"],
                        person_id,
                    )

                    if other_active_count > 0:
                        raise HTTPException(
                            status_code=400,
                            detail="Cannot delete primary person while other active persons exist. "
                                   "Please assign another primary person first or deactive all non_primary and then deactivate primary.",
                        )

                # --------------------------------------------------
                # 3️⃣ Concurrency-Safe Soft Delete (Person)
                # --------------------------------------------------
                delete_person_sql = f"""
                    UPDATE {DB_SCHEMA}.registration_persons
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE person_id = $1
                       AND is_active = TRUE
                     RETURNING *
                """
                deleted_person = await conn.fetchrow(delete_person_sql, person_id)

                if not deleted_person:
                    raise HTTPException(status_code=400, detail="Unable to delete registration person.")

                # --------------------------------------------------
                # 4️⃣ Cascade Soft Delete for Person's Documents
                # --------------------------------------------------
                deleted_docs = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_documents
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE person_id = $1
                       AND is_active = TRUE
                     RETURNING *
                    """,
                    person_id,
                )

                # --------------------------------------------------
                # 5️⃣ Version Audit for Each Document (SKIPPED)
                # --------------------------------------------------
                # for doc in deleted_docs:
                #     await conn.execute(
                #         f"""
                #         INSERT INTO {DB_SCHEMA}.versions
                #         (
                #             emp_id,
                #             entity_type,
                #             entity_id,
                #             customer_id,
                #             action,
                #             json,
                #             updated_json
                #         )
                #         VALUES ($1,$2,$3,$4,$5,$6,$7)
                #         """,
                #         emp_id,
                #         "REGISTRATION_DOCUMENT",
                #         doc["document_id"],
                #         person_row["customer_id"],
                #         "DELETE",
                #         None,
                #         json.dumps(dict(doc), default=str),
                #     )

                # --------------------------------------------------
                # 6️⃣ Version Audit for Person
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "REGISTRATION_PERSON",
                    person_id,
                    person_row["customer_id"],
                    "DELETE",
                    None,
                    json.dumps(dict(deleted_person), default=str),
                )

            log.info(
                "Registration person soft deleted successfully | person_id=%s | documents_deactivated=%s",
                person_id,
                len(deleted_docs),
            )

            return {
                **dict(deleted_person),
                "documents_deactivated_count": len(deleted_docs),
                "message": "Registration person soft deleted successfully. All active documents deactivated.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # Exception Handling
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK ERROR")
            raise HTTPException(status_code=400, detail=str(e))

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError as e:
            log.exception("Postgres error")
            raise HTTPException(status_code=500, detail=str(e))

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration person soft delete")
            raise HTTPException(status_code=500, detail="Internal server error.")

# -------------------------------------------------------------------
# ACTIVATE REGISTRATION PERSON
# (Enterprise + Version Audit + Cascade Docs + GST & Customer Active Check)
# -------------------------------------------------------------------

@router.post(
    "/{person_id}/activate",
    summary="Activate Registration Person (Production Ready + Audit + Cascade Documents)",
    responses={
        200: {"description": "Registration person activated successfully."},
        400: {"description": "Validation failed or already active."},
        404: {"description": "Registration person not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def activate_registration_person(
    person_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    """
    Activate Registration Person and cascade activate all associated documents.

    ✔ Atomic transaction
    ✔ Concurrency safe
    ✔ GST must be active
    ✔ Customer must be active
    ✔ Cascade activation of person's documents
    ✔ Version audit for person only (documents audit skipped)
    ✔ Structured logging
    """
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "activate_registration_person",
        },
    )
    log.info("Incoming registration person activation | person_id=%s", person_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch Existing Person + GST + Customer Status
                # 🔥 IMPROVED: Join using gst_registration_id (ID-based architecture)
                # --------------------------------------------------
                person_row = await conn.fetchrow(
                    f"""
                    SELECT rp.*, 
                           c.is_active AS customer_active, 
                           gst.is_active AS gst_active
                      FROM {DB_SCHEMA}.registration_persons rp
                      JOIN {DB_SCHEMA}.customers c
                        ON rp.customer_id = c.customer_id
                      JOIN {DB_SCHEMA}.gst_registration gst
                        ON rp.gst_registration_id = gst.id
                     WHERE rp.person_id = $1
                     LIMIT 1
                    """,
                    person_id,
                )

                if not person_row:
                    raise HTTPException(status_code=404, detail="Registration person not found.")

                if person_row["is_active"]:
                    raise HTTPException(status_code=400, detail="Registration person already active.")

                if not person_row["gst_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot activate person: associated GST is inactive. Activate GST first.",
                    )

                if not person_row["customer_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot activate person: associated customer is inactive.",
                    )

                # Store customer_id once for audit
                customer_id = person_row["customer_id"]

                # --------------------------------------------------
                # 2️⃣ Activate Person (Concurrency Safe)
                # --------------------------------------------------
                activate_person_sql = f"""
                    UPDATE {DB_SCHEMA}.registration_persons
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE person_id = $1
                       AND is_active = FALSE
                     RETURNING *
                """
                activated_person = await conn.fetchrow(activate_person_sql, person_id)
                if not activated_person:
                    raise HTTPException(
                        status_code=409,
                        detail="Person state changed. Please retry.",
                    )

                # --------------------------------------------------
                # 3️⃣ Cascade Activate Person's Documents
                # --------------------------------------------------
                activated_docs = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_documents
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE person_id = $1
                       AND is_active = FALSE
                     RETURNING *
                    """,
                    person_id,
                )

                # --------------------------------------------------
                # 4️⃣ Version Audit for Documents (SKIPPED)
                # --------------------------------------------------
                # for doc in activated_docs:
                #     await conn.execute(
                #         f"""
                #         INSERT INTO {DB_SCHEMA}.versions
                #         (
                #             emp_id,
                #             entity_type,
                #             entity_id,
                #             customer_id,
                #             action,
                #             json,
                #             updated_json
                #         )
                #         VALUES ($1,$2,$3,$4,$5,$6,$7)
                #         """,
                #         emp_id,
                #         "REGISTRATION_DOCUMENT",
                #         doc["document_id"],
                #         customer_id,
                #         "ACTIVATE",
                #         None,
                #         json.dumps(dict(doc), default=str),
                #     )

                # --------------------------------------------------
                # 5️⃣ Version Audit for Person
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (
                        emp_id,
                        entity_type,
                        entity_id,
                        customer_id,
                        action,
                        json,
                        updated_json
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "REGISTRATION_PERSON",
                    person_id,
                    customer_id,
                    "ACTIVATE",
                    None,
                    json.dumps(dict(activated_person), default=str),
                )

            log.info(
                "Registration person activated successfully | person_id=%s | documents_activated=%s",
                person_id,
                len(activated_docs),
            )

            return {
                **dict(activated_person),
                "documents_activated_count": len(activated_docs),
                "message": "Registration person activated successfully. All associated documents activated.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # Exception Handling
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK ERROR")
            raise HTTPException(status_code=400, detail=str(e))

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError as e:
            log.exception("Database error during person activation")
            raise HTTPException(status_code=500, detail=str(e))

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration person activation")
            raise HTTPException(status_code=500, detail="Internal server error.")