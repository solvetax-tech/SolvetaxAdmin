import logging
import json
from datetime import datetime
from typing import List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.Income_tax.schemas import IncomeTaxIn, IncomeTaxEditIn, IncomeTaxLeadCreateIn
from backend.Income_tax.income_tax_helpers import (
    INCOME_TAX_EDITABLE_FIELDS,
    INCOME_TAX_CRM_ENTITY_TYPE,
    CRM_LEAD_STAGE_INTAKE,
    current_income_tax_year,
    default_intake_financial_year,
    income_tax_cache_ver,
    INCOME_TAX_FILTER_DEFAULT_LIMIT,
    INCOME_TAX_FILTER_MAX_LIMIT,
    income_tax_returning_columns,
    income_tax_row_to_dict,
    income_tax_select_columns,
    normalize_query_str_list,
)
from backend.crm.crm_leads_common import _fetch_valid_stage_codes, _invalidate_crm_cache
from backend.logger import logger
from backend.text_search_filters import append_fuzzy_name_filter, append_ilike_contains
from backend.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)
from backend.security.rbac import require_permission
from backend.utils import DB_SCHEMA, build_income_tax_visibility, generate_uuid, get_db_pool

router = APIRouter(prefix="/api/v1/income-tax", tags=["Income Tax"])


def _income_tax_filter_tag() -> str:
    return "income_tax:filter:index"


def _income_tax_detail_tag(income_tax_id: int) -> str:
    return f"income_tax:detail:index:{income_tax_id}"


async def _invalidate_income_tax_cache(income_tax_id: Optional[int] = None) -> None:
    await redis_invalidate_tag(_income_tax_filter_tag())
    if income_tax_id is not None:
        await redis_invalidate_tag(_income_tax_detail_tag(income_tax_id))


def _income_tax_returning_sql() -> str:
    return f"RETURNING {income_tax_returning_columns()}"


async def _check_fy_overlap_duplicate(
    conn: asyncpg.Connection,
    *,
    pan_number: Optional[str],
    mobile: str,
    financial_year: List[str],
    source_of_income: Optional[List[str]],
    exclude_id: Optional[int] = None,
) -> Optional[dict]:
    """Return field errors when an active row overlaps FY (and sources when payload includes sources)."""
    args: list = [pan_number, financial_year, mobile]
    exclude_sql = ""
    src_filter = ""

    if exclude_id is not None:
        args.append(exclude_id)
        exclude_sql = f"AND i.id <> ${len(args)}"

    if source_of_income:
        args.append(source_of_income)
        src_idx = len(args)
        src_filter = f"""
              AND i.source_of_income IS NOT NULL
              AND cardinality(i.source_of_income) > 0
              AND i.source_of_income && ${src_idx}::varchar[]
        """

    row = await conn.fetchrow(
        f"""
        SELECT EXISTS(
            SELECT 1
            FROM {DB_SCHEMA}.income_tax i
            WHERE i.is_active = TRUE
              AND $1::text IS NOT NULL
              AND upper(btrim(i.pan_number)) = upper(btrim($1::text))
              AND i.financial_year && $2::varchar[]
              {exclude_sql}
              {src_filter}
        ) AS pan_fy_match,
        EXISTS(
            SELECT 1
            FROM {DB_SCHEMA}.income_tax i
            WHERE i.is_active = TRUE
              AND $1::text IS NULL
              AND i.pan_number IS NULL
              AND btrim(i.mobile) = btrim($3::text)
              AND i.financial_year && $2::varchar[]
              {exclude_sql}
              {src_filter}
        ) AS mobile_fy_no_pan_match
        """,
        *args,
    )
    if not row:
        return None
    if row["pan_fy_match"]:
        msg = "A record already exists for this PAN with overlapping financial year(s)."
        if source_of_income:
            msg = "A record already exists for this PAN with overlapping financial year(s) and income source(s)."
        return {"pan_number": msg, "financial_year": msg}
    if row["mobile_fy_no_pan_match"]:
        msg = "A record already exists for this mobile with overlapping financial year(s) (without PAN)."
        if source_of_income:
            msg = (
                "A record already exists for this mobile with overlapping financial year(s) "
                "and income source(s) (without PAN)."
            )
        return {"mobile": msg, "financial_year": msg}
    return None


def _raise_income_tax_validation_error(fields: dict, status_code: int = 400, message: str = "Validation failed") -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "type": "validation_error",
                "message": message,
                "fields": fields,
            }
        },
    )


