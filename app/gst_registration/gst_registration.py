import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from datetime import datetime, timezone
from app.gst_registration.schemas import (
    GSTRegistrationIn,
    GSTRegistrationEditIn,
    CustomerSnapshotForGstOut,
)
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_gst_visibility, build_customer_visibility
from app.security.rbac import require_permission
from app.logger import logger
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from app.gst_registration_filing.gst_return_details_rebuild import (
    rebuild_return_details_for_filing,
    count_active_return_details,
    infer_explicit_template_from_prior_row_count,
)
from zoneinfo import ZoneInfo
import json
import uuid
import re

router = APIRouter(
    prefix="/api/v1/gst-registrations",
    tags=["GST Registration"]
)


def _gst_reg_sql_col(name: str) -> str:
    """Ident must match ddl-quoted columns (e.g. \"language\", \"password\")."""
    if name in ("language", "password"):
        return f'"{name}"'
    return name


def _gst_filter_tag() -> str:
    return "gst_registration:filter:index"


def _gst_customer_fields_tag(customer_id: int) -> str:
    return f"gst_registration:customer_fields:index:{customer_id}"


def _gst_detail_tag(registration_id: int) -> str:
    return f"gst_registration:detail:index:{registration_id}"


async def _invalidate_gst_registration_cache(
    customer_id: Optional[int] = None,
    registration_id: Optional[int] = None,
) -> None:
    await redis_invalidate_tag(_gst_filter_tag())
    if customer_id is not None:
        await redis_invalidate_tag(_gst_customer_fields_tag(customer_id))
    if registration_id is not None:
        await redis_invalidate_tag(_gst_detail_tag(registration_id))


async def _customer_exists_and_active(conn: asyncpg.Connection, customer_id: int) -> bool:
    row = await conn.fetchrow(
        f"""
        SELECT 1
          FROM {DB_SCHEMA}.customers
         WHERE customer_id = $1
           AND is_active IS TRUE
        LIMIT 1
        """,
        customer_id,
    )
    return row is not None


