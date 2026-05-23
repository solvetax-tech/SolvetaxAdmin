import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status, Request
from typing import Optional, List
from app.security.rbac import require_permission
from app.security.public_security import enforce_public_security
from app.payments.schemas import RegistrationPaymentIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid
from app.logger import logger
from app.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
from datetime import datetime
from zoneinfo import ZoneInfo
import json

router = APIRouter(
    prefix="/api/v1/payments_config",
    tags=["Payments Config"]
)


def _normalize_optional_filter(filter_value: Optional[str]) -> Optional[str]:
    if filter_value is None:
        return None
    s = filter_value.strip()
    return s if s else None


SERVICE_PRICE_SPECS = [
    {"code": "ITR_FILING", "mode": "first", "queries": [
        {"entity_type": "INCOME_TAX", "value": "DEFAULT"},
        {"entity_type": "INCOME_TAX", "value": "SALARY"},
        {"entity_type": "INCOME_TAX", "value": "BUSINESS"},
        {"entity_type": "INCOME_TAX", "value": "PROFESSION"},
        {"entity_type": "INCOME_TAX", "value": "HOUSE_PROPERTY"},
        {"entity_type": "INCOME_TAX", "value": "CAPITAL_GAINS"},
        {"entity_type": "INCOME_TAX", "value": "OTHER_SOURCES"},
        {"entity_type": "INCOME_TAX", "value": "MULTIPLE_SOURCES"},
    ]},
    {"code": "ITR_NOTICE", "mode": "first", "queries": [{"entity_type": "INCOME_TAX", "value": "ITR_NOTICE"}]},
    {"code": "ADVANCE_TAX", "mode": "first", "queries": [{"entity_type": "INCOME_TAX", "value": "ADVANCE_TAX"}]},
    {"code": "CAPITAL_GAINS", "mode": "first", "queries": [
        {"entity_type": "INCOME_TAX", "value": "CAPITAL_GAINS_CALC"},
        {"entity_type": "INCOME_TAX", "value": "CAPITAL_GAINS"},
    ]},
    {"code": "GST_REGISTRATION", "mode": "first", "queries": [
        {"entity_type": "GST_REGISTRATION", "value": "DEFAULT"},
        {"entity_type": "GST_REGISTRATION", "value": "PROPRIETARY"},
        {"entity_type": "GST_REGISTRATION", "value": "PARTNERSHIP_FIRM"},
        {"entity_type": "GST_REGISTRATION", "value": "COMPANY"},
    ]},
    {"code": "GST_AMENDMENT", "mode": "first", "queries": [{"entity_type": "GST", "value": "GST_AMENDMENT"}]},
    {"code": "GST_CANCELLATION", "mode": "first", "queries": [{"entity_type": "GST", "value": "GST_CANCELLATION"}]},
    {"code": "GST_FILING", "mode": "first", "queries": [{"entity_type": "GST_FILING", "value": "GST_FILING"}]},
    {"code": "GST_Q_FILING", "mode": "first", "queries": [{"entity_type": "GST_FILING", "value": "GST_Q_FILING"}]},
    {"code": "GST_ANNUAL_RETURN", "mode": "first", "queries": [{"entity_type": "GST_FILING", "value": "GST_ANNUAL_RETURN"}]},
    {"code": "GST_LUT", "mode": "first", "queries": [{"entity_type": "GST", "value": "GST_LUT"}]},
    {"code": "GST_REFUND", "mode": "first", "queries": [{"entity_type": "GST", "value": "GST_REFUND"}]},
    {"code": "GST_NOTICE_REPLY", "mode": "first", "queries": [{"entity_type": "GST", "value": "GST_NOTICE_REPLY"}]},
    {"code": "PVT_LTD_REG", "mode": "first", "queries": [{"entity_type": "COMPANY", "value": "PVT_LTD_REG"}]},
    {"code": "LLP_REG", "mode": "first", "queries": [{"entity_type": "COMPANY", "value": "LLP_REG"}]},
    {"code": "OPC_REG", "mode": "first", "queries": [{"entity_type": "COMPANY", "value": "OPC_REG"}]},
    {"code": "PARTNERSHIP_REG", "mode": "first", "queries": [{"entity_type": "COMPANY", "value": "PARTNERSHIP_REG"}]},
    {"code": "ROC_ANNUAL", "mode": "first", "queries": [{"entity_type": "MCA", "value": "ROC_ANNUAL"}]},
    {"code": "DIR3_KYC", "mode": "first", "queries": [{"entity_type": "MCA", "value": "DIR3_KYC"}]},
    {"code": "DIRECTOR_CHANGE", "mode": "first", "queries": [{"entity_type": "MCA", "value": "DIRECTOR_CHANGE"}]},
    {"code": "MONTHLY_ACCOUNTING", "mode": "first", "queries": [{"entity_type": "ACCOUNTING", "value": "MONTHLY_ACCOUNTING"}]},
    {"code": "YEAR_END_FINALIZATION", "mode": "first", "queries": [{"entity_type": "ACCOUNTING", "value": "YEAR_END_FINALIZATION"}]},
    {"code": "PAYROLL_PROCESSING", "mode": "first", "queries": [{"entity_type": "PAYROLL", "value": "PAYROLL_PROCESSING"}]},
    {"code": "PF_FILING", "mode": "first", "queries": [{"entity_type": "PAYROLL", "value": "PF_FILING"}]},
    {"code": "ESI_FILING", "mode": "first", "queries": [{"entity_type": "PAYROLL", "value": "ESI_FILING"}]},
    {"code": "TRADEMARK_REG", "mode": "first", "queries": [{"entity_type": "TRADEMARK", "value": "TRADEMARK_REG"}]},
    {"code": "TRADEMARK_RENEWAL", "mode": "first", "queries": [{"entity_type": "TRADEMARK", "value": "TRADEMARK_RENEWAL"}]},
    {"code": "MSME_REG", "mode": "first", "queries": [{"entity_type": "LICENSE", "value": "MSME_REG"}]},
    {"code": "FSSAI_LICENSE", "mode": "first", "queries": [{"entity_type": "LICENSE", "value": "FSSAI_LICENSE"}]},
    {"code": "IEC_REG", "mode": "first", "queries": [{"entity_type": "LICENSE", "value": "IEC_REG"}]},
]