def _raise_income_tax_duplicate_for_edit(
    *,
    existing_income_tax_id: int,
    mobile: str,
    year: int,
    message: str,
    pan_number: str | None = None,
) -> None:
    guidance = (
        f"This client already has an active income tax record for calendar year {year}. "
        "Open that record to add or update financial years, sources of income, refund amount, "
        "filing status, and remarks — do not create a new record."
    )
    fields: dict[str, str] = {
        "year": f"Record year {year} — edit existing record (id={existing_income_tax_id}).",
    }
    if pan_number:
        fields["pan_number"] = (
            f"A record already exists for PAN {pan_number} in year {year}."
        )
    fields["mobile"] = f"A record already exists for mobile {mobile} in year {year}."

    raise HTTPException(
        status_code=409,
        detail={
            "error": {
                "type": "duplicate_record",
                "message": message,
                "guidance": guidance,
                "existing_income_tax_id": existing_income_tax_id,
                "record_year": year,
                "fields": fields,
            }
        },
    )


def _income_tax_year_match_sql(
    column_ref: str = "year",
    *,
    created_at_col: str = "created_at",
    param_ref: str = "$2",
) -> str:
    """Match calendar year on `year` column or from created_at when year was not backfilled."""
    return f"""(
          {column_ref} = {param_ref}
          OR (
              {column_ref} IS NULL
              AND EXTRACT(YEAR FROM {created_at_col} AT TIME ZONE 'Asia/Kolkata')::int = {param_ref}
          )
      )"""


async def _find_active_income_tax_by_mobile_year(
    conn: asyncpg.Connection,
    mobile: str,
    year: int,
    *,
    exclude_id: Optional[int] = None,
) -> Optional[int]:
    exclude_sql = ""
    args: list = [mobile.strip(), year]
    if exclude_id is not None:
        exclude_sql = "AND id <> $3"
        args.append(exclude_id)
    year_match = _income_tax_year_match_sql("year")
    return await conn.fetchval(
        f"""
        SELECT id
        FROM {DB_SCHEMA}.income_tax
        WHERE is_active = TRUE
          AND btrim(mobile) = btrim($1::text)
          AND {year_match}
          {exclude_sql}
        ORDER BY id DESC
        LIMIT 1
        """,
        *args,
    )