# -------------------------------------------------------------------
# CREATE GST REGISTRATION
# -------------------------------------------------------------------
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create GST Registration",
    responses={
        201: {"description": "GST registration created successfully."},
        400: {"description": "Validation failed."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def create_gst_registration(
    payload: GSTRegistrationIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = str(uuid.uuid4())
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""

    # Assignment: mirror customer create — RM defaults rm_id; created_by = current emp_id only when role is OP.
    rm_id = payload.rm_id
    if role_norm == "RM" and rm_id is None:
        rm_id = emp_id
    created_by_val = emp_id if role_norm == "OP" else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
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
                # Pre-validation (format + duplicates)
                # --------------------------------------------------
                field_errors = {}

                gstin_value = payload.gstin.strip().upper() if payload.gstin else None
                pan_value = payload.pan.strip().upper() if payload.pan else None
                mobile_value = payload.mobile.strip() if payload.mobile else None
                username_value = payload.username.strip() if payload.username else None
                secondary_email_value = payload.secondary_email.strip().lower() if payload.secondary_email else None

                username_value = username_value or None
                mobile_value = mobile_value or None
                secondary_email_value = secondary_email_value or None

                if gstin_value and not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]", gstin_value):
                    field_errors["gstin"] = "Invalid GSTIN format."

                if pan_value and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan_value):
                    field_errors["pan"] = "Invalid PAN format."

                if mobile_value and not re.fullmatch(r"[0-9]{10}", mobile_value):
                    field_errors["mobile"] = "Invalid mobile number format."

                if secondary_email_value:
                    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", secondary_email_value):
                        field_errors["secondary_email"] = "Invalid secondary email format."

                if gstin_value and pan_value:
                    gstin_pan = gstin_value[2:12]
                    if gstin_pan != pan_value:
                        field_errors["pan"] = "PAN does not match GSTIN."

                duplicate_row = await conn.fetchrow(
                    f"""
                    SELECT
                        CASE
                            WHEN $1::text IS NULL OR trim($1::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE gstin IS NOT NULL
                                   AND upper(trim(gstin)) = upper(trim($1::text))
                            )
                        END AS gstin_match,
                        CASE
                            WHEN $2::text IS NULL OR trim($2::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE username IS NOT NULL
                                   AND lower(trim(username)) = lower(trim($2::text))
                            )
                        END AS username_match,
                        CASE
                            WHEN $3::text IS NULL OR trim($3::text) = '' OR $4::text IS NULL OR trim($4::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE is_active = TRUE
                                   AND upper(trim(gstin)) = upper(trim($3::text))
                                   AND mobile = trim($4::text)
                            )
                        END AS gstin_mobile_match
                    """,
                    gstin_value,
                    username_value,
                    gstin_value,
                    mobile_value,
                )

                has_duplicate = False
                if duplicate_row:
                    if duplicate_row["gstin_match"]:
                        field_errors["gstin"] = "GSTIN already exists."
                        has_duplicate = True
                    if duplicate_row["username_match"]:
                        field_errors["username"] = "Username already exists."
                        has_duplicate = True

                if payload.customer_id is not None:
                    if not await _customer_exists_and_active(conn, payload.customer_id):
                        field_errors["customer_id"] = (
                            "Customer not found or inactive."
                        )

                if field_errors:
                    raise HTTPException(
                        status_code=409 if has_duplicate else 400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": field_errors,
                            }
                        },
                    )

                if rm_id is None:
                    raise HTTPException(
                        status_code=400,
                        detail="rm_id is required (or sign in as RM to default rm_id to yourself).",
                    )

                approved_at_val = (
                    now
                    if str(payload.registration_status).strip().upper() == "APPROVED"
                    else None
                )

                # --------------------------------------------------
                # INSERT GST (column order aligned with solvetax.gst_registration ddl)
                # --------------------------------------------------
                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.gst_registration (
                        customer_id,
                        gstin,
                        username,
                        {_gst_reg_sql_col("password")},
                        pan,
                        mobile,
                        {_gst_reg_sql_col("language")},
                        state,
                        business_name,
                        registration_type,
                        ownership_category,
                        business_type,
                        turnover_details,
                        registration_status,
                        suspension_reason,
                        cancellation_reason,
                        approved_at,
                        is_rcm_applicable,
                        is_active,
                        created_by,
                        rm_id,
                        email,
                        secondary_email,
                        is_filing_needed,
                        filing_preference,
                        referral_id,
                        referral_entity,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                        $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                        $21,$22,$23,$24,$25,$26,$27,$28,$29
                    )
                    RETURNING *
                """

                gst_row = await conn.fetchrow(
                    insert_sql,
                    payload.customer_id,
                    gstin_value,
                    username_value,
                    payload.password,
                    pan_value,
                    mobile_value,
                    payload.language,
                    payload.state,
                    payload.business_name,
                    payload.registration_type,
                    payload.ownership_category,
                    payload.business_type,
                    payload.turnover_details,
                    payload.registration_status,
                    payload.suspension_reason,
                    payload.cancellation_reason,
                    approved_at_val,
                    payload.is_rcm_applicable,
                    True,
                    created_by_val,
                    rm_id,
                    payload.email,
                    secondary_email_value,
                    payload.is_filing_needed,
                    getattr(payload, "filing_preference", None),
                    payload.referral_id,
                    payload.referral_entity,
                    now,
                    now,
                )

                if not gst_row:
                    raise HTTPException(500, "GST registration creation failed.")

                # --------------------------------------------------
                # VERSION LOG
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
                    "GST_REGISTRATION",
                    gst_row["id"],
                    gst_row.get("customer_id"),
                    "CREATE",
                    json.dumps(dict(gst_row), default=str),
                    None,
                )
            await _invalidate_gst_registration_cache(
                gst_row.get("customer_id"),
                gst_row.get("id"),
            )

            return {
                **dict(gst_row),
                "message": "GST registration created successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            UNIQUE_MAP = {
                "gst_registration_gstin_key": ("gstin", "GSTIN already exists."),
                "uq_gst_username_lower": ("username", "Username already exists."),
                "uq_gst_gstin_mobile_active": ("mobile", "Mobile already mapped to GST.")
            }

            field, message = UNIQUE_MAP.get(
                constraint,
                ("non_field_error", "Duplicate value violates unique constraint.")
            )

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {
                            field: message
                        }
                    }
                }
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(400, "Invalid foreign key reference.")

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_gst_format": ("gstin", "Invalid GSTIN format."),
                "chk_pan_format": ("pan", "Invalid PAN format."),
                "chk_mobile_format": ("mobile", "Invalid mobile number format."),
                "chk_secondary_email_format": ("secondary_email", "Invalid secondary email format."),
                "chk_gstin_pan_match": ("pan", "PAN does not match GSTIN."),
                "chk_approved_logic": ("registration_status", "Invalid approved status logic."),
            }

            field, message = CHECK_MAP.get(
                constraint,
                ("non_field_error", f"Data violates constraint: {constraint}")
            )

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {
                            field: message
                        }
                    }
                }
            )

        except asyncpg.PostgresError:
            log.exception("Database error during GST registration create")
            raise HTTPException(500, "Database error.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST registration create")
            raise HTTPException(500, "Internal server error.")
# -------------------------------------------------------------------
# FILTER GST REGISTRATIONS (ENTERPRISE PRODUCTION READY)
# -------------------------------------------------------------------
@router.get(
    "/dynamic_filter",
    summary="Filter GST Registrations",
    responses={
        200: {"description": "GST registrations filtered successfully."},
        400: {"description": "Validation failed (e.g. invalid date range)."},
        500: {"description": "Database or internal error."},
    },
)
async def list_gst_registrations(
    gst_registration_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    gstin: Optional[str] = None,
    gstin_is_null: Optional[bool] = None,
    mobile: Optional[str] = None,
    mobile_is_null: Optional[bool] = None,
    email: Optional[str] = None,
    email_is_null: Optional[bool] = None,
    secondary_email: Optional[str] = None,
    secondary_email_is_null: Optional[bool] = None,
    rm_id: Optional[int] = None,
    created_by: Optional[int] = None,
    business_name: Optional[str] = None,
    business_name_is_null: Optional[bool] = None,
    business_type: Optional[str] = None,
    registration_status: Optional[str] = None,
    ownership_category: Optional[str] = None,
    state: Optional[str] = None,
    language: Optional[str] = None,
    referral_id: Optional[int] = None,
    referral_entity: Optional[str] = None,
    filing_preference: Optional[str] = None,  # ✅ ADDED
    has_service: Optional[bool] = None,       # ✅ ADDED
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = str(uuid.uuid4())

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    role = current_user.get("role")

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming GST filter | limit=%s offset=%s", limit, offset)

    # --------------------------------------------------
    # 🔥 ADDED VALIDATIONS (NO REMOVAL)
    # --------------------------------------------------

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
        )

    # ✅ TIMEZONE NORMALIZATION
    def normalize_dt(dt):
        if dt and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    from_date = normalize_dt(from_date)
    to_date = normalize_dt(to_date)

    # ✅ SAFE NORMALIZATION
    gstin = gstin.strip().upper() if gstin else None
    mobile = mobile.strip() if mobile else None
    email = email.strip().lower() if email else None
    secondary_email = secondary_email.strip().lower() if secondary_email else None

    # ✅ ENUM VALIDATIONS
    valid_registration_status = {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED"}
    if registration_status and registration_status.strip().upper() not in valid_registration_status:
        raise HTTPException(400, "Invalid registration_status")

    valid_business_types = {"PROPRIETORSHIP", "PARTNERSHIP", "COMPANY", "LLP"}
    if business_type and business_type.strip().upper() not in valid_business_types:
        raise HTTPException(400, "Invalid business_type")

    valid_ownership = {"INDIVIDUAL", "COMPANY", "PARTNERSHIP"}
    if ownership_category and ownership_category.strip().upper() not in valid_ownership:
        raise HTTPException(400, "Invalid ownership_category")

    valid_filing_pref = {"MONTHLY", "QUARTERLY"}
    if filing_preference and filing_preference.strip().upper() not in valid_filing_pref:
        raise HTTPException(400, "Invalid filing_preference")
    role_norm = str(role).strip().upper() if role is not None else None
    business_name_clean = business_name.strip() if business_name and business_name.strip() else None
    business_type_norm = business_type.strip().upper() if business_type and business_type.strip() else None
    registration_status_norm = registration_status.strip().upper() if registration_status and registration_status.strip() else None
    ownership_category_norm = ownership_category.strip().upper() if ownership_category and ownership_category.strip() else None
    state_norm = state.strip().upper() if state and state.strip() else None
    language_norm = language.strip().upper() if language and language.strip() else None
    referral_entity_norm = (
        referral_entity.strip().upper() if referral_entity and referral_entity.strip() else None
    )
    filing_preference_norm = filing_preference.strip().upper() if filing_preference and filing_preference.strip() else None
    cache_key = build_cache_key(
        "gst_registration:filter",
        gst_registration_id=gst_registration_id,
        customer_id=customer_id,
        gstin=gstin,
        gstin_is_null=gstin_is_null,
        mobile=mobile,
        mobile_is_null=mobile_is_null,
        email=email,
        email_is_null=email_is_null,
        secondary_email=secondary_email,
        secondary_email_is_null=secondary_email_is_null,
        rm_id=rm_id,
        created_by=created_by,
        business_name=business_name_clean,
        business_name_is_null=business_name_is_null,
        business_type=business_type_norm,
        registration_status=registration_status_norm,
        ownership_category=ownership_category_norm,
        state=state_norm,
        language=language_norm,
        referral_id=referral_id,
        referral_entity=referral_entity_norm,
        filing_preference=filing_preference_norm,
        has_service=has_service,
        is_active=is_active,
        include_inactive=include_inactive,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
        role=role_norm,
        emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async def _load_list_gst_registrations():
        conditions = []
        values = []
        param_index = 1

        join_customer_services = False  # ✅ ADDED

        # --------------------------------------------------
        # Indexed Exact Match Filters
        # --------------------------------------------------

        if gst_registration_id is not None:
            conditions.append(f"g.id = ${param_index}")
            values.append(gst_registration_id)
            param_index += 1

        if customer_id is not None:
            conditions.append(f"g.customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if gstin_is_null:
            conditions.append("g.gstin IS NULL")
        elif gstin:
            conditions.append(f"upper(g.gstin) = ${param_index}")
            values.append(gstin)
            param_index += 1

        if mobile_is_null:
            conditions.append("g.mobile IS NULL")
        elif mobile:
            conditions.append(f"g.mobile = ${param_index}")
            values.append(mobile)
            param_index += 1

        if email_is_null:
            conditions.append("g.email IS NULL")
        elif email:
            conditions.append(f"lower(g.email) = ${param_index}")
            values.append(email)
            param_index += 1

        if secondary_email_is_null:
            conditions.append("g.secondary_email IS NULL")
        elif secondary_email:
            conditions.append(f"lower(g.secondary_email) = ${param_index}")
            values.append(secondary_email)
            param_index += 1

        if rm_id is not None:
            conditions.append(f"g.rm_id = ${param_index}")
            values.append(rm_id)
            param_index += 1

        if created_by is not None:
            conditions.append(f"g.created_by = ${param_index}")
            values.append(created_by)
            param_index += 1

        if business_name_is_null:
            conditions.append("g.business_name IS NULL")

        elif business_name_clean:
            conditions.append(
                f"""(
                    g.business_name ILIKE ${param_index}
                    OR similarity(g.business_name, ${param_index + 1}) >= 0.8
                )"""
            )
            values.append(f"%{business_name_clean}%")
            values.append(business_name_clean)
            param_index += 2

        if business_type_norm:
            conditions.append(f"g.business_type = ${param_index}")
            values.append(business_type_norm)
            param_index += 1

        if registration_status_norm:
            conditions.append(f"g.registration_status = ${param_index}")
            values.append(registration_status_norm)
            param_index += 1

        if ownership_category_norm:
            conditions.append(f"g.ownership_category = ${param_index}")
            values.append(ownership_category_norm)
            param_index += 1

        if state_norm:
            conditions.append(f"g.state = ${param_index}")
            values.append(state_norm)
            param_index += 1

        if language_norm:
            conditions.append(f"g.{_gst_reg_sql_col('language')} = ${param_index}")
            values.append(language_norm)
            param_index += 1

        if referral_id is not None:
            conditions.append(f"g.referral_id = ${param_index}")
            values.append(referral_id)
            param_index += 1

        if referral_entity_norm:
            conditions.append(f"g.referral_entity = ${param_index}")
            values.append(referral_entity_norm)
            param_index += 1

        if filing_preference_norm:
            conditions.append(f"g.filing_preference = ${param_index}")
            values.append(filing_preference_norm)
            param_index += 1

        if has_service is not None:
            join_customer_services = True
            if has_service:
                conditions.append("cs.entity_id IS NOT NULL")
            else:
                conditions.append("cs.entity_id IS NULL")

        if is_active is not None:
            conditions.append(f"g.is_active = ${param_index}")
            values.append(is_active)
            param_index += 1
        elif not include_inactive:
            conditions.append("g.is_active = TRUE")

        if from_date:
            conditions.append(f"g.created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"g.created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        # --------------------------------------------------
        # ROLE BASED VISIBILITY
        # --------------------------------------------------

        visibility_sql, visibility_values, param_index = build_gst_visibility(
            role_norm,
            emp_id,
            param_index,
            DB_SCHEMA,
        )

        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # --------------------------------------------------
        # JOIN (FIXED DUPLICATE ISSUE)
        # --------------------------------------------------

        join_sql = ""
        if join_customer_services:
            join_sql = f"""
            LEFT JOIN (
                SELECT DISTINCT entity_id
                FROM {DB_SCHEMA}.customer_services
                WHERE entity_type = 'GST_REGISTRATION'
                  AND status = 'ACTIVE'
            ) cs ON cs.entity_id = g.id
            """

        count_sql = f"""
            SELECT COUNT(1)
              FROM {DB_SCHEMA}.gst_registration g
              {join_sql}
              {where_clause}
        """

        data_sql = f"""
            SELECT g.*,
                   e_rm.first_name AS rm_name,
                   e_creator.first_name AS created_by_name
              FROM {DB_SCHEMA}.gst_registration g
              LEFT JOIN {DB_SCHEMA}.employees e_rm
                     ON g.rm_id = e_rm.emp_id
              LEFT JOIN {DB_SCHEMA}.employees e_creator
                     ON g.created_by = e_creator.emp_id
              {join_sql}
              {where_clause}
             ORDER BY g.created_at DESC, g.id DESC
             LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        try:
            async with pool.acquire() as conn:
                total_count = await conn.fetchval(count_sql, *values)
                rows = await conn.fetch(data_sql, *values_with_pagination)

            log.info(
                "GST filter success | returned=%s total=%s",
                len(rows),
                total_count,
            )

            return {
                "data": [dict(row) for row in rows],
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "request_id": request_id,
            }

        except asyncpg.PostgresError as e:
            log.error(
                "Database error during GST filtering | error=%s",
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
            log.exception("Unexpected error during GST filtering")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_list_gst_registrations,
        ttl_seconds=300,
        tags=[_gst_filter_tag()],
    )


