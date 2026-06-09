import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.gst_registration.schemas import (
    RegistrationPersonIn,
    RegistrationPersonEditIn,
)
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_gst_visibility
from app.logger import logger
from app.text_search_filters import append_fuzzy_name_filter
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from datetime import date, datetime
from zoneinfo import ZoneInfo
import json
import re

router = APIRouter(
    prefix="/api/v1/gst-people",
    tags=["GST Registration People"]
)


def _gst_people_designations_tag() -> str:
    return "gst_people:designations:index"


def _gst_people_filter_tag() -> str:
    return "gst_people:filter:index"


async def _invalidate_gst_people_cache() -> None:
    await redis_invalidate_tag(_gst_people_designations_tag())
    await redis_invalidate_tag(_gst_people_filter_tag())

# -------------------------------------------------------------------
# GET DESIGNATIONS BASED ON OWNERSHIP CATEGORY
# -------------------------------------------------------------------

# -------------------------------------------------------------------
# GET DESIGNATIONS BASED ON OWNERSHIP CATEGORY
# -------------------------------------------------------------------

@router.get(
    "/gst-registration/{gst_id}/designations",
    summary="Get Designations based on GST Ownership Category",
)
async def get_designations(
    gst_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id}
    )

    log.info(
        "Fetching designations | gst_id=%s",
        gst_id,
    )
    cache_key = build_cache_key(
        "gst_people:designations",
        gst_id=gst_id,
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
            detail="Database connection error."
        )

    async def _load_designations():
        async with pool.acquire() as conn:
            try:
                gst_row = await conn.fetchrow(
                    f"""
                    SELECT
                        id,
                        ownership_category
                    FROM {DB_SCHEMA}.gst_registration
                    WHERE id = $1
                    AND is_active = TRUE
                    """,
                    gst_id,
                )

                if not gst_row:
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": {
                                    "gst_id": "GST registration not found or inactive."
                                }
                            }
                        }
                    )

                ownership_category = gst_row["ownership_category"]
                ownership_category_norm = (
                    str(ownership_category).strip().upper() if ownership_category is not None else None
                )
                rows = await conn.fetch(
                    f"""
                    SELECT
                        value,
                        display_name,
                        description
                    FROM {DB_SCHEMA}.gst_registration_config
                    WHERE upper(trim(config_type)) = $1
                    AND is_active = TRUE
                    ORDER BY sort_order
                    """,
                    ownership_category_norm,
                )
                designations = [dict(r) for r in rows]

                log.info(
                    "Designations fetched successfully | ownership_category=%s count=%s",
                    ownership_category,
                    len(designations),
                )

                return {
                    "gst_id": gst_id,
                    "ownership_category": ownership_category,
                    "designations": designations,
                    "request_id": request_id,
                }
            except asyncpg.PostgresError:
                log.exception("Database error while fetching designations")
                raise HTTPException(
                    status_code=500,
                    detail="Database error occurred."
                )
            except HTTPException:
                raise
            except Exception:
                log.exception("Unexpected error while fetching designations")
                raise HTTPException(
                    status_code=500,
                    detail="Internal server error."
                )

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_designations,
        ttl_seconds=300,
        tags=[_gst_people_designations_tag()],
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

    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:

        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Validate GST Exists
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

                derived_customer_id = gst_row["customer_id"]
                derived_gstin = gst_row["gstin"]
                derived_ownership = gst_row["ownership_category"]

                # --------------------------------------------------
                # 2️⃣ Normalize Inputs
                # --------------------------------------------------

                pan_value = payload.pan.strip().upper() if payload.pan else None
                aadhaar_value = payload.aadhaar.strip() if payload.aadhaar else None
                email_value = payload.email.strip().lower() if payload.email else None
                mobile_value = payload.mobile.strip() if payload.mobile else None

                field_errors = {}

                # --------------------------------------------------
                # 3️⃣ Format Validation
                # --------------------------------------------------

                if pan_value and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan_value):
                    field_errors["pan"] = "Invalid PAN format. Expected: ABCDE1234F"

                if aadhaar_value and not re.fullmatch(r"[0-9]{12}", aadhaar_value):
                    field_errors["aadhaar"] = "Invalid Aadhaar format (12 digits required)."

                if mobile_value and not re.fullmatch(r"[0-9]{10}", mobile_value):
                    field_errors["mobile"] = "Invalid mobile format (10 digits required)."

                if email_value and not re.fullmatch(
                    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$",
                    email_value,
                ):
                    field_errors["email"] = "Invalid email format."

                # --------------------------------------------------
                # 4️⃣ Duplicate Check
                # --------------------------------------------------

                duplicate_row = await conn.fetchrow(
                    f"""
                    SELECT

                        CASE
                            WHEN $2::text IS NULL THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                FROM {DB_SCHEMA}.gst_registration_persons
                                WHERE gst_registration_id = $1
                                AND is_active = TRUE
                                AND pan IS NOT NULL
                                AND upper(trim(pan)) = upper(trim($2))
                            )
                        END AS pan_match,

                        CASE
                            WHEN $3::text IS NULL THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                FROM {DB_SCHEMA}.gst_registration_persons
                                WHERE gst_registration_id = $1
                                AND is_active = TRUE
                                AND aadhaar IS NOT NULL
                                AND trim(aadhaar) = trim($3)
                            )
                        END AS aadhaar_match,

                        CASE
                            WHEN $4::text IS NULL THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                FROM {DB_SCHEMA}.gst_registration_persons
                                WHERE gst_registration_id = $1
                                AND is_active = TRUE
                                AND email IS NOT NULL
                                AND lower(trim(email)) = lower(trim($4))
                            )
                        END AS email_match,

                        CASE
                            WHEN $5::text IS NULL THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                FROM {DB_SCHEMA}.gst_registration_persons
                                WHERE gst_registration_id = $1
                                AND is_active = TRUE
                                AND mobile IS NOT NULL
                                AND trim(mobile) = trim($5)
                            )
                        END AS mobile_match,

                        CASE
                            WHEN $6::boolean = TRUE THEN EXISTS(
                                SELECT 1
                                FROM {DB_SCHEMA}.gst_registration_persons
                                WHERE gst_registration_id = $1
                                AND is_primary_customer = TRUE
                                AND is_active = TRUE
                            )
                            ELSE FALSE
                        END AS primary_match

                    """,
                    payload.gst_registration_id,
                    pan_value,
                    aadhaar_value,
                    email_value,
                    mobile_value,
                    payload.is_primary_customer,
                )

                if duplicate_row:

                    if duplicate_row["pan_match"]:
                        field_errors["pan"] = "This PAN already exists for this GST."

                    if duplicate_row["aadhaar_match"]:
                        field_errors["aadhaar"] = "This Aadhaar already exists for this GST."

                    if duplicate_row["email_match"]:
                        field_errors["email"] = "This email already exists for this GST."

                    if duplicate_row["mobile_match"]:
                        field_errors["mobile"] = "This mobile already exists for this GST."

                    if duplicate_row["primary_match"]:
                        field_errors["is_primary_customer"] = (
                            "Only one active primary person is allowed per GST."
                        )

                if field_errors:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": field_errors,
                            }
                        },
                    )

                # --------------------------------------------------
                # 5️⃣ Insert Registration Person
                # --------------------------------------------------

                person_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.gst_registration_persons
                    (
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
                    VALUES
                    (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,TRUE,$10,$11,$12,$13
                    )
                    RETURNING *
                    """,
                    derived_customer_id,
                    derived_gstin,
                    payload.full_name,
                    payload.designation,
                    pan_value,
                    aadhaar_value,
                    email_value,
                    mobile_value,
                    payload.is_primary_customer,
                    now,
                    now,
                    derived_ownership,
                    payload.gst_registration_id,
                )

                if not person_row:
                    raise HTTPException(
                        status_code=500,
                        detail="Registration person creation failed.",
                    )

                # --------------------------------------------------
                # 6️⃣ Version Audit
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
            await _invalidate_gst_people_cache()

            return {
                **dict(person_row),
                "message": "Registration person created successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.UniqueViolationError as e:

            constraint = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                "uq_reg_person_gstid_pan_active":
                    "This PAN already exists for this GST.",
                "uq_reg_person_gstid_aadhaar_active":
                    "This Aadhaar already exists for this GST.",
                "uq_reg_person_gstid_mobile_active":
                    "This mobile already exists for this GST.",
                "uq_reg_person_gstid_email_active":
                    "This email already exists for this GST.",
                "uq_reg_primary_per_gstid":
                    "Only one active primary person is allowed per GST.",
            }

            raise HTTPException(
                status_code=409,
                detail=UNIQUE_MAP.get(
                    constraint,
                    f"Duplicate value violates constraint: {constraint}",
                ),
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

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
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Enterprise Registration Person Filtering
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    role = current_user.get("role")

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
    role_norm = str(role).strip().upper() if role is not None else None
    gstin_norm = gstin.strip().upper() if gstin and gstin.strip() else None
    pan_norm = pan.strip().upper() if pan and pan.strip() else None
    aadhaar_norm = aadhaar.strip() if aadhaar and aadhaar.strip() else None
    mobile_norm = mobile.strip() if mobile and mobile.strip() else None
    email_norm = email.strip().lower() if email and email.strip() else None
    full_name_norm = full_name.strip() if full_name and full_name.strip() else None
    designation_norm = designation.strip() if designation and designation.strip() else None
    emp_id_for_scope = int(current_emp_id) if str(current_emp_id).isdigit() else None
    cache_key = build_cache_key(
        "gst_people:filter",
        person_id=person_id,
        customer_id=customer_id,
        gst_registration_id=gst_registration_id,
        gstin=gstin_norm,
        gstin_is_null=gstin_is_null,
        pan=pan_norm,
        aadhaar=aadhaar_norm,
        mobile=mobile_norm,
        email=email_norm,
        full_name=full_name_norm,
        designation=designation_norm,
        is_primary_customer=is_primary_customer,
        is_active=is_active,
        include_inactive=include_inactive,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
        role=role_norm,
        emp_id=emp_id_for_scope,
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

    async def _load_list_registration_persons():
        conditions = []
        values = []
        param_index = 1

        # --------------------------------------------------
        # Exact Match Filters
        # --------------------------------------------------

        if person_id is not None:
            conditions.append(f"p.person_id = ${param_index}")
            values.append(person_id)
            param_index += 1

        if customer_id is not None:
            conditions.append(f"p.customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if gst_registration_id is not None:
            conditions.append(f"p.gst_registration_id = ${param_index}")
            values.append(gst_registration_id)
            param_index += 1

        # ---------------- GSTIN ----------------
        if gstin_is_null is not None:
            conditions.append("p.gstin IS NULL" if gstin_is_null else "p.gstin IS NOT NULL")
        elif gstin_norm:
            conditions.append(f"upper(trim(p.gstin)) = ${param_index}")
            values.append(gstin_norm)
            param_index += 1

        if pan_norm:
            conditions.append(f"upper(p.pan) = ${param_index}")
            values.append(pan_norm)
            param_index += 1

        if aadhaar_norm:
            conditions.append(f"trim(p.aadhaar) = ${param_index}")
            values.append(aadhaar_norm)
            param_index += 1

        if mobile_norm:
            conditions.append(f"btrim(p.mobile) = btrim(${param_index}::text)")
            values.append(mobile_norm)
            param_index += 1

        if email_norm:
            conditions.append(f"lower(p.email) = ${param_index}")
            values.append(email_norm)
            param_index += 1

        if is_primary_customer is not None:
            conditions.append(f"p.is_primary_customer = ${param_index}")
            values.append(is_primary_customer)
            param_index += 1

        # --------------------------------------------------
        # Partial Match Filters
        # --------------------------------------------------

        if full_name_norm:
            param_index = append_fuzzy_name_filter(
                conditions,
                values,
                param_index,
                "p.full_name",
                full_name_norm,
            )

        if designation_norm:
            param_index = append_fuzzy_name_filter(
                conditions,
                values,
                param_index,
                "p.designation",
                designation_norm,
            )

        # --------------------------------------------------
        # Active Filtering Pattern
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"p.is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("p.is_active = TRUE")

        # --------------------------------------------------
        # Date Filters
        # --------------------------------------------------

        if from_date:
            conditions.append(f"p.created_at::date >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"p.created_at::date <= ${param_index}")
            values.append(to_date)
            param_index += 1

        # --------------------------------------------------
        # ROLE BASED VISIBILITY (GST → PERSON)
        # --------------------------------------------------

        visibility_sql, visibility_values, param_index = build_gst_visibility(
            role_norm,
            emp_id_for_scope,
            param_index,
            DB_SCHEMA
        )

        if visibility_sql:
            visibility_sql = f"""
            p.gst_registration_id IN (
                SELECT g.id
                FROM {DB_SCHEMA}.gst_registration g
                WHERE {visibility_sql}
            )
            """
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        # --------------------------------------------------
        # WHERE Builder
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_sql = f"""
            SELECT COUNT(*)
              FROM {DB_SCHEMA}.gst_registration_persons p
              LEFT JOIN {DB_SCHEMA}.gst_registration g
                     ON p.gst_registration_id = g.id
              {where_clause}
        """

        data_sql = f"""
            SELECT p.*,
                   g.rm_id,
                   g.created_by,
                   e_rm.first_name AS rm_name,
                   e_creator.first_name AS created_by_name
              FROM {DB_SCHEMA}.gst_registration_persons p
              LEFT JOIN {DB_SCHEMA}.gst_registration g
                     ON p.gst_registration_id = g.id
              LEFT JOIN {DB_SCHEMA}.employees e_rm
                     ON g.rm_id = e_rm.emp_id
              LEFT JOIN {DB_SCHEMA}.employees e_creator
                     ON g.created_by = e_creator.emp_id
              {where_clause}
             ORDER BY p.created_at DESC, p.person_id DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        try:
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

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_list_registration_persons,
        ttl_seconds=300,
        tags=[_gst_people_filter_tag()],
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
    current_user=Depends(require_permission("USER_ACCESS", "WRITE")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "edit_registration_person"},
    )

    log.info("Incoming edit registration person | person_id=%s", person_id)

    # --------------------------------------------------
    # Extract payload
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        log.exception("Payload serialization failed")
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update.")

    # --------------------------------------------------
    # Normalize fields
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
    # DB pool
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
                # 1️⃣ Fetch existing person
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.gst_registration_persons
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

                gst_registration_id = old_row["gst_registration_id"]

                # --------------------------------------------------
                # 2️⃣ Format validation
                # --------------------------------------------------
                field_errors = {}

                pan_value = update_data.get("pan")
                aadhaar_value = update_data.get("aadhaar")
                email_value = update_data.get("email")
                mobile_value = update_data.get("mobile")

                if pan_value and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan_value):
                    field_errors["pan"] = "Invalid PAN format. Expected: ABCDE1234F"

                if aadhaar_value and not re.fullmatch(r"[0-9]{12}", aadhaar_value):
                    field_errors["aadhaar"] = "Invalid Aadhaar format (12 digits required)."

                if mobile_value and not re.fullmatch(r"[0-9]{10}", mobile_value):
                    field_errors["mobile"] = "Invalid mobile format (10 digits required)."

                if email_value and not re.fullmatch(
                    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$",
                    email_value,
                ):
                    field_errors["email"] = "Invalid email format."

                # --------------------------------------------------
                # 3️⃣ Duplicate checks
                # --------------------------------------------------
                duplicate_row = await conn.fetchrow(
                    f"""
                    SELECT

                        CASE
                            WHEN $2::text IS NULL THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                FROM {DB_SCHEMA}.gst_registration_persons
                                WHERE gst_registration_id = $1
                                AND is_active = TRUE
                                AND person_id <> $6
                                AND pan IS NOT NULL
                                AND upper(trim(pan)) = upper(trim($2))
                            )
                        END AS pan_match,

                        CASE
                            WHEN $3::text IS NULL THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                FROM {DB_SCHEMA}.gst_registration_persons
                                WHERE gst_registration_id = $1
                                AND is_active = TRUE
                                AND person_id <> $6
                                AND aadhaar IS NOT NULL
                                AND trim(aadhaar) = trim($3)
                            )
                        END AS aadhaar_match,

                        CASE
                            WHEN $4::text IS NULL THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                FROM {DB_SCHEMA}.gst_registration_persons
                                WHERE gst_registration_id = $1
                                AND is_active = TRUE
                                AND person_id <> $6
                                AND email IS NOT NULL
                                AND lower(trim(email)) = lower(trim($4))
                            )
                        END AS email_match,

                        CASE
                            WHEN $5::text IS NULL THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                FROM {DB_SCHEMA}.gst_registration_persons
                                WHERE gst_registration_id = $1
                                AND is_active = TRUE
                                AND person_id <> $6
                                AND mobile IS NOT NULL
                                AND trim(mobile) = trim($5)
                            )
                        END AS mobile_match
                    """,
                    gst_registration_id,
                    pan_value,
                    aadhaar_value,
                    email_value,
                    mobile_value,
                    person_id,
                )

                if duplicate_row:

                    if duplicate_row["pan_match"]:
                        field_errors["pan"] = "PAN already exists for this GST."

                    if duplicate_row["aadhaar_match"]:
                        field_errors["aadhaar"] = "Aadhaar already exists for this GST."

                    if duplicate_row["email_match"]:
                        field_errors["email"] = "Email already exists for this GST."

                    if duplicate_row["mobile_match"]:
                        field_errors["mobile"] = "Mobile already exists for this GST."

                if field_errors:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": field_errors,
                            }
                        },
                    )

                # --------------------------------------------------
                # 4️⃣ Reject if no actual change
                # --------------------------------------------------

                no_change = True

                for k, v in update_data.items():

                    if k in old_row and old_row[k] != v:
                        no_change = False
                        break

                if no_change:

                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "No changes detected to update.",
                                "fields": {}
                            }
                        }
                    )

                # --------------------------------------------------
                # 5️⃣ Handle primary logic
                # --------------------------------------------------
                if (
                    "is_primary_customer" in update_data
                    and update_data["is_primary_customer"] is True
                ):
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration_persons
                        SET is_primary_customer = FALSE,
                            updated_at = NOW()
                        WHERE gst_registration_id = $1
                        AND is_primary_customer = TRUE
                        AND is_active = TRUE
                        """,
                        gst_registration_id,
                    )

                # --------------------------------------------------
                # 6️⃣ Dynamic update
                # --------------------------------------------------
                fields, values, idx = [], [], 1

                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1

                fields.append("updated_at = NOW()")
                values.append(person_id)

                sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration_persons
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
                # 7️⃣ Mobile propagation
                # --------------------------------------------------
                if "mobile" in update_data and update_data["mobile"]:

                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration_documents
                        SET mobile = $1,
                            updated_at = NOW()
                        WHERE person_id = $2
                        AND is_active = TRUE
                        """,
                        update_data["mobile"],
                        person_id,
                    )

                # --------------------------------------------------
                # 8️⃣ Version audit
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
            await _invalidate_gst_people_cache()

            return {
                **dict(new_row),
                "message": "Registration person updated successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.UniqueViolationError as e:

            constraint_name = getattr(e, "constraint_name", "")

            UNIQUE_FIELD_MAP = {
                "uq_reg_person_gstid_pan_active":
                    ("pan", "PAN already exists for this GST."),
                "uq_reg_person_gstid_aadhaar_active":
                    ("aadhaar", "Aadhaar already exists for this GST."),
                "uq_reg_person_gstid_mobile_active":
                    ("mobile", "Mobile already exists for this GST."),
                "uq_reg_person_gstid_email_active":
                    ("email", "Email already exists for this GST."),
                "uq_reg_primary_per_gstid":
                    ("is_primary_customer", "Only one active primary person allowed per GST."),
            }

            field, message = UNIQUE_FIELD_MAP.get(
                constraint_name,
                ("non_field_error", f"Duplicate value violates constraint: {constraint_name}"),
            )

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {field: message},
                    }
                },
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid foreign key reference.",
            )

        except asyncpg.exceptions.CheckViolationError as e:

            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_pan_format": ("pan", "Invalid PAN format."),
                "chk_person_aadhaar_format": ("aadhaar", "Invalid Aadhaar format."),
                "chk_person_mobile_format": ("mobile", "Invalid mobile format."),
            }

            field, message = CHECK_MAP.get(
                constraint,
                ("non_field_error", f"Data violates constraint: {constraint}"),
            )

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {field: message},
                    }
                },
            )

        except asyncpg.PostgresError:
            log.exception("Database error during registration person update")
            raise HTTPException(status_code=500, detail="Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration person update")
            raise HTTPException(status_code=500, detail="Internal server error.")
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
                      FROM {DB_SCHEMA}.gst_registration_persons
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
                          FROM {DB_SCHEMA}.gst_registration_persons
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
                    UPDATE {DB_SCHEMA}.gst_registration_persons
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
                    UPDATE {DB_SCHEMA}.gst_registration_documents
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE person_id = $1
                       AND is_active = TRUE
                     RETURNING *
                    """,
                    person_id,
                )
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
                    None,
                )

            log.info(
                "Registration person soft deleted successfully | person_id=%s | documents_deactivated=%s",
                person_id,
                len(deleted_docs),
            )
            await _invalidate_gst_people_cache()

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
# (Enterprise + Version Audit + Cascade Docs + Primary Enforcement)
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
                # 1️⃣ Fetch Person + GST + Customer Status (LOCK ROW)
                # --------------------------------------------------
                person_row = await conn.fetchrow(
                    f"""
                    SELECT rp.*, 
                           c.is_active AS customer_active, 
                           gst.is_active AS gst_active
                      FROM {DB_SCHEMA}.gst_registration_persons rp
                      JOIN {DB_SCHEMA}.customers c
                        ON rp.customer_id = c.customer_id
                      JOIN {DB_SCHEMA}.gst_registration gst
                        ON rp.gst_registration_id = gst.id
                     WHERE rp.person_id = $1
                     FOR UPDATE
                    """,
                    person_id,
                )

                if not person_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration person not found.",
                    )

                if person_row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Registration person already active.",
                    )

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

                gst_registration_id = person_row["gst_registration_id"]
                customer_id = person_row["customer_id"]
                is_primary = person_row["is_primary_customer"]

                # --------------------------------------------------
                # 2️⃣ Fetch Active Primary Person for this GST
                # --------------------------------------------------
                primary_person = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.gst_registration_persons
                     WHERE gst_registration_id = $1
                       AND is_primary_customer = TRUE
                       AND is_active = TRUE
                     LIMIT 1
                    """,
                    gst_registration_id,
                )

                # --------------------------------------------------
                # 3️⃣ Primary Enforcement Logic
                # --------------------------------------------------

                # ❌ If NO active primary exists
                if not primary_person:

                    # If this person is NOT primary → BLOCK
                    if not is_primary:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "Please activate the primary person first. "
                                "If you want to make another person primary, "
                                "activate the current primary person, change the primary designation "
                                "to the desired person, and then proceed."
                            ),
                        )

                # --------------------------------------------------
                # 4️⃣ Activate Person (Concurrency Safe)
                # --------------------------------------------------
                activate_person_sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration_persons
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE person_id = $1
                       AND is_active = FALSE
                     RETURNING *
                """

                activated_person = await conn.fetchrow(
                    activate_person_sql,
                    person_id,
                )

                if not activated_person:
                    raise HTTPException(
                        status_code=409,
                        detail="Person state changed. Please retry.",
                    )

                # --------------------------------------------------
                # 5️⃣ Cascade Activate Person's Documents
                # --------------------------------------------------
                activated_docs = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE person_id = $1
                       AND is_active = FALSE
                     RETURNING *
                    """,
                    person_id,
                )

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
                    customer_id,
                    "ACTIVATE",
                    None,
                    None,
                )

            log.info(
                "Registration person activated successfully | person_id=%s | documents_activated=%s",
                person_id,
                len(activated_docs),
            )
            await _invalidate_gst_people_cache()

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
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK ERROR")
            raise HTTPException(
                status_code=400,
                detail=str(e),
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail="Invalid data format.",
            )

        except asyncpg.PostgresError as e:
            log.exception("Database error during person activation")
            raise HTTPException(
                status_code=500,
                detail=str(e),
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during registration person activation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