async def fetch_active_price_for_service_code(conn: asyncpg.Connection, service_code: str):
    """
    Resolve an active PRICE row from ``payment_config`` for a catalog ``service_code``
    (same mapping rules as public service-prices).
    """
    code_norm = (service_code or "").strip().upper()
    if not code_norm:
        return None
    spec = next((s for s in SERVICE_PRICE_SPECS if s["code"] == code_norm), None)
    if spec:
        for q in spec["queries"]:
            entity_type_norm = (q.get("entity_type") or "").strip().upper()
            value_norm = (q.get("value") or "").strip().upper()
            filter_norm = _normalize_optional_filter(q.get("filter"))
            if not entity_type_norm or not value_norm:
                continue
            row = await conn.fetchrow(
                f"""
                SELECT display_name, amount, description, is_active
                  FROM {DB_SCHEMA}.payment_config
                 WHERE upper(trim(entity_type)) = $1
                   AND upper(trim(value)) = $2
                   AND upper(trim(config_type)) = 'PRICE'
                   AND is_active = TRUE
                   AND (
                       $3::text IS NULL
                       OR filter IS NULL
                       OR upper(trim(filter)) = upper(trim($3::text))
                   )
                 ORDER BY
                   CASE
                     WHEN $3::text IS NOT NULL AND filter IS NOT NULL
                       AND upper(trim(filter)) = upper(trim($3::text)) THEN 0
                     WHEN $3::text IS NULL AND filter IS NULL THEN 0
                     ELSE 1
                   END,
                   sort_order ASC NULLS LAST,
                   amount ASC NULLS LAST
                 LIMIT 1
                """,
                entity_type_norm,
                value_norm,
                filter_norm,
            )
            if row:
                return row
    return await conn.fetchrow(
        f"""
        SELECT display_name, amount, description, is_active
          FROM {DB_SCHEMA}.payment_config
         WHERE upper(trim(config_type)) = 'PRICE'
           AND is_active = TRUE
           AND upper(trim(entity_type)) = $1
           AND (
               upper(trim(value)) = 'DEFAULT'
               OR upper(trim(value)) = $1
           )
           AND (filter IS NULL OR trim(filter) = '')
         ORDER BY
           CASE WHEN upper(trim(value)) = $1 THEN 0 ELSE 1 END ASC,
           sort_order ASC NULLS LAST
         LIMIT 1
        """,
        code_norm,
    )