# -------------------------------------------------------------------
# FULL GST REGISTRATION BUNDLE (registration row + persons + documents + services)
# -------------------------------------------------------------------
@router.get(
    "/{registration_id}/full",
    summary="Get full GST registration by registration id",
    responses={
        200: {"description": "Registration bundle returned."},
        404: {"description": "Not found or not visible for current user."},
        500: {"description": "Database or internal error."},
    },
)
async def get_gst_registration_full(
    registration_id: int,
    include_inactive: bool = Query(
        False,
        description="When true, include inactive persons and documents.",
    ),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Returns the `gst_registration` row (with RM/creator names), all linked
    `gst_registration_persons`, `gst_registration_documents`, and
    `customer_services` for `entity_type = 'GST_REGISTRATION'`.

    `registration_id` is the primary key `gst_registration.id`.
    """
    request_id = str(uuid.uuid4())
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_gst_registration_full"},
    )

    cache_key = build_cache_key(
        "gst_registration:detail",
        registration_id=registration_id,
        include_inactive=include_inactive,
        role=role_norm,
        emp_id=emp_id,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async def _load_gst_registration_full():
        visibility_sql, visibility_values, _next = build_gst_visibility(
            role_norm,
            emp_id,
            2,
            DB_SCHEMA,
        )
        reg_values: List = [registration_id]
        vis_clause = ""
        if visibility_sql:
            vis_clause = f" AND ({visibility_sql})"
            reg_values.extend(visibility_values)

        reg_sql = f"""
            SELECT g.*,
                   e_rm.first_name AS rm_name,
                   e_creator.first_name AS created_by_name
              FROM {DB_SCHEMA}.gst_registration g
              LEFT JOIN {DB_SCHEMA}.employees e_rm
                     ON g.rm_id = e_rm.emp_id
              LEFT JOIN {DB_SCHEMA}.employees e_creator
                     ON g.created_by = e_creator.emp_id
             WHERE g.id = $1
             {vis_clause}
             LIMIT 1
        """

        person_active = "" if include_inactive else " AND p.is_active = TRUE"
        doc_active = ""
        if not include_inactive:
            doc_active = " AND p.is_active = TRUE AND d.is_active = TRUE"

        persons_sql = f"""
            SELECT p.*,
                   g.rm_id,
                   g.created_by,
                   e_rm.first_name AS rm_name,
                   e_creator.first_name AS created_by_name
              FROM {DB_SCHEMA}.gst_registration_persons p
              JOIN {DB_SCHEMA}.gst_registration g
                    ON p.gst_registration_id = g.id
              LEFT JOIN {DB_SCHEMA}.employees e_rm
                     ON g.rm_id = e_rm.emp_id
              LEFT JOIN {DB_SCHEMA}.employees e_creator
                     ON g.created_by = e_creator.emp_id
             WHERE p.gst_registration_id = $1
             {person_active}
             ORDER BY p.created_at ASC NULLS LAST, p.person_id ASC
        """

        documents_sql = f"""
            SELECT d.*,
                   p.full_name,
                   g.rm_id,
                   g.created_by,
                   e_rm.first_name AS rm_name,
                   e_creator.first_name AS created_by_name,
                   e_verify.first_name AS verified_by_name
              FROM {DB_SCHEMA}.gst_registration_documents d
              JOIN {DB_SCHEMA}.gst_registration_persons p
                    ON d.person_id = p.person_id
              JOIN {DB_SCHEMA}.gst_registration g
                    ON p.gst_registration_id = g.id
              LEFT JOIN {DB_SCHEMA}.employees e_rm
                     ON g.rm_id = e_rm.emp_id
              LEFT JOIN {DB_SCHEMA}.employees e_creator
                     ON g.created_by = e_creator.emp_id
              LEFT JOIN {DB_SCHEMA}.employees e_verify
                     ON d.verified_by = e_verify.emp_id
             WHERE p.gst_registration_id = $1
             {doc_active}
             ORDER BY d.created_at ASC NULLS LAST, d.document_id ASC
        """

        services_sql = f"""
            SELECT *
              FROM {DB_SCHEMA}.customer_services
             WHERE entity_type = 'GST_REGISTRATION'
               AND entity_id = $1
             ORDER BY created_at DESC NULLS LAST
        """

        try:
            async with pool.acquire() as conn:
                reg_row = await conn.fetchrow(reg_sql, *reg_values)
                if not reg_row:
                    raise HTTPException(
                        status_code=404,
                        detail="GST registration not found or not accessible.",
                    )
                persons = await conn.fetch(persons_sql, registration_id)
                documents = await conn.fetch(documents_sql, registration_id)
                services = await conn.fetch(services_sql, registration_id)
        except HTTPException:
            raise
        except asyncpg.PostgresError:
            log.exception("Database error loading GST registration bundle")
            raise HTTPException(status_code=500, detail="Database error.")

        return {
            "registration": dict(reg_row),
            "persons": [dict(r) for r in persons],
            "documents": [dict(r) for r in documents],
            "customer_services": [dict(r) for r in services],
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_gst_registration_full,
        ttl_seconds=300,
        tags=[_gst_detail_tag(registration_id), _gst_filter_tag()],
    )


# -------------------------------------------------------------------
# CUSTOMER SNAPSHOT FOR GST (from customers.customer_id)
# -------------------------------------------------------------------
@router.get(
    "/customer/{customer_id}/fields",
    response_model=CustomerSnapshotForGstOut,
    summary="Get customer fields for GST registration",
    responses={
        200: {"description": "Customer fields returned."},
        400: {"description": "Customer inactive."},
        404: {"description": "Customer not found or not visible for current user."},
        500: {"description": "Database or internal error."},
    },
)
async def get_customer_fields_for_gst(
    customer_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    Returns `business_name`, `business_type`, `state`, `language`, `op_id`, `rm_id`,
    `rm_name`, `op_name`, `mobile`
    from `customers` where `customers.customer_id` = `customer_id`.
    Visibility matches customer list (RM/OP/manager scoping).
    """
    request_id = str(uuid.uuid4())
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_customer_fields_for_gst"},
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    vis_sql, vis_vals, _next_idx = build_customer_visibility(role_norm, emp_id, 2, DB_SCHEMA)
    values = [customer_id]
    where_extra = ""
    if vis_sql:
        where_extra = f" AND ({vis_sql})"
        values.extend(vis_vals)

    sql = f"""
        SELECT c.customer_id,
               c.business_name,
               c.business_type,
               c.state,
               c.language,
               c.op_id,
               c.rm_id,
               c.mobile,
               c.is_active,
               e_rm.first_name AS rm_name,
               e_op.first_name AS op_name
        FROM {DB_SCHEMA}.customers c
        LEFT JOIN {DB_SCHEMA}.employees e_rm ON e_rm.emp_id = c.rm_id
        LEFT JOIN {DB_SCHEMA}.employees e_op ON e_op.emp_id = c.op_id
        WHERE c.customer_id = $1
        {where_extra}
        LIMIT 1
    """
    cache_key = build_cache_key(
        "gst_registration:customer_fields",
        customer_id=customer_id,
        role=role_norm,
        emp_id=emp_id,
    )

    async def _load_customer_fields_for_gst():
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(sql, *values)
        except asyncpg.PostgresError:
            log.exception("Database error fetching customer snapshot for GST")
            raise HTTPException(status_code=500, detail="Database error.")

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Customer not found or not accessible.",
            )

        if not row["is_active"]:
            raise HTTPException(status_code=400, detail="Customer is inactive.")

        return {
            "customer_id": row["customer_id"],
            "business_name": row["business_name"],
            "business_type": row["business_type"],
            "state": row["state"],
            "language": row["language"],
            "op_id": row["op_id"],
            "rm_id": row["rm_id"],
            "rm_name": row["rm_name"],
            "op_name": row["op_name"],
            "mobile": row["mobile"],
        }

    cached = await redis_get_or_set_json(
        cache_key,
        loader=_load_customer_fields_for_gst,
        ttl_seconds=300,
        tags=[_gst_customer_fields_tag(customer_id)],
    )
    return CustomerSnapshotForGstOut(**cached)