async def _find_active_income_tax_by_pan_year(
    conn: asyncpg.Connection,
    pan_number: str,
    year: int,
    *,
    exclude_id: Optional[int] = None,
) -> Optional[int]:
    exclude_sql = ""
    args: list = [pan_number.strip(), year]
    if exclude_id is not None:
        exclude_sql = "AND id <> $3"
        args.append(exclude_id)
    year_match = _income_tax_year_match_sql("year")
    return await conn.fetchval(
        f"""
        SELECT id
        FROM {DB_SCHEMA}.income_tax
        WHERE is_active = TRUE
          AND upper(btrim(pan_number)) = upper(btrim($1::text))
          AND {year_match}
          {exclude_sql}
        ORDER BY id DESC
        LIMIT 1
        """,
        *args,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create income tax record")
async def create_income_tax(
    payload: IncomeTaxIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw) and str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""
    rm_id = payload.rm_id
    if role_norm == "RM" and rm_id is None:
        rm_id = emp_id
    op_id = emp_id if role_norm == "OP" else payload.op_id
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id, "api": "create_income_tax"})

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    record_year = current_income_tax_year()

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                existing_id = await _find_active_income_tax_by_mobile_year(
                    conn, payload.mobile, record_year
                )
                if existing_id is not None:
                    _raise_income_tax_duplicate_for_edit(
                        existing_income_tax_id=int(existing_id),
                        mobile=payload.mobile,
                        year=record_year,
                        message=(
                            f"A record for this mobile already exists for year {record_year}. "
                            "Use the existing record to add financial years, income sources, and refund details."
                        ),
                    )

                if payload.pan_number:
                    existing_pan_id = await _find_active_income_tax_by_pan_year(
                        conn, payload.pan_number, record_year
                    )
                    if existing_pan_id is not None:
                        _raise_income_tax_duplicate_for_edit(
                            existing_income_tax_id=int(existing_pan_id),
                            mobile=payload.mobile,
                            year=record_year,
                            pan_number=payload.pan_number,
                            message=(
                                f"A record for this PAN already exists for year {record_year}. "
                                "Use the existing record to add financial years, income sources, and refund details."
                            ),
                        )

                dup_fields = await _check_fy_overlap_duplicate(
                    conn,
                    pan_number=payload.pan_number,
                    mobile=payload.mobile,
                    financial_year=payload.financial_year,
                    source_of_income=payload.source_of_income,
                )
                if dup_fields:
                    _raise_income_tax_validation_error(
                        dup_fields,
                        status_code=409,
                        message="Income tax request already exists for overlapping financial year(s).",
                    )

                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.income_tax (
                        client_name, mobile, language, state, priority, remarks,
                        pan_number, financial_year, filed_status,
                        referral_phone_number, email_id, source_of_income, refund_amount,
                        rm_id, op_id, year, is_active, created_at, updated_at
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,TRUE,NOW(),NOW()
                    )
                    {_income_tax_returning_sql()}
                    """,
                    payload.client_name,
                    payload.mobile,
                    payload.language,
                    payload.state,
                    payload.priority,
                    payload.remarks,
                    payload.pan_number,
                    payload.financial_year,
                    payload.filed_status,
                    payload.referral_phone_number,
                    payload.email_id,
                    payload.source_of_income,
                    payload.refund_amount,
                    rm_id,
                    op_id,
                    record_year,
                )
                if not row:
                    raise HTTPException(status_code=500, detail="Income tax record creation failed.")

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "INCOME_TAX",
                    row["id"],
                    None,
                    "CREATE",
                    json.dumps(income_tax_row_to_dict(row), default=str),
                    None,
                )
            await _invalidate_income_tax_cache(row["id"])
            return {
                "message": "Income tax record created successfully.",
                "request_id": request_id,
                "data": income_tax_row_to_dict(row),
            }
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "")
            unique_map = {
                "uq_income_tax_mobile_year_active": (
                    "mobile",
                    "A record already exists for this mobile and year.",
                ),
                "uq_income_tax_pan_financial_year_active": (
                    "pan_number",
                    "A record already exists for this PAN and financial year.",
                ),
                "income_tax_pan_number_financial_year_key": (
                    "pan_number",
                    "A record already exists for this PAN and financial year.",
                ),
                "uq_income_tax_mobile_fy_no_pan": (
                    "mobile",
                    "A record already exists for this mobile and financial year (without PAN).",
                ),
            }
            field, message = unique_map.get(
                constraint,
                ("non_field_error", "Duplicate value violates unique constraint."),
            )
            _raise_income_tax_validation_error(
                {field: message},
                status_code=409,
                message="Income tax request already exists for this financial year.",
            )
        except asyncpg.exceptions.ForeignKeyViolationError:
            _raise_income_tax_validation_error(
                {"non_field_error": "Invalid rm_id or op_id reference."},
                status_code=400,
            )
        except asyncpg.PostgresError:
            log.exception("Database error while creating income tax")
            raise HTTPException(status_code=500, detail="Database error.")


@router.post(
    "/lead",
    status_code=status.HTTP_201_CREATED,
    summary="Create income tax record and linked CRM ITR lead",
    description=(
        "Creates a minimal income_tax row and a crm_leads row with entity_type=INCOME_TAX "
        "and entity_id set to the new income_tax id (ITR funnel / push-to-lead intake)."
    ),
)
async def create_income_tax_lead(
    payload: IncomeTaxLeadCreateIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw) and str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_income_tax_lead"},
    )

    fy_values = default_intake_financial_year()
    record_year = current_income_tax_year()

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                link_existing_lead = payload.crm_lead_id is not None
                crm_lead_row = None

                if link_existing_lead:
                    # IDOR guard: only link a CRM lead the caller can actually
                    # see (same visibility as CRM list/detail). Without this an
                    # RM/OP could hijack another owner's unlinked lead by id.
                    from backend.crm.crm_leads_common import _fetch_crm_lead_visible
                    crm_lead_row = await _fetch_crm_lead_visible(
                        conn,
                        role_norm,
                        emp_id or 0,
                        payload.crm_lead_id,
                        for_update=True,
                    )
                    if not crm_lead_row:
                        raise HTTPException(status_code=404, detail="CRM lead not found.")
                    if not crm_lead_row["is_active"]:
                        _raise_income_tax_validation_error(
                            {"crm_lead_id": "Cannot push an inactive CRM lead."},
                            status_code=400,
                        )
                    lead_et = (crm_lead_row.get("entity_type") or "").strip().upper()
                    if lead_et != INCOME_TAX_CRM_ENTITY_TYPE:
                        _raise_income_tax_validation_error(
                            {
                                "crm_lead_id": (
                                    f"Lead entity_type must be {INCOME_TAX_CRM_ENTITY_TYPE}, "
                                    f"not {lead_et or 'unset'}."
                                )
                            },
                            status_code=400,
                        )
                    if crm_lead_row.get("entity_id") is not None:
                        _raise_income_tax_validation_error(
                            {
                                "crm_lead_id": (
                                    f"Lead is already linked to income tax id "
                                    f"{crm_lead_row['entity_id']}."
                                )
                            },
                            status_code=409,
                            message="This CRM lead was already pushed to ITR.",
                        )

                mobile = (payload.mobile or (crm_lead_row or {}).get("mobile") or "").strip()
                if not mobile:
                    _raise_income_tax_validation_error(
                        {"mobile": "Mobile number is required."},
                        status_code=400,
                    )

                raw_name = payload.full_name or (crm_lead_row or {}).get("full_name") or mobile
                client_name = str(raw_name).strip()[:150]
                if len(client_name) < 2:
                    client_name = mobile[:150]

                language = payload.preferred_language or (crm_lead_row or {}).get(
                    "preferred_language"
                )
                if isinstance(language, str):
                    language = language.strip().upper() or None

                email = payload.email
                if email is None and crm_lead_row is not None:
                    email = crm_lead_row.get("email")

                rm_id = payload.rm_id
                if rm_id is None and crm_lead_row is not None:
                    rm_id = crm_lead_row.get("rm_id")
                if role_norm == "RM" and rm_id is None:
                    rm_id = emp_id

                op_id = payload.op_id
                if op_id is None and crm_lead_row is not None:
                    op_id = crm_lead_row.get("op_id")
                if role_norm == "OP" and op_id is None:
                    op_id = emp_id

                default_remarks = (
                    "Pushed from CRM ITR lead."
                    if link_existing_lead
                    else "Created from ITR lead intake."
                )
                itr_remarks = payload.remarks or default_remarks

                existing_itr_id = await _find_active_income_tax_by_mobile_year(
                    conn, mobile, record_year
                )
                if existing_itr_id is not None:
                    _raise_income_tax_duplicate_for_edit(
                        existing_income_tax_id=int(existing_itr_id),
                        mobile=mobile,
                        year=record_year,
                        message=(
                            f"A record for this mobile already exists for year {record_year}. "
                            "Use the existing record or open the linked CRM lead."
                        ),
                    )

                if not link_existing_lead:
                    existing_lead = await conn.fetchrow(
                        f"""
                        SELECT id, entity_id
                        FROM {DB_SCHEMA}.crm_leads
                        WHERE is_active = TRUE
                          AND btrim(mobile) = btrim($1::text)
                          AND upper(btrim(entity_type)) = $2
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        mobile,
                        INCOME_TAX_CRM_ENTITY_TYPE,
                    )
                    if existing_lead:
                        _raise_income_tax_validation_error(
                            {
                                "mobile": (
                                    f"An active CRM ITR lead already exists for this mobile "
                                    f"(lead id={existing_lead['id']})."
                                )
                            },
                            status_code=409,
                            message="CRM ITR lead already exists for this mobile.",
                        )

                    valid_stages = await _fetch_valid_stage_codes(
                        conn, INCOME_TAX_CRM_ENTITY_TYPE
                    )
                    if valid_stages and CRM_LEAD_STAGE_INTAKE not in valid_stages:
                        _raise_income_tax_validation_error(
                            {
                                "stage": (
                                    f"{CRM_LEAD_STAGE_INTAKE} must be configured for "
                                    f"{INCOME_TAX_CRM_ENTITY_TYPE} in crm_lead_stages."
                                )
                            },
                            status_code=400,
                        )

                itr_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.income_tax (
                        client_name, mobile, language, state, priority, remarks,
                        pan_number, financial_year, filed_status,
                        referral_phone_number, email_id, source_of_income, refund_amount,
                        rm_id, op_id, year, is_active, created_at, updated_at
                    ) VALUES (
                        $1,$2,$3,NULL,'NORMAL',$4,
                        NULL,$5,'NOT_FILED',
                        NULL,$6,NULL,NULL,
                        $7,$8,$9,$10,NOW(),NOW()
                    )
                    {_income_tax_returning_sql()}
                    """,
                    client_name,
                    mobile,
                    language,
                    itr_remarks,
                    fy_values,
                    email,
                    rm_id,
                    op_id,
                    record_year,
                    True,
                )
                if not itr_row or not itr_row["is_active"]:
                    raise HTTPException(
                        status_code=500,
                        detail="Income tax record was not created as active.",
                    )

                income_tax_id = int(itr_row["id"])

                if link_existing_lead:
                    lead_row = await conn.fetchrow(
                        f"""
                        UPDATE {DB_SCHEMA}.crm_leads
                        SET entity_id = $1,
                            full_name = COALESCE(NULLIF(btrim($2::text), ''), full_name),
                            email = COALESCE($3, email),
                            preferred_language = COALESCE($4, preferred_language),
                            rm_id = COALESCE($5, rm_id),
                            op_id = COALESCE($6, op_id),
                            updated_at = NOW()
                        WHERE id = $7
                          AND is_active = TRUE
                        RETURNING *
                        """,
                        income_tax_id,
                        client_name,
                        email,
                        language,
                        rm_id,
                        op_id,
                        payload.crm_lead_id,
                    )
                    if not lead_row:
                        raise HTTPException(
                            status_code=500,
                            detail="CRM lead could not be linked to income tax.",
                        )
                else:
                    lead_row = await conn.fetchrow(
                        f"""
                        INSERT INTO {DB_SCHEMA}.crm_leads (
                            mobile,
                            full_name,
                            email,
                            entity_id,
                            entity_type,
                            preferred_language,
                            stage,
                            follow_up_status,
                            rm_id,
                            op_id,
                            remarks,
                            is_active,
                            lead_type,
                            tag,
                            lead_source,
                            created_at,
                            updated_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6,
                            $7,
                            'PENDING',
                            $8, $9,
                            $10,
                            $11,
                            NULL, NULL, NULL,
                            NOW(), NOW()
                        )
                        RETURNING *
                        """,
                        mobile,
                        client_name[:200],
                        email,
                        income_tax_id,
                        INCOME_TAX_CRM_ENTITY_TYPE,
                        language,
                        CRM_LEAD_STAGE_INTAKE,
                        rm_id,
                        op_id,
                        itr_remarks,
                        True,
                    )
                    if not lead_row or not lead_row["is_active"]:
                        raise HTTPException(
                            status_code=500,
                            detail="CRM lead was not created as active.",
                        )

                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "INCOME_TAX",
                    income_tax_id,
                    None,
                    "CREATE",
                    json.dumps(income_tax_row_to_dict(itr_row), default=str),
                    None,
                )

            lead_id = int(lead_row["id"])
            await _invalidate_income_tax_cache(income_tax_id)
            await _invalidate_crm_cache(lead_id)

            msg = (
                "Income tax record linked to CRM ITR lead successfully."
                if link_existing_lead
                else "Income tax record and CRM ITR lead created successfully."
            )
            return {
                "message": msg,
                "request_id": request_id,
                "income_tax_id": income_tax_id,
                "crm_lead_id": lead_id,
                "data": income_tax_row_to_dict(itr_row),
                "lead": dict(lead_row),
            }
        except HTTPException:
            raise
        except asyncpg.exceptions.UniqueViolationError as e:
            constraint = getattr(e, "constraint_name", "")
            if "crm" in (constraint or "").lower():
                _raise_income_tax_validation_error(
                    {"mobile": "CRM lead unique constraint violated for this mobile."},
                    status_code=409,
                    message="CRM ITR lead already exists.",
                )
            _raise_income_tax_validation_error(
                {"mobile": "Duplicate income tax record for this mobile or year."},
                status_code=409,
                message="Income tax record already exists.",
            )
        except asyncpg.exceptions.ForeignKeyViolationError:
            _raise_income_tax_validation_error(
                {"non_field_error": "Invalid rm_id or op_id reference."},
                status_code=400,
            )
        except asyncpg.PostgresError:
            log.exception("Database error while creating income tax lead")
            raise HTTPException(status_code=500, detail="Database error.")


@router.get("/filter", summary="Filter income tax records")
async def filter_income_tax(
    id: Optional[int] = None,
    mobile: Optional[str] = None,
    pan_number: Optional[str] = None,
    client_name: Optional[str] = Query(None, description="Fuzzy match on client name."),
    email_id: Optional[str] = Query(None, description="Partial match on email."),
    financial_year: Optional[List[str]] = Query(
        None,
        description="One or more FY values (e.g. 2024-25). Records matching any selected FY are returned.",
    ),
    filed_status: Optional[str] = None,
    priority: Optional[str] = None,
    language: Optional[str] = None,
    state: Optional[str] = None,
    source_of_income: Optional[List[str]] = Query(
        None,
        description="One or more income source codes/labels. Records matching any selected source are returned.",
    ),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),
    created_from: Optional[datetime] = Query(None, description="Filter records created on or after (IST-aware datetime)."),
    created_to: Optional[datetime] = Query(None, description="Filter records created on or before (IST-aware datetime)."),
    limit: int = Query(INCOME_TAX_FILTER_DEFAULT_LIMIT, ge=1, le=INCOME_TAX_FILTER_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""
    log = logging.LoggerAdapter(logger, {"request_id": request_id, "emp_id": emp_id, "api": "filter_income_tax"})

    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=400, detail="created_from must be <= created_to.")

    cache_key = build_cache_key(
        "income_tax_filter",
        ver=income_tax_cache_ver(),
        id=id,
        mobile=mobile.strip() if mobile else None,
        pan_number=pan_number.strip().upper() if pan_number else None,
        client_name=client_name.strip() if client_name else None,
        email_id=email_id.strip().lower() if email_id else None,
        financial_year=normalize_query_str_list(financial_year) or None,
        filed_status=filed_status.strip().upper() if filed_status else None,
        priority=priority.strip().upper() if priority else None,
        language=language.strip().upper() if language else None,
        state=state.strip().upper() if state else None,
        source_of_income=[s.strip().upper() for s in normalize_query_str_list(source_of_income)] or None,
        year=year,
        rm_id=rm_id,
        op_id=op_id,
        is_active=is_active,
        include_inactive=include_inactive,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
        role=role_norm,
        emp_id=emp_id,
    )

    conditions = []
    values = []
    idx = 1

    def add_eq(col, val):
        nonlocal idx
        conditions.append(f"{col} = ${idx}")
        values.append(val)
        idx += 1

    if id is not None:
        add_eq("i.id", id)
    if mobile:
        add_eq("trim(i.mobile)", mobile.strip())
    if pan_number:
        add_eq("upper(trim(i.pan_number))", pan_number.strip().upper())
    if client_name:
        idx = append_fuzzy_name_filter(conditions, values, idx, "i.client_name", client_name)
    if email_id:
        idx = append_ilike_contains(conditions, values, idx, "lower(i.email_id)", email_id)
    fy_filters = normalize_query_str_list(financial_year)
    if fy_filters:
        conditions.append(f"i.financial_year && ${idx}::varchar[]")
        values.append(fy_filters)
        idx += 1
    if filed_status:
        add_eq("i.filed_status", filed_status.strip().upper())
    if priority:
        add_eq("i.priority", priority.strip().upper())
    if language:
        add_eq("i.language", language.strip().upper())
    if state:
        idx = append_fuzzy_name_filter(conditions, values, idx, "i.state", state)
    src_filters = [s.strip().upper() for s in normalize_query_str_list(source_of_income)]
    if src_filters:
        conditions.append(
            f"EXISTS (SELECT 1 FROM unnest(i.source_of_income) AS s(v) "
            f"WHERE upper(btrim(s.v)) = ANY(${idx}::text[]))"
        )
        values.append(src_filters)
        idx += 1
    if year is not None:
        conditions.append(
            _income_tax_year_match_sql(
                "i.year",
                created_at_col="i.created_at",
                param_ref=f"${idx}",
            )
        )
        values.append(year)
        idx += 1
    if created_from:
        conditions.append(f"i.created_at >= ${idx}")
        values.append(created_from)
        idx += 1
    if created_to:
        conditions.append(f"i.created_at <= ${idx}")
        values.append(created_to)
        idx += 1
    if rm_id is not None:
        add_eq("i.rm_id", rm_id)
    if op_id is not None:
        add_eq("i.op_id", op_id)
    if is_active is not None:
        add_eq("i.is_active", is_active)
    elif not include_inactive:
        conditions.append("i.is_active = TRUE")

    visibility_sql, visibility_values, idx = build_income_tax_visibility(role_norm, emp_id, idx, DB_SCHEMA)
    if visibility_sql:
        conditions.append(f"({visibility_sql})")
        values.extend(visibility_values)

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async def _loader():
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                total = await conn.fetchval(
                    f"SELECT COUNT(*)::bigint FROM {DB_SCHEMA}.income_tax i {where_sql}",
                    *values,
                )
                rows = await conn.fetch(
                    f"""
                    SELECT {income_tax_select_columns("i")},
                           e_rm.first_name AS rm_name,
                           e_op.first_name AS op_name
                    FROM {DB_SCHEMA}.income_tax i
                    LEFT JOIN {DB_SCHEMA}.employees e_rm ON e_rm.emp_id = i.rm_id
                    LEFT JOIN {DB_SCHEMA}.employees e_op ON e_op.emp_id = i.op_id
                    {where_sql}
                    ORDER BY i.id DESC
                    LIMIT ${idx} OFFSET ${idx + 1}
                    """,
                    *values,
                    limit,
                    offset,
                )
            return {
                "items": [income_tax_row_to_dict(r) for r in rows],
                "total": int(total or 0),
                "limit": limit,
                "offset": offset,
                "request_id": request_id,
            }
        except asyncpg.PostgresError:
            log.exception("Database error while filtering income tax")
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key=cache_key,
        loader=_loader,
        ttl_seconds=300,
        tags=[_income_tax_filter_tag()],
    )


@router.get("/{income_tax_id}", summary="Get income tax record by id")
async def get_income_tax(
    income_tax_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role = current_user.get("role")
    role_norm = str(role).strip().upper() if role is not None else ""

    cache_key = build_cache_key(
        "income_tax_detail",
        ver=income_tax_cache_ver(),
        income_tax_id=income_tax_id,
        role=role_norm,
        emp_id=emp_id,
    )

    async def _loader():
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                visibility_sql, visibility_values, _next = build_income_tax_visibility(
                    role_norm,
                    emp_id,
                    2,
                    DB_SCHEMA,
                )
                conditions = ["i.id = $1"]
                args = [income_tax_id]
                if visibility_sql:
                    conditions.append(f"({visibility_sql})")
                    args.extend(visibility_values)
                row = await conn.fetchrow(
                    f"""
                    SELECT {income_tax_select_columns("i")},
                           e_rm.first_name AS rm_name,
                           e_op.first_name AS op_name
                    FROM {DB_SCHEMA}.income_tax i
                    LEFT JOIN {DB_SCHEMA}.employees e_rm ON e_rm.emp_id = i.rm_id
                    LEFT JOIN {DB_SCHEMA}.employees e_op ON e_op.emp_id = i.op_id
                    WHERE {' AND '.join(conditions)}
                    """,
                    *args,
                )
            if not row:
                raise HTTPException(status_code=404, detail="Income tax record not found.")
            return income_tax_row_to_dict(row)
        except asyncpg.PostgresError:
            raise HTTPException(status_code=500, detail="Database error.")

    return await redis_get_or_set_json(
        cache_key=cache_key,
        loader=_loader,
        ttl_seconds=300,
        tags=[_income_tax_detail_tag(income_tax_id)],
    )


@router.post("/{income_tax_id}/edit", summary="Edit income tax record")
async def edit_income_tax(
    income_tax_id: int,
    payload: IncomeTaxEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    role_norm = (current_user.get("role") or "").strip().upper()

    update_data = {
        k: v
        for k, v in payload.model_dump(exclude_unset=True).items()
        if k in INCOME_TAX_EDITABLE_FIELDS
    }
    # Mass-assignment guard: only an admin may reassign ownership (rm_id/op_id).
    if role_norm != "ADMIN":
        update_data.pop("rm_id", None)
        update_data.pop("op_id", None)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update.")

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # IDOR guard: a WRITE holder may only mutate income-tax records
                # they can see. ADMIN unrestricted; RM/OP/managers limited to
                # their own assignments — matching get-by-id read scope.
                visibility_sql, visibility_values, _vidx = build_income_tax_visibility(
                    role_norm, emp_id, 2, DB_SCHEMA,
                )
                fetch_conditions = ["i.id = $1"]
                fetch_args = [income_tax_id]
                if visibility_sql:
                    fetch_conditions.append(f"({visibility_sql})")
                    fetch_args.extend(visibility_values)
                old = await conn.fetchrow(
                    f"""
                    SELECT i.* FROM {DB_SCHEMA}.income_tax i
                    WHERE {' AND '.join(fetch_conditions)}
                    FOR UPDATE
                    """,
                    *fetch_args,
                )
                if not old:
                    raise HTTPException(status_code=404, detail="Income tax record not found.")

                if set(update_data.keys()) == {"is_active"}:
                    new_active = bool(update_data["is_active"])
                    old_active = bool(old["is_active"])
                    if new_active == old_active:
                        state = "active" if new_active else "inactive"
                        raise HTTPException(
                            status_code=400,
                            detail=f"Income tax record is already {state}.",
                        )
                    if new_active:
                        record_year = (
                            int(old["year"])
                            if old.get("year") is not None
                            else current_income_tax_year()
                        )
                        conflict_id = await _find_active_income_tax_by_mobile_year(
                            conn,
                            str(old["mobile"]),
                            record_year,
                            exclude_id=income_tax_id,
                        )
                        if conflict_id is not None:
                            _raise_income_tax_duplicate_for_edit(
                                existing_income_tax_id=int(conflict_id),
                                mobile=str(old["mobile"]),
                                year=record_year,
                                message=(
                                    f"Another active record already uses this mobile for year {record_year}. "
                                    "Deactivate or edit that record first."
                                ),
                            )
                        if old.get("pan_number"):
                            pan_conflict_id = await _find_active_income_tax_by_pan_year(
                                conn,
                                str(old["pan_number"]),
                                record_year,
                                exclude_id=income_tax_id,
                            )
                            if pan_conflict_id is not None:
                                _raise_income_tax_duplicate_for_edit(
                                    existing_income_tax_id=int(pan_conflict_id),
                                    mobile=str(old["mobile"]),
                                    year=record_year,
                                    message=(
                                        f"Another active record already uses this PAN for year {record_year}. "
                                        "Deactivate or edit that record first."
                                    ),
                                )
                    new = await conn.fetchrow(
                        f"""
                        UPDATE {DB_SCHEMA}.income_tax
                        SET is_active = $1, updated_at = NOW()
                        WHERE id = $2
                        {_income_tax_returning_sql()}
                        """,
                        new_active,
                        income_tax_id,
                    )
                    message = (
                        "Income tax record activated successfully."
                        if new_active
                        else "Income tax record deactivated successfully."
                    )
                    await _invalidate_income_tax_cache(income_tax_id)
                    return {
                        "message": message,
                        "request_id": request_id,
                        "data": income_tax_row_to_dict(new),
                    }

                pan_value = update_data.get("pan_number", old["pan_number"])
                mobile_value = update_data.get("mobile", old["mobile"])
                record_year = int(old["year"]) if old.get("year") is not None else current_income_tax_year()
                conflict_id = await _find_active_income_tax_by_mobile_year(
                    conn,
                    str(mobile_value),
                    record_year,
                    exclude_id=income_tax_id,
                )
                if conflict_id is not None:
                    _raise_income_tax_duplicate_for_edit(
                        existing_income_tax_id=int(conflict_id),
                        mobile=str(mobile_value),
                        year=record_year,
                        message=(
                            f"Another active record already uses this mobile for year {record_year}. "
                            "Edit that record instead."
                        ),
                    )
                pan_value_for_conflict = update_data.get("pan_number", old["pan_number"])
                if pan_value_for_conflict:
                    pan_conflict_id = await _find_active_income_tax_by_pan_year(
                        conn,
                        str(pan_value_for_conflict),
                        record_year,
                        exclude_id=income_tax_id,
                    )
                    if pan_conflict_id is not None:
                        _raise_income_tax_duplicate_for_edit(
                            existing_income_tax_id=int(pan_conflict_id),
                            mobile=str(mobile_value),
                            year=record_year,
                            message=(
                                f"Another active record already uses this PAN for year {record_year}. "
                                "Edit that record instead."
                            ),
                        )
                fy_value = list(update_data.get("financial_year", old["financial_year"] or []))
                src_value = update_data.get("source_of_income", old["source_of_income"])
                if src_value is not None:
                    src_value = list(src_value)

                dup_fields = await _check_fy_overlap_duplicate(
                    conn,
                    pan_number=pan_value,
                    mobile=mobile_value,
                    financial_year=fy_value,
                    source_of_income=src_value,
                    exclude_id=income_tax_id,
                )
                if dup_fields:
                    _raise_income_tax_validation_error(dup_fields, status_code=409)

                fields = []
                values = []
                idx = 1
                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1
                fields.append("updated_at = NOW()")
                values.append(income_tax_id)

                new = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.income_tax
                    SET {', '.join(fields)}
                    WHERE id = ${idx}
                    {_income_tax_returning_sql()}
                    """,
                    *values,
                )
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.versions
                    (emp_id, entity_type, entity_id, customer_id, action, json, updated_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    emp_id,
                    "INCOME_TAX",
                    income_tax_id,
                    None,
                    "UPDATE",
                    json.dumps(income_tax_row_to_dict(old), default=str),
                    json.dumps(income_tax_row_to_dict(new), default=str),
                )
        await _invalidate_income_tax_cache(income_tax_id)
        msg = "Income tax record updated successfully."
        if "is_active" in update_data:
            if bool(update_data["is_active"]):
                msg = "Income tax record activated successfully."
            else:
                msg = "Income tax record deactivated successfully."
        return {
            "message": msg,
            "request_id": request_id,
            "data": income_tax_row_to_dict(new),
        }
    except asyncpg.exceptions.UniqueViolationError as e:
        constraint = getattr(e, "constraint_name", "")
        unique_map = {
            "uq_income_tax_pan_financial_year_active": (
                "pan_number",
                "Duplicate PAN + financial year for active record.",
            ),
            "income_tax_pan_number_financial_year_key": (
                "pan_number",
                "Duplicate PAN + financial year for active record.",
            ),
        }
        field, message = unique_map.get(
            constraint,
            ("non_field_error", "Duplicate value violates unique constraint."),
        )
        _raise_income_tax_validation_error({field: message}, status_code=409)
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error.")