# -------------------------------------------------------------------
# GET PAYMENT CONFIG (UI DROPDOWN)
# -------------------------------------------------------------------

@router.get(
    "/payment-config",
    summary="Get Payment Configurations",
    responses={
        200: {"description": "Payment configs fetched successfully."},
        500: {"description": "Database error."},
    },
)
async def get_payment_configs(
    entity_type: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_payment_configs"},
    )

    log.info(
        "Incoming payment config request | entity_type=%s",
        entity_type,
    )
    entity_type_norm = entity_type.strip().upper()
    cache_key = build_cache_key(
        "payments_config:get_configs",
        entity_type=entity_type_norm,
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

    async def _load_payment_configs():
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT
                        id,
                        entity_type,
                        config_type,
                        value,
                        filter,
                        display_name,
                        amount,
                        description,
                        sort_order
                    FROM {DB_SCHEMA}.payment_config
                    WHERE upper(entity_type) = upper($1)
                    AND is_active = TRUE
                    ORDER BY sort_order ASC
                    """,
                    entity_type_norm,
                )

            log.info(
                "Payment configs fetched successfully | count=%s",
                len(rows),
            )

            return {
                "data": [dict(r) for r in rows],
                "count": len(rows),
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            log.exception("Database error during payment config fetch")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except Exception:
            log.exception("Unexpected error during payment config fetch")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_payment_configs,
        ttl_seconds=300,
        tags=["payments_config:get_configs:index"],
    )


@router.get(
    "/payment-config/public",
    summary="Resolve one payment price (Public)",
    responses={
        200: {"description": "Payment config row or not found."},
        500: {"description": "Database error."},
    },
)
async def get_payment_configs_public(
    request: Request,
    entity_type: str = Query(..., min_length=1, description="Config bucket, e.g. INCOME_TAX, GST, GST_REGISTRATION"),
    value: str = Query(..., min_length=1, description="Row key, e.g. SALARY, GST_FILING, PROPRIETARY"),
    price_filter: Optional[str] = Query(
        None,
        alias="filter",
        description="Optional variant (e.g. NULL_RETURNS / NOT_NULL_RETURNS). Omit to prefer unfiltered row, else lowest sort_order.",
    ),
):
    """
    Requires entity_type + value every time. Optional filter:
    - If provided: exact filter match first, else falls back to rows with NULL filter.
    - If omitted: prefers rows where filter IS NULL; else first row by sort_order (e.g. salary variants).
    """
    await enforce_public_security(
        request=request,
        bucket="public:payments_config",
        max_requests=600,
        window_seconds=60,
        block_seconds=60,
    )

    request_id = generate_uuid()
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": "-", "api": "get_payment_configs_public"},
    )

    entity_type_norm = entity_type.strip().upper()
    value_norm = value.strip().upper()
    filter_norm = _normalize_optional_filter(price_filter)

    log.info(
        "PUBLIC payment resolve | entity_type=%s value=%s filter=%s",
        entity_type_norm,
        value_norm,
        filter_norm,
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    async def _resolve_payment_config_public():
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"""
                    SELECT
                        id,
                        entity_type,
                        config_type,
                        value,
                        filter,
                        display_name,
                        amount,
                        description,
                        sort_order
                    FROM {DB_SCHEMA}.payment_config
                    WHERE upper(trim(entity_type)) = $1
                      AND upper(trim(value)) = $2
                      AND upper(trim(config_type)) = 'PRICE'
                      AND is_active = TRUE
                      AND (
                        $3::text IS NULL
                        OR filter IS NULL
                        OR upper(trim(filter)) = upper(trim($3::text))
                      )
                    ORDER BY
                      CASE
                        WHEN $3::text IS NOT NULL AND filter IS NOT NULL
                          AND upper(trim(filter)) = upper(trim($3::text)) THEN 0
                        WHEN $3::text IS NULL AND filter IS NULL THEN 0
                        ELSE 1
                      END,
                      sort_order ASC NULLS LAST,
                      amount ASC NULLS LAST
                    LIMIT 1
                    """,
                    entity_type_norm,
                    value_norm,
                    filter_norm,
                )

            found = row is not None
            log.info(
                "PUBLIC payment resolve result | found=%s",
                found,
            )

            return {
                "data": dict(row) if row else None,
                "found": found,
                "request_id": request_id,
            }

        except asyncpg.PostgresError:
            log.exception("Database error during public payment resolve")
            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except Exception:
            log.exception("Unexpected error during public payment resolve")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )

    cache_key = build_cache_key(
        "payments_config:resolve_public",
        entity_type=entity_type_norm,
        value=value_norm,
        filter=filter_norm or "",
    )
    return await redis_get_or_set_json(
        cache_key,
        loader=_resolve_payment_config_public,
        ttl_seconds=90,
        tags=["payments_config:resolve_public:index"],
    )


@router.get(
    "/payment-config/public/service-prices",
    summary="Get all UI service prices (Public, cached)",
    responses={
        200: {"description": "Service prices fetched."},
        500: {"description": "Database error."},
    },
)
async def get_public_service_prices(request: Request):
    await enforce_public_security(
        request=request,
        bucket="public:payments_config:bulk",
        max_requests=300,
        window_seconds=60,
        block_seconds=60,
    )

    request_id = generate_uuid()
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": "-", "api": "get_public_service_prices"},
    )

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async def _load_bulk_service_prices():
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT
                        upper(trim(entity_type)) AS entity_type,
                        upper(trim(value)) AS value,
                        CASE
                            WHEN filter IS NULL OR trim(filter) = '' THEN NULL
                            ELSE upper(trim(filter))
                        END AS filter,
                        amount,
                        sort_order
                    FROM {DB_SCHEMA}.payment_config
                    WHERE upper(trim(config_type)) = 'PRICE'
                      AND is_active = TRUE
                    ORDER BY
                        upper(trim(entity_type)),
                        upper(trim(value)),
                        CASE WHEN filter IS NULL OR trim(filter) = '' THEN 0 ELSE 1 END,
                        sort_order ASC NULLS LAST,
                        amount ASC NULLS LAST
                    """
                )

                lookup_rows = []
                rows_by_pair = {}
                for row in rows:
                    amount = row["amount"]
                    if amount is None:
                        continue
                    entity_type = row["entity_type"]
                    value = row["value"]
                    filter_value = row["filter"]
                    amount_num = float(amount)
                    sort_order = row["sort_order"]
                    lookup_rows.append(
                        {
                            "entity_type": entity_type,
                            "value": value,
                            "filter": filter_value,
                            "amount": amount_num,
                            "sort_order": sort_order,
                        }
                    )
                    pair_key = (entity_type, value)
                    pair_rows = rows_by_pair.get(pair_key)
                    if pair_rows is None:
                        pair_rows = []
                        rows_by_pair[pair_key] = pair_rows
                    pair_rows.append(
                        {
                            "filter": filter_value,
                            "amount": amount_num,
                        }
                    )

                def _pick_amount(entity_type: str, value: str, filter_value: Optional[str] = None) -> Optional[float]:
                    pair_rows = rows_by_pair.get((entity_type, value))
                    if not pair_rows:
                        return None
                    if filter_value:
                        filter_norm = filter_value.strip().upper()
                        for item in pair_rows:
                            if item["filter"] == filter_norm:
                                return item["amount"]
                    for item in pair_rows:
                        if item["filter"] is None:
                            return item["amount"]
                    return pair_rows[0]["amount"]

                price_map = {}
                for spec in SERVICE_PRICE_SPECS:
                    resolved_amount = None
                    for q in spec["queries"]:
                        entity_type = (q.get("entity_type") or "").strip().upper()
                        value = (q.get("value") or "").strip().upper()
                        filter_value = q.get("filter")
                        if not entity_type or not value:
                            continue
                        amount = _pick_amount(entity_type, value, filter_value)
                        if amount is not None:
                            resolved_amount = amount
                            break
                    if resolved_amount is not None:
                        price_map[spec["code"]] = resolved_amount

            return {
                "data": price_map,
                "count": len(price_map),
                "lookup_rows": lookup_rows,
                "request_id": request_id,
            }
        except asyncpg.PostgresError:
            log.exception("Database error during bulk service price fetch")
            raise HTTPException(status_code=500, detail="Database error occurred.")
        except Exception:
            log.exception("Unexpected error during bulk service price fetch")
            raise HTTPException(status_code=500, detail="Internal server error.")

    cache_key = build_cache_key("payments_config:public_service_prices")
    return await redis_get_or_set_json(
        cache_key,
        loader=_load_bulk_service_prices,
        ttl_seconds=180,
        tags=["payments_config:public_service_prices:index"],
    )