# -------------------------------------------------------------------
# EDIT GST REGISTRATION (Enterprise Production + Version Audit)
# -------------------------------------------------------------------
@router.post(
    "/{gst_id}/edit",
    summary="Edit GST Registration (Production Ready + Version Audit)",
    responses={
        200: {"description": "GST registration updated successfully."},
        400: {"description": "Validation failed or invalid reference."},
        404: {"description": "GST registration not found or inactive."},
        409: {"description": "Duplicate field value."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_gst_registration(
    gst_id: int,
    payload: GSTRegistrationEditIn,
    current_user=Depends(require_permission("USER_ACCESS", "WRITE")),
):
    """
    ✔ Dynamic update
    ✔ Only active GST can be updated
    ✔ ID-based architecture (no GSTIN cascade)
    ✔ Version audit
    ✔ DB constraint aligned
    ✔ Trigger-safe (approved_at controlled by DB)
    ✔ Concurrency safe (FOR UPDATE)
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "edit_gst_registration"},
    )

    log.info("Incoming GST edit request | gst_id=%s", gst_id)

    # --------------------------------------------------
    # Extract Payload
    # --------------------------------------------------
    try:
        update_data = payload.model_dump(exclude_unset=True)
    except Exception:
        log.exception("Payload serialization failed")
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not update_data:
        raise HTTPException(status_code=400, detail="At least one field must be provided for update.")

    update_data.pop("approved_at", None)  # Never allow manual update

    # --------------------------------------------------
    # 🔥 ADDED (1): NORMALIZATION BEFORE DUPLICATE CHECK
    # --------------------------------------------------
    def normalize(k, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            if k in ["gstin", "pan"]:
                return v.upper()
            if k in ["email", "secondary_email"]:
                return v.lower()
        return v

    update_data = {k: normalize(k, v) for k, v in update_data.items()}

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
                # 1️⃣ Fetch Existing GST (ACTIVE ONLY + LOCK)
                # --------------------------------------------------
                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE id = $1
                       AND is_active = TRUE
                     FOR UPDATE
                    """,
                    gst_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail="GST registration not found or inactive, First Activate the GST to edit",
                    )

                # --------------------------------------------------
                # Pre-validation (format + duplicates) for edit
                # --------------------------------------------------
                field_errors = {}

                gstin_value = update_data.get("gstin", old_row.get("gstin"))
                pan_value = update_data.get("pan", old_row.get("pan"))
                mobile_value = update_data.get("mobile", old_row.get("mobile"))
                username_value = update_data.get("username", old_row.get("username"))
                secondary_email_value = update_data.get("secondary_email", old_row.get("secondary_email"))

                if gstin_value:
                    gstin_value = gstin_value.strip().upper()
                if pan_value:
                    pan_value = pan_value.strip().upper()
                if mobile_value:
                    mobile_value = mobile_value.strip()
                if username_value:
                    username_value = username_value.strip()
                if secondary_email_value:
                    secondary_email_value = secondary_email_value.strip().lower()

                if gstin_value and not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]", gstin_value):
                    field_errors["gstin"] = "Invalid GSTIN format."

                if pan_value and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan_value):
                    field_errors["pan"] = "Invalid PAN format."

                if mobile_value and not re.fullmatch(r"[0-9]{10}", mobile_value):
                    field_errors["mobile"] = "Invalid mobile number format."

                if secondary_email_value:
                    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", secondary_email_value):
                        field_errors["secondary_email"] = "Invalid secondary email format."

                if gstin_value and pan_value:
                    gstin_pan = gstin_value[2:12]
                    if gstin_pan != pan_value:
                        field_errors["pan"] = "PAN does not match GSTIN."

                duplicate_row = await conn.fetchrow(
                    f"""
                    SELECT
                        CASE
                            WHEN $1::text IS NULL OR trim($1::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE id <> $5
                                   AND gstin IS NOT NULL
                                   AND upper(trim(gstin)) = upper(trim($1::text))
                            )
                        END AS gstin_match,
                        CASE
                            WHEN $2::text IS NULL OR trim($2::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE id <> $5
                                   AND username IS NOT NULL
                                   AND lower(trim(username)) = lower(trim($2::text))
                            )
                        END AS username_match,
                        CASE
                            WHEN $3::text IS NULL OR trim($3::text) = '' OR $4::text IS NULL OR trim($4::text) = '' THEN FALSE
                            ELSE EXISTS(
                                SELECT 1
                                  FROM {DB_SCHEMA}.gst_registration
                                 WHERE id <> $5
                                   AND is_active = TRUE
                                   AND upper(trim(gstin)) = upper(trim($3::text))
                                   AND mobile = trim($4::text)
                            )
                        END AS gstin_mobile_match
                    """,
                    gstin_value,
                    username_value,
                    gstin_value,
                    mobile_value,
                    gst_id,
                )

                has_duplicate = False
                if duplicate_row:
                    if duplicate_row["gstin_match"]:
                        field_errors["gstin"] = "GSTIN already exists."
                        has_duplicate = True
                    if duplicate_row["username_match"]:
                        field_errors["username"] = "Username already exists."
                        has_duplicate = True

                if "customer_id" in update_data and update_data["customer_id"] is not None:
                    if not await _customer_exists_and_active(conn, update_data["customer_id"]):
                        field_errors["customer_id"] = (
                            "Customer not found or inactive."
                        )

                if field_errors:
                    raise HTTPException(
                        status_code=409 if has_duplicate else 400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": field_errors,
                            }
                        },
                    )

                # --------------------------------------------------
                # 🔥 ADDED (2): SAFE NO CHANGE CHECK
                # --------------------------------------------------
                no_change = True
                for k, v in update_data.items():
                    if k in old_row and str(old_row[k]).strip() != str(v).strip():
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
                # 3️⃣ Dynamic Update
                # --------------------------------------------------
                fields, values, idx = [], [], 1

                for k, v in update_data.items():
                    fields.append(f"{_gst_reg_sql_col(k)} = ${idx}")
                    values.append(v)
                    idx += 1

                fields.append("updated_at = NOW()")
                values.append(gst_id)

                sql = f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET {', '.join(fields)}
                     WHERE id = ${idx}
                       AND is_active = TRUE
                     RETURNING *
                """

                new_row = await conn.fetchrow(sql, *values)

                if not new_row:
                    raise HTTPException(
                        status_code=409,
                        detail="GST state changed. Please retry.",
                    )

                # Keep shared GST filing fields synced for active filings linked to this registration.
                registration_to_filing = {
                    "gstin": "gstin",
                    "taxpayer_type": "taxpayer_type",
                    "turnover_details": "turnover_details",
                    "filing_preference": "filing_frequency",
                    "state": "state",
                    "language": "language",
                    "registration_status": "gst_reg_status",
                    "username": "username",
                    "password": "password",
                    "business_name": "business_name",
                    "business_type": "business_type",
                    "business_description": "business_description",
                }
                filing_fields = []
                filing_values = []
                filing_idx = 1
                for reg_key, filing_col in registration_to_filing.items():
                    if reg_key in update_data:
                        filing_fields.append(f"{filing_col} = ${filing_idx}")
                        filing_values.append(update_data[reg_key])
                        filing_idx += 1
                if filing_fields:
                    if "filing_preference" in update_data and update_data["filing_preference"]:
                        filing_fields.append(
                            f"service_id = CASE WHEN ${filing_idx} = 'MONTHLY' THEN 4 "
                            f"WHEN ${filing_idx} = 'QUARTERLY' THEN 5 ELSE service_id END"
                        )
                        filing_values.append(update_data["filing_preference"])
                        filing_idx += 1
                    filing_fields.append("updated_at = NOW()")
                    filing_values.append(gst_id)
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_filings
                        SET {', '.join(filing_fields)}
                        WHERE gst_registration_id = ${filing_idx}
                          AND is_active = TRUE
                        """,
                        *filing_values,
                    )

                # If GST edit changes filing-driving fields, rebuild linked filing return schedules.
                if ("turnover_details" in update_data) or (
                    "filing_preference" in update_data and update_data.get("filing_preference")
                ):
                    IST = ZoneInfo("Asia/Kolkata")
                    now_ist = datetime.now(IST)
                    group_2_states = {
                        "DELHI", "UTTAR_PRADESH", "BIHAR", "WEST_BENGAL", "ODISHA",
                        "JHARKHAND", "CHHATTISGARH", "MADHYA_PRADESH", "RAJASTHAN",
                        "HARYANA", "PUNJAB", "HIMACHAL_PRADESH", "UTTARAKHAND",
                        "JAMMU_AND_KASHMIR", "LADAKH", "SIKKIM", "ARUNACHAL_PRADESH",
                        "NAGALAND", "MANIPUR", "MIZORAM", "TRIPURA", "MEGHALAYA",
                        "ASSAM", "CHANDIGARH",
                    }
                    linked_filings = await conn.fetch(
                        f"""
                        SELECT *
                        FROM {DB_SCHEMA}.gst_filings
                        WHERE gst_registration_id = $1
                          AND is_active = TRUE
                        FOR UPDATE
                        """,
                        gst_id,
                    )
                    for filing in linked_filings:
                        prior_n = await count_active_return_details(conn, filing["id"])
                        explicit_template = infer_explicit_template_from_prior_row_count(
                            prior_n,
                            filing["filing_category"],
                            filing["taxpayer_type"],
                            filing["filing_frequency"],
                        )
                        await rebuild_return_details_for_filing(
                            conn,
                            filing_id=filing["id"],
                            filing_category=filing["filing_category"],
                            filing_frequency=filing["filing_frequency"],
                            taxpayer_type=filing["taxpayer_type"],
                            turnover_details=filing["turnover_details"],
                            state=filing["state"],
                            filing_period=filing["filing_period"] or "",
                            group_2_states=group_2_states,
                            ist=IST,
                            now=now_ist,
                            explicit_filing_period=explicit_template,
                            is_auto_enabled=bool(filing["is_auto_enabled"]),
                            supersede_with_is_current=True,
                        )

                # --------------------------------------------------
                # 4️⃣ Version Audit
                # --------------------------------------------------
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id,
                     action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "GST_REGISTRATION",
                    new_row["id"],
                    new_row.get("customer_id"),
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

                log.info(
                    "GST updated successfully | gst_id=%s | fields=%s",
                    gst_id,
                    list(update_data.keys()),
                )
                await _invalidate_gst_registration_cache(
                    new_row.get("customer_id"),
                    new_row.get("id"),
                )

                return {
                    **dict(new_row),
                    "message": "GST registration updated successfully.",
                    "request_id": request_id,
                }

        # --------------------------------------------------
        # UNIQUE CONSTRAINTS
        # --------------------------------------------------
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "")

            UNIQUE_MAP = {
                "gst_registration_gstin_key": ("gstin", "GSTIN already exists."),
                "uq_gst_username_lower": ("username", "Username already exists."),
                "uq_gst_gstin_mobile_active": ("mobile", "Mobile already assigned to an active GST."),
            }

            field, message = UNIQUE_MAP.get(
                constraint,
                ("non_field_error", "Duplicate value violates unique constraint.")
            )

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {
                            field: message
                        }
                    }
                }
            )

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Invalid foreign key reference provided.")

        except asyncpg.exceptions.CheckViolationError as e:
            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_gst_format": ("gstin", "Invalid GSTIN format."),
                "chk_pan_format": ("pan", "Invalid PAN format."),
                "chk_mobile_format": ("mobile", "Invalid mobile number format."),
                "chk_secondary_email_format": ("secondary_email", "Invalid secondary email format."),
                "chk_gstin_pan_match": ("pan", "PAN does not match GSTIN."),
                "chk_approved_logic": ("registration_status", "Invalid approved status logic."),
            }

            field, message = CHECK_MAP.get(
                constraint,
                ("non_field_error", f"Data violates constraint: {constraint}")
            )

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {
                            field: message
                        }
                    }
                }
            )

        except asyncpg.exceptions.NotNullViolationError:
            raise HTTPException(status_code=400, detail="Missing required field value.")

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format provided.")

        except asyncpg.PostgresError:
            log.exception("Database error during GST update")
            raise HTTPException(status_code=500, detail="Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST update")
            raise HTTPException(status_code=500, detail="Internal server error.")

@router.delete(
    "/{gst_id}/soft_delete",
    summary="Soft delete GST registration (Enterprise + Cascade + Audit)",
    responses={
        200: {"description": "GST registration soft deleted successfully."},
        400: {"description": "Business validation failed."},
        404: {"description": "GST registration not found."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_gst_registration(
    gst_id: int,
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
            "api": "soft_delete_gst_registration",
        },
    )

    log.info("Incoming soft delete GST | gst_id=%s", gst_id)

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
                # 1️⃣ Fetch Existing GST (LOCK)
                # --------------------------------------------------
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
                    raise HTTPException(
                        status_code=404,
                        detail="GST registration not found.",
                    )

                if gst_row["is_active"] is False:
                    raise HTTPException(
                        status_code=400,
                        detail="GST registration already inactive.confirm associated persons and docs are inactivate state or not.",
                    )

                # --------------------------------------------------
                # 2️⃣ Soft Delete GST
                # --------------------------------------------------
                deleted_gst = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE id = $1
                       AND is_active = TRUE
                     RETURNING *
                    """,
                    gst_id,
                )

                if not deleted_gst:
                    raise HTTPException(
                        status_code=400,
                        detail="Unable to deactivate GST registration.",
                    )

                # --------------------------------------------------
                # 3️⃣ Cascade Soft Delete Persons
                # --------------------------------------------------
                deleted_persons = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_persons
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE gst_registration_id = $1
                       AND is_active = TRUE
                     RETURNING person_id
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 4️⃣ Cascade Soft Delete Documents
                # --------------------------------------------------
                deleted_documents = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents d
                       SET is_active = FALSE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.gst_registration_persons p
                     WHERE d.person_id = p.person_id
                       AND p.gst_registration_id = $1
                       AND d.is_active = TRUE
                     RETURNING d.document_id
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 5️⃣ Version Audit (GST ONLY)
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
                    "GST_REGISTRATION",
                    deleted_gst["id"],
                    deleted_gst["customer_id"],
                    "DELETE",
                    None,
                    None,
                )

            log.info(
                "GST soft deleted successfully | gst_id=%s | persons_deactivated=%s | documents_deactivated=%s",
                gst_id,
                len(deleted_persons),
                len(deleted_documents),
            )
            await _invalidate_gst_registration_cache(
                customer_id=None,
                registration_id=deleted_gst.get("id"),
            )

            return {
                **dict(deleted_gst),
                "persons_deactivated_count": len(deleted_persons),
                "documents_deactivated_count": len(deleted_documents),
                "message": "GST registration soft deleted successfully. "
                           "All associated persons and documents deactivated.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail="Foreign key constraint violation.",
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK constraint error")
            raise HTTPException(status_code=400, detail=str(e))

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError as e:
            log.exception("Postgres error during GST soft delete")
            raise HTTPException(status_code=500, detail=str(e))

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST soft delete")
            raise HTTPException(status_code=500, detail="Internal server error.")

@router.post(
    "/{gst_id}/activate",
    summary="Activate GST Registration (Production Ready + Audit + Cascade)",
    responses={
        200: {"description": "GST registration activated successfully."},
        400: {"description": "Validation failed or already active."},
        404: {"description": "GST registration not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def activate_gst_registration(
    gst_id: int,
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
            "api": "activate_gst_registration",
        },
    )

    log.info("Incoming GST activation | gst_id=%s", gst_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch Existing GST (LOCK)
                # --------------------------------------------------
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
                    raise HTTPException(404, "GST registration not found.")

                if gst_row["is_active"]:
                    raise HTTPException(400, "GST registration already active.")

                # --------------------------------------------------
                # 2️⃣ Activate GST
                # --------------------------------------------------
                activated_gst = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE id = $1
                       AND is_active = FALSE
                     RETURNING *
                    """,
                    gst_id,
                )

                if not activated_gst:
                    raise HTTPException(
                        409,
                        "GST state changed. Please retry.",
                    )

                # --------------------------------------------------
                # 3️⃣ Cascade Activate Persons
                # --------------------------------------------------
                activated_persons = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_persons
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE gst_registration_id = $1
                       AND is_active = FALSE
                     RETURNING person_id
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 4️⃣ Cascade Activate Documents
                # --------------------------------------------------
                activated_documents = await conn.fetch(
                    f"""
                    UPDATE {DB_SCHEMA}.gst_registration_documents d
                       SET is_active = TRUE,
                           updated_at = NOW()
                      FROM {DB_SCHEMA}.gst_registration_persons p
                     WHERE d.person_id = p.person_id
                       AND p.gst_registration_id = $1
                       AND d.is_active = FALSE
                     RETURNING d.document_id
                    """,
                    gst_id,
                )

                # --------------------------------------------------
                # 5️⃣ Version Audit
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
                    "GST_REGISTRATION",
                    activated_gst["id"],
                    activated_gst.get("customer_id"),
                    "ACTIVATE",
                    None,
                    None,
                )

            log.info(
                "GST activated successfully | gst_id=%s | persons_activated=%s | documents_activated=%s",
                gst_id,
                len(activated_persons),
                len(activated_documents),
            )
            await _invalidate_gst_registration_cache(
                customer_id=None,
                registration_id=activated_gst.get("id"),
            )

            return {
                **dict(activated_gst),
                "persons_activated_count": len(activated_persons),
                "documents_activated_count": len(activated_documents),
                "message": "GST registration activated successfully. "
                           "All associated persons and documents activated.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK ERROR")
            raise HTTPException(status_code=400, detail=str(e))

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError as e:
            log.exception("Database error during GST activation")
            raise HTTPException(status_code=500, detail=str(e))

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during GST activation")