@router.get(
    "/amount/{entity_id}",
    summary="Get Entity Payment Details",
)
async def get_payment_amount(
    entity_id: int,
    entity_type: str = Query(
        "GST_REGISTRATION",
        description="GST_REGISTRATION | GST_FILING | GST_FILING_RETURN_DETAILS | INCOME_TAX | CUSTOMER_SERVICE "
        "(CUSTOMER_SERVICE: customer_services.id; GST_FILING_RETURN_DETAILS: gst_filing_return_details.id).",
    ),
    customer_id: Optional[int] = Query(
        None,
        gt=0,
        description=(
            "Optional for INCOME_TAX only: matches payments.customer_id (use null/omit when ITR has no customer)."
        ),
    ),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    entity_type_norm = entity_type.strip().upper()
    emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    cache_key = build_cache_key(
        "payments_config:get_amount",
        entity_id=entity_id,
        entity_type=entity_type_norm,
        customer_id=customer_id,
        emp_id=emp_id,
    )

    pool = await get_db_pool()
    itr_payment_customer_id = customer_id if entity_type_norm == "INCOME_TAX" else None

    async def _load_payment_amount():
        async with pool.acquire() as conn:
            try:
                customer_id = None
                display_name = ""
                description = ""
                ownership_category = "N/A"
                pricing_lookup_entity_type = entity_type_norm

                if entity_type_norm == "GST_REGISTRATION":
                    gst_row = await conn.fetchrow(
                        f"""
                        SELECT id, customer_id, ownership_category, is_active
                        FROM {DB_SCHEMA}.gst_registration
                        WHERE id = $1
                        LIMIT 1
                        """,
                        entity_id,
                    )
                    if not gst_row:
                        raise HTTPException(404, "GST registration not found.")
                    if not gst_row["is_active"]:
                        raise HTTPException(400, "GST registration is inactive.")

                    customer_id = gst_row["customer_id"]
                    ownership_category = (
                        (gst_row["ownership_category"] or "N/A").strip().upper()
                    )
                    display_name = "GST Registration"

                elif entity_type_norm == "GST_FILING":
                    filing_row = await conn.fetchrow(
                        f"""
                        SELECT id, customer_id, filing_frequency, gstin, is_active
                        FROM {DB_SCHEMA}.gst_filings
                        WHERE id = $1
                        LIMIT 1
                        """,
                        entity_id,
                    )
                    if not filing_row:
                        raise HTTPException(404, "GST filing not found.")
                    if not filing_row["is_active"]:
                        raise HTTPException(400, "GST filing is inactive.")

                    customer_id = filing_row["customer_id"]
                    display_name = f"GST Filing ({filing_row['filing_frequency']})"
                    ownership_category = filing_row["filing_frequency"]

                elif entity_type_norm == "GST_FILING_RETURN_DETAILS":
                    detail_row = await conn.fetchrow(
                        f"""
                        SELECT d.id,
                               d.is_active AS detail_active,
                               f.customer_id,
                               f.filing_frequency,
                               f.is_active AS filing_active
                          FROM {DB_SCHEMA}.gst_filing_return_details d
                          INNER JOIN {DB_SCHEMA}.gst_filings f
                            ON f.id = d.gst_filing_id
                         WHERE d.id = $1
                         LIMIT 1
                        """,
                        entity_id,
                    )
                    if not detail_row:
                        raise HTTPException(
                            404, "GST filing return detail not found."
                        )
                    if not detail_row["detail_active"]:
                        raise HTTPException(
                            400, "GST filing return detail is inactive."
                        )
                    if not detail_row["filing_active"]:
                        raise HTTPException(400, "Parent GST filing is inactive.")

                    customer_id = detail_row["customer_id"]
                    filing_frequency = detail_row["filing_frequency"]
                    display_name = (
                        f"GST Filing return detail ({filing_frequency})"
                    )
                    ownership_category = filing_frequency
                    pricing_lookup_entity_type = "GST_FILING"

                elif entity_type_norm == "INCOME_TAX":
                    income_tax_row = await conn.fetchrow(
                        f"""
                        SELECT id, financial_year, is_active
                        FROM {DB_SCHEMA}.income_tax
                        WHERE id = $1
                        LIMIT 1
                        """,
                        entity_id,
                    )
                    if not income_tax_row:
                        raise HTTPException(404, "Income tax record not found.")
                    if not income_tax_row["is_active"]:
                        raise HTTPException(400, "Income tax record is inactive.")

                    # ITR rows have no customer_id; use optional query param for payment history.
                    customer_id = itr_payment_customer_id
                    fy = income_tax_row["financial_year"]
                    if isinstance(fy, (list, tuple)):
                        fy_label = ", ".join(str(x) for x in fy if x)
                    else:
                        fy_label = str(fy) if fy else ""
                    display_name = f"Income Tax ({fy_label or 'N/A'})"
                    ownership_category = fy_label or "N/A"

                elif entity_type_norm == "CUSTOMER_SERVICE":
                    cs_row = await conn.fetchrow(
                        f"""
                        SELECT cs.id,
                               cs.customer_id,
                               cs.service_code,
                               cs.is_active,
                               sc.service_name
                          FROM {DB_SCHEMA}.customer_services cs
                          LEFT JOIN {DB_SCHEMA}.service_config sc
                            ON upper(trim(sc.service_code)) = upper(trim(cs.service_code))
                           AND sc.is_active IS NOT DISTINCT FROM TRUE
                         WHERE cs.id = $1
                         LIMIT 1
                        """,
                        entity_id,
                    )
                    if not cs_row:
                        raise HTTPException(404, "Customer service not found.")
                    if not cs_row["is_active"]:
                        raise HTTPException(400, "Customer service is inactive.")

                    customer_id = cs_row["customer_id"]
                    code = (cs_row["service_code"] or "").strip().upper()
                    ownership_category = code or "N/A"
                    label = (cs_row["service_name"] or code or "Customer service").strip()
                    display_name = label

                else:
                    raise HTTPException(
                        400,
                        f"Unsupported entity type: {entity_type_norm}",
                    )

                payment_summary = await conn.fetchrow(
                    f"""
                    SELECT
                        (
                            SELECT amount
                            FROM {DB_SCHEMA}.payments
                            WHERE customer_id IS NOT DISTINCT FROM $1
                              AND entity_id = $2
                              AND entity_type = $3
                              AND is_active = TRUE
                              AND payment_status != 'CANCELLED'
                            ORDER BY created_at ASC
                            LIMIT 1
                        ) AS original_amount,
                        COALESCE(SUM(discount), 0) AS total_discount,
                        COALESCE(SUM(paid_amount), 0) AS total_paid,
                        (
                            SELECT payment_status
                            FROM {DB_SCHEMA}.payments
                            WHERE customer_id IS NOT DISTINCT FROM $1
                              AND entity_id = $2
                              AND entity_type = $3
                              AND is_active = TRUE
                              AND payment_status != 'CANCELLED'
                            ORDER BY created_at DESC
                            LIMIT 1
                        ) AS last_status
                    FROM {DB_SCHEMA}.payments
                    WHERE customer_id IS NOT DISTINCT FROM $1
                      AND entity_id = $2
                      AND entity_type = $3
                      AND is_active = TRUE
                      AND payment_status != 'CANCELLED'
                    """,
                    customer_id,
                    entity_id,
                    entity_type_norm,
                )

                if payment_summary["original_amount"] is None:
                    if entity_type_norm == "CUSTOMER_SERVICE":
                        config = await fetch_active_price_for_service_code(
                            conn,
                            ownership_category if ownership_category != "N/A" else "",
                        )
                    else:
                        config = await conn.fetchrow(
                            f"""
                            SELECT display_name, amount, description, is_active
                            FROM {DB_SCHEMA}.payment_config
                            WHERE upper(trim(entity_type)) = upper(trim($1::text))
                              AND upper(trim(config_type)) = 'PRICE'
                              AND (
                                  upper(trim(value)) = upper(trim($2::text))
                                  OR upper(trim(value)) = 'DEFAULT'
                              )
                              AND (filter IS NULL OR trim(filter) = '')
                            ORDER BY
                              CASE WHEN upper(trim(value)) = upper(trim($2::text)) THEN 0 ELSE 1 END ASC
                            LIMIT 1
                            """,
                            pricing_lookup_entity_type,
                            ownership_category,
                        )

                    if not config:
                        original_amount = 0.0
                        display_name = display_name or entity_type_norm
                        description = f"Initial payment for {display_name}"
                    else:
                        if not config["is_active"]:
                            raise HTTPException(
                                400,
                                "Payment configuration is inactive.",
                            )
                        original_amount = float(config["amount"])
                        display_name = config["display_name"]
                        description = config["description"]

                    total_discount = 0.0
                    total_paid = 0.0

                else:
                    original_amount = float(payment_summary["original_amount"])
                    total_discount = float(
                        payment_summary["total_discount"] or 0
                    )
                    total_paid = float(payment_summary["total_paid"] or 0)
                    last_status = payment_summary["last_status"]

                    if entity_type_norm == "GST_REGISTRATION":
                        display_name = "GST Registration"
                        description = "Remaining payment for GST registration"
                    elif entity_type_norm == "CUSTOMER_SERVICE":
                        description = f"Remaining payment for {display_name}"
                    else:
                        description = f"Remaining payment for {display_name}"

                    if last_status == "PAID":
                        raise HTTPException(
                            409,
                            f"Payment already completed for this {entity_type_norm.lower().replace('_', ' ')}.",
                        )

                from app.payments.payment_ledger import compute_entity_balance

                net_amount, remaining_amount = compute_entity_balance(
                    original_amount, total_discount, total_paid
                )

                if remaining_amount <= 0 and (
                    original_amount > 0 or total_paid > 0
                ):
                    raise HTTPException(
                        409,
                        f"Payment already completed for this {entity_type_norm.lower().replace('_', ' ')}.",
                    )

                return {
                    "entity_id": entity_id,
                    "entity_type": entity_type_norm,
                    "customer_id": customer_id,
                    "ownership_category": ownership_category,
                    "display_name": display_name,
                    "original_amount": round(original_amount, 2),
                    "total_discount": round(total_discount, 2),
                    "total_paid": round(total_paid, 2),
                    "net_amount": round(net_amount, 2),
                    "remaining_amount": round(remaining_amount, 2),
                    "payable_amount": round(remaining_amount, 2),
                    "description": description,
                    "request_id": request_id,
                }
            except asyncpg.PostgresError:
                raise HTTPException(500, "Database error.")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(500, "Internal server error.")

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_payment_amount,
        ttl_seconds=300,
        tags=["payments_config:get_amount:index"],
    )
