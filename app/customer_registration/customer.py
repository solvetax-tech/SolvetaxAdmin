import logging
import uuid
import asyncpg
import httpx
from difflib import SequenceMatcher
from fastapi import APIRouter, HTTPException, Query, Depends, Request, status, UploadFile, File
from pydantic import constr, validator
from typing import Optional, List
from datetime import datetime
from app.customer_registration.schemas import (
    CustomerIn,
    CustomerEditIn,
    CustomerOut,
    BusinessDescriptionGenerateIn,
)
from app.utils import get_db_pool, DB_SCHEMA, is_business_description_ai_configured
from app.security.rbac import require_permission
from app.security.public_security import enforce_public_security
from app.logger import logger
from app.utils import (
    mask_sensitive_data,
    generate_uuid,
    build_customer_visibility,
    get_blob_service_client,
    AZURE_STORAGE_CONTAINER1,
)
import json
from zoneinfo import ZoneInfo
from app.customer_registration.business_description_ai import request_business_description
from app.redis_cache import (
    build_cache_key,
    get_or_set_json as redis_get_or_set_json,
    invalidate_tag as redis_invalidate_tag,
)

IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(
    prefix="/api/v1/customers",
    tags=["Customers"]
)


def _customer_get_by_id_cache_key(customer_id: int, role: Optional[str], emp_id: Optional[int]) -> str:
    return build_cache_key(
        "customer:get_by_id",
        customer_id=customer_id,
        role=(role or "").strip().upper() or None,
        emp_id=emp_id,
    )


def _customer_get_by_id_tag(customer_id: int) -> str:
    return f"customer:get_by_id:index:{customer_id}"


def _customer_filter_tag() -> str:
    return "customer:filter:index"


async def _invalidate_customer_cache(customer_id: int) -> None:
    # Customer detail + list caches. If GST (or other) GET endpoints add Redis later,
    # invalidate their tags here too when customer fields affect those responses.
    await redis_invalidate_tag(_customer_get_by_id_tag(customer_id))
    await redis_invalidate_tag(_customer_filter_tag())


def _customer_pincode_lookup_tag() -> str:
    return "customer:pincode_lookup:index"


def _customer_pincode_lookup_cache_key(pincode: str) -> str:
    return build_cache_key("customer:pincode_lookup", pincode=pincode)


@router.get(
    "/pincode/{pincode}",
    summary="Lookup city/state by pincode",
    responses={
        200: {"description": "Pincode lookup successful."},
        400: {"description": "Invalid pincode."},
        404: {"description": "Pincode not found."},
        502: {"description": "Upstream service error."},
    },
)
async def lookup_pincode(
    pincode: str,
    search: Optional[str] = Query(
        None,
        description="Optional search text to filter location name/district/state.",
    ),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "lookup_pincode"},
    )

    pincode_norm = (pincode or "").strip()
    if not (pincode_norm.isdigit() and len(pincode_norm) == 6):
        raise HTTPException(status_code=400, detail="Pincode must be a 6-digit number.")

    search_norm = search.strip().lower() if isinstance(search, str) and search.strip() else None
    cache_key = build_cache_key(
        "customer:pincode_lookup:v2",
        pincode=pincode_norm,
        search=search_norm,
    )

    async def _load_pincode_location():
        url = f"https://api.postalpincode.in/pincode/{pincode_norm}"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            log.exception("Pincode lookup HTTP error | pincode=%s", pincode_norm)
            raise HTTPException(status_code=502, detail="Pincode service unavailable.")
        except ValueError:
            log.exception("Pincode lookup invalid JSON | pincode=%s", pincode_norm)
            raise HTTPException(status_code=502, detail="Invalid response from pincode service.")

        if not isinstance(payload, list) or not payload:
            raise HTTPException(status_code=502, detail="Unexpected pincode service response.")

        first = payload[0] or {}
        if first.get("Status") != "Success":
            raise HTTPException(status_code=404, detail="Pincode not found.")

        post_offices = first.get("PostOffice") or []
        if not post_offices:
            raise HTTPException(status_code=404, detail="Pincode not found.")

        locations = []
        seen = set()
        for po in post_offices:
            location = {
                "name": po.get("Name"),
                "district": po.get("District"),
                "state": po.get("State"),
                "country": po.get("Country"),
            }
            if search_norm:
                haystack = " ".join(
                    str(v).strip().lower()
                    for v in (location["name"], location["district"], location["state"])
                    if v
                )
                if search_norm not in haystack:
                    continue
            key = (
                location["name"],
                location["district"],
                location["state"],
                location["country"],
            )
            if key not in seen:
                seen.add(key)
                locations.append(location)

        if not locations:
            raise HTTPException(status_code=404, detail="No locations match the search for this pincode.")

        return {
            "pincode": pincode_norm,
            "search": search_norm,
            "state": locations[0].get("state"),
            "city": locations[0].get("district"),
            "locations": locations,
            "source": "india_post",
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_pincode_location,
        ttl_seconds=86400,
        tags=[_customer_pincode_lookup_tag()],
    )


@router.get(
    "/pincode-search",
    summary="Lookup location details by name (pincode optional)",
    responses={
        200: {"description": "Location search successful."},
        400: {"description": "Invalid search input."},
        404: {"description": "Location not found."},
        502: {"description": "Upstream service error."},
    },
)
async def lookup_location_by_name(
    search: str = Query(..., min_length=2, description="Post office/city/locality search text."),
    pincode: Optional[str] = Query(None, description="Optional 6-digit pincode filter."),
    min_match_percent: int = Query(
        35,
        ge=30,
        le=40,
        description="Minimum fuzzy name match percentage (30-40).",
    ),
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "lookup_location_by_name"},
    )

    search_norm = search.strip()
    if not search_norm:
        raise HTTPException(status_code=400, detail="search is required.")

    pincode_norm = pincode.strip() if isinstance(pincode, str) and pincode.strip() else None
    if pincode_norm and not (pincode_norm.isdigit() and len(pincode_norm) == 6):
        raise HTTPException(status_code=400, detail="pincode must be a 6-digit number.")

    cache_key = build_cache_key(
        "customer:pincode_search:v1",
        search=search_norm.lower(),
        pincode=pincode_norm,
        min_match_percent=min_match_percent,
    )

    async def _load_location_search():
        url = f"https://api.postalpincode.in/postoffice/{search_norm}"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            log.exception("Location search HTTP error | search=%s", search_norm)
            raise HTTPException(status_code=502, detail="Location search service unavailable.")
        except ValueError:
            log.exception("Location search invalid JSON | search=%s", search_norm)
            raise HTTPException(status_code=502, detail="Invalid response from location service.")

        if not isinstance(payload, list) or not payload:
            raise HTTPException(status_code=502, detail="Unexpected location service response.")

        first = payload[0] or {}
        if first.get("Status") != "Success":
            raise HTTPException(status_code=404, detail="No locations found.")

        post_offices = first.get("PostOffice") or []
        locations = []
        seen = set()
        search_lower = search_norm.lower()
        min_match_ratio = min_match_percent / 100.0
        for po in post_offices:
            row_pincode = str(po.get("Pincode") or "").strip()
            if pincode_norm and row_pincode != pincode_norm:
                continue
            location = {
                "name": po.get("Name"),
                "district": po.get("District"),
                "state": po.get("State"),
                "country": po.get("Country"),
                "pincode": row_pincode or None,
            }
            candidates = [
                str(location["name"] or "").strip().lower(),
                str(location["district"] or "").strip().lower(),
                str(location["state"] or "").strip().lower(),
            ]
            score = max(SequenceMatcher(None, search_lower, c).ratio() for c in candidates if c)
            if score < min_match_ratio:
                continue
            key = (
                location["name"],
                location["district"],
                location["state"],
                location["country"],
                location["pincode"],
            )
            if key not in seen:
                seen.add(key)
                location["match_percent"] = round(score * 100, 2)
                locations.append(location)

        if not locations:
            raise HTTPException(status_code=404, detail="No locations match the given filters.")

        locations.sort(key=lambda item: item.get("match_percent", 0), reverse=True)

        return {
            "search": search_norm,
            "pincode": pincode_norm,
            "min_match_percent": min_match_percent,
            "state": locations[0].get("state"),
            "city": locations[0].get("district"),
            "locations": locations,
            "source": "india_post",
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_location_search,
        ttl_seconds=86400,
        tags=[_customer_pincode_lookup_tag()],
    )
# -------------------------------------------------------------------
# CREATE CUSTOMER (Enterprise Production + Version Audit + Services)
# -------------------------------------------------------------------

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Customer (Production Ready + Audit)",
    responses={
        201: {"description": "Customer created successfully."},
        400: {"description": "Validation failed."},
        409: {"description": "Duplicate value violation."},
        500: {"description": "Database or internal error."},
    },
)
async def create_customer(
    request: Request,
    payload: CustomerIn,
):
    await enforce_public_security(
        request=request,
        bucket="public:create_customer",
        max_requests=15,
        window_seconds=60,
        block_seconds=300,
    )

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()

    emp_id = None
    role = None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_customer"},
    )

    masked_email = mask_sensitive_data(payload.email)

    masked_mobile = mask_sensitive_data(payload.mobile)

    log.info(
        "Incoming create customer request | email=%s mobile=%s service_required=%s service_provided=%s",
        masked_email,
        masked_mobile,
        payload.service_required,
        payload.service_provided,
    )

    # --------------------------------------------------
    # Normalize Service Arrays
    # --------------------------------------------------

    def normalize_services(values):

        if values is None:
            return []

        if not isinstance(values, list):
            raise HTTPException(
                status_code=400,
                detail="Services must be a list of strings.",
            )

        cleaned = []

        for v in values:

            if not isinstance(v, str):
                raise HTTPException(
                    status_code=400,
                    detail="Service values must be strings.",
                )

            v = v.strip()

            if v:
                cleaned.append(v)

        return list(dict.fromkeys(cleaned))

    service_required = normalize_services(payload.service_required)

    service_provided = normalize_services(payload.service_provided)

    # --------------------------------------------------
    # Default RM / OP assignment based on role
    # --------------------------------------------------
    rm_id = payload.rm_id
    op_id = payload.op_id

    if role == "RM" and rm_id is None:
        rm_id = emp_id
    if role == "OP" and op_id is None:
        op_id = emp_id

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------

    try:
        pool = await get_db_pool()

    except Exception:

        log.exception("Database pool acquisition failed")

        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "type": "server_error",
                    "message": "Database connection error.",
                    "fields": {}
                }
            },
        )

    async with pool.acquire() as conn:

        try:

            # --------------------------------------------------
            # PROACTIVE DUPLICATE CHECK
            # --------------------------------------------------

            duplicate_row = await conn.fetchrow(
                f"""
                SELECT 
                    EXISTS (SELECT 1 FROM {DB_SCHEMA}.customers WHERE email = $1) AS email_match,
                    EXISTS (SELECT 1 FROM {DB_SCHEMA}.customers WHERE mobile = $2) AS mobile_match
                """,
                payload.email,
                payload.mobile
            )

            field_errors = {}

            if duplicate_row["email_match"]:
                field_errors["email"] = "Email already exists."

            if duplicate_row["mobile_match"]:
                field_errors["mobile"] = "Mobile number already exists."

            if field_errors:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": {
                            "type": "validation_error",
                            "message": "Validation failed",
                            "fields": field_errors
                        }
                    }
                )

            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Insert Customer
                # --------------------------------------------------

                insert_sql = f"""
                    INSERT INTO {DB_SCHEMA}.customers
                    (
                        full_name,
                        email,
                        mobile,
                        business_name,
                        business_description,
                        business_image_url,
                        business_type,
                        state,
                        city,
                        language,
                        remark,
                        rm_id,
                        op_id,
                        referral_id,
                        service_required,
                        service_provided
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16
                    )
                    RETURNING *
                """

                customer_row = await conn.fetchrow(
                    insert_sql,
                    payload.full_name,
                    payload.email,
                    payload.mobile,
                    payload.business_name,
                    payload.business_description,
                    str(payload.business_image_url)
                    if payload.business_image_url
                    else None,
                    payload.business_type,
                    payload.state,
                    payload.city,
                    payload.language,
                    payload.remark,
                    rm_id,
                    op_id,
                    payload.referral_id,
                    service_required,
                    service_provided,
                )

                if not customer_row:

                    log.error("Customer creation failed - no row returned")

                    raise HTTPException(
                        status_code=500,
                        detail={
                            "error": {
                                "type": "server_error",
                                "message": "Customer creation failed.",
                                "fields": {}
                            }
                        },
                    )

                customer_id = customer_row["customer_id"]

                # --------------------------------------------------
                # 2️⃣ Version Audit
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
                    "CUSTOMER",
                    customer_id,
                    customer_id,
                    "CREATE",
                    json.dumps(dict(customer_row), default=str),
                    None,
                )

            log.info(
                "Customer created successfully | customer_id=%s",
                customer_id,
            )

            await _invalidate_customer_cache(customer_id)
            return {
                **dict(customer_row),
                "message": "Customer created successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # UNIQUE CONSTRAINT HANDLING
        # --------------------------------------------------

        except asyncpg.exceptions.UniqueViolationError as e:

            constraint = getattr(e, "constraint_name", "")

            field_errors = {}

            if constraint == "uq_customers_mobile":
                field_errors["mobile"] = "Mobile number already exists."

            elif constraint == "uq_customers_email":
                field_errors["email"] = "Email already exists."

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": field_errors or {"non_field_error": "Duplicate value violation."}
                    }
                },
            )

        # --------------------------------------------------
        # FOREIGN KEY HANDLING
        # --------------------------------------------------

        except asyncpg.exceptions.ForeignKeyViolationError as e:

            constraint = getattr(e, "constraint_name", "")

            field_errors = {}

            if constraint == "customers_rm_id_fkey":
                field_errors["rm_id"] = "Invalid rm_id provided."

            elif constraint == "customers_op_id_fkey":
                field_errors["op_id"] = "Invalid op_id provided."

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": field_errors or {"non_field_error": "Invalid foreign key reference."}
                    }
                },
            )

        # --------------------------------------------------
        # CHECK / NOT NULL / DATA
        # --------------------------------------------------

        except asyncpg.exceptions.CheckViolationError as e:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": f"Data violates constraint: {getattr(e, 'constraint_name', '')}"}
                    }
                },
            )

        except asyncpg.exceptions.NotNullViolationError:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Missing required field value."}
                    }
                },
            )

        except asyncpg.exceptions.DataError:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Invalid data format provided."}
                    }
                },
            )

        # --------------------------------------------------
        # GENERIC DB ERROR
        # --------------------------------------------------

        except asyncpg.PostgresError:

            log.exception("Database error during customer creation")

            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Database error occurred.",
                        "fields": {}
                    }
                },
            )

        except HTTPException:
            raise

        except Exception:

            log.exception("Unexpected error during customer creation")

            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Internal server error.",
                        "fields": {}
                    }
                },
            )


# -------------------------------------------------------------------
# GENERATE BUSINESS DESCRIPTION (configured AI / agent HTTP endpoint)
# -------------------------------------------------------------------
@router.post(
    "/business-description/generate",
    summary="Generate business description via configured AI endpoint",
    responses={
        200: {"description": "Generated text returned (not saved to DB)."},
        503: {"description": "AI URL not configured or upstream failed."},
    },
)
async def generate_business_description(
    payload: BusinessDescriptionGenerateIn,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "generate_business_description"},
    )

    if not is_business_description_ai_configured():
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "config_error",
                    "message": "AI not configured: set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT.",
                    "fields": {},
                }
            },
        )

    body = payload.model_dump()
    generated = await request_business_description(body, log=log)
    if not generated:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "upstream_error",
                    "message": "Upstream did not return a usable description (check logs / response shape).",
                    "fields": {},
                }
            },
        )

    log.info("Business description generated (not persisted) | request_id=%s", request_id)
    return {
        "business_description": generated,
        "request_id": request_id,
    }


# -------------------------------------------------------------------
# UPLOAD CUSTOMER BUSINESS IMAGE (Azure Blob → URL for business_image_url)
# -------------------------------------------------------------------
@router.post(
    "/business-image/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload customer business image (blob only; use URL as business_image_url)",
    responses={
        201: {"description": "File uploaded successfully."},
        400: {"description": "Invalid file."},
        503: {"description": "Blob container not configured."},
        500: {"description": "Blob upload failed."},
    },
)
async def upload_customer_business_image(
    file: UploadFile = File(...),
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):
    def upload_file_to_blob(file_bytes: bytes, filename: str, folder: str = "customer-business-images") -> str:
        blob_service_client = get_blob_service_client()
        unique_filename = f"{generate_uuid()}_{filename}"
        blob_path = f"{folder}/{unique_filename}"
        blob_client = blob_service_client.get_blob_client(
            container=AZURE_STORAGE_CONTAINER1,
            blob=blob_path,
        )
        blob_client.upload_blob(file_bytes, overwrite=True)
        return blob_client.url

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "upload_customer_business_image"},
    )

    if not AZURE_STORAGE_CONTAINER1:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "type": "server_error",
                    "message": "AZURE_STORAGE_CONTAINER1 is not set in environment.",
                    "fields": {},
                }
            },
        )

    log.info("Incoming customer business image upload | filename=%s", file.filename)

    ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    MAX_FILE_SIZE = 10 * 1024 * 1024

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed: JPEG, PNG, WebP, GIF.",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 10MB limit.",
        )

    try:
        blob_url = upload_file_to_blob(contents, file.filename or "image")
    except Exception:
        log.exception("Azure blob upload failed (customer business image)")
        raise HTTPException(
            status_code=500,
            detail="Blob upload failed.",
        )

    log.info("Customer business image uploaded | blob_url=%s", blob_url)
    return {
        "business_image_url": blob_url,
        "blob_url": blob_url,
        "filename": file.filename,
        "message": "File uploaded successfully.",
        "request_id": request_id,
    }


# -------------------------------------------------------------------
# GET CUSTOMER BY ID (Enterprise Production + Detail Audit)
# -------------------------------------------------------------------
@router.get(
    "/{customer_id}",
    summary="Get Customer Details (Production Ready)",
    responses={
        200: {"description": "Customer details fetched successfully."},
        404: {"description": "Customer not found."},
        500: {"description": "Database or internal error."},
    },
)
async def get_customer_by_id(
    customer_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):
    """
    ✔ Fetch single customer with RM and OP names
    ✔ Concurrency safe
    ✔ Detail audit logging
    """
    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "get_customer_by_id"},
    )

    log.info("Incoming get customer request | customer_id=%s", customer_id)
    role = current_user.get("role")
    cache_key = _customer_get_by_id_cache_key(customer_id, role, emp_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    try:
        async def _load_customer_by_id():
            # --------------------------------------------------
            # ROLE BASED VISIBILITY (Single Customer)
            # --------------------------------------------------
            conditions = ["c.customer_id = $1"]
            values = [customer_id]
            idx = 2

            visibility_sql, visibility_values, idx = build_customer_visibility(
                current_user.get("role"),
                emp_id,
                idx,
                DB_SCHEMA,
            )

            if visibility_sql:
                conditions.append(visibility_sql)
                values.extend(visibility_values)

            where_clause = " AND ".join(conditions)

            query = f"""
                SELECT c.*,
                       e_rm.first_name AS rm_name,
                       e_op.first_name AS op_name
                FROM {DB_SCHEMA}.customers c
                LEFT JOIN {DB_SCHEMA}.employees e_rm
                       ON c.rm_id = e_rm.emp_id
                LEFT JOIN {DB_SCHEMA}.employees e_op
                       ON c.op_id = e_op.emp_id
                WHERE {where_clause}
            """
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, *values)

            if not row:
                log.warning("Customer not found | customer_id=%s", customer_id)
                raise HTTPException(
                    status_code=404,
                    detail="Customer not found.",
                )
            return dict(row)

        result = await redis_get_or_set_json(
            cache_key,
            loader=_load_customer_by_id,
            ttl_seconds=300,
            tags=[_customer_get_by_id_tag(customer_id)],
        )
        log.info("Customer fetched successfully | customer_id=%s", customer_id)
        return result

    except asyncpg.PostgresError:
        log.exception("Database error during customer fetch")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )
    except HTTPException:
        raise
    except Exception:
        log.exception("Unexpected error during customer fetch")
        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# LIST CUSTOMERS (Enterprise Filter + Pagination + Services Support)
# -------------------------------------------------------------------

STANDARD_FILTERS = {
    "customer_id": ("customer_id =", lambda v: v),
    "full_name": ("full_name ILIKE", lambda v: f"%{v.strip()}%"),
    "email": ("email ILIKE", lambda v: f"%{v.strip().lower()}%"),
    "mobile": ("mobile =", lambda v: v.strip()),
    "business_type": ("business_type =", lambda v: v),
    "state": ("state =", lambda v: v),
    "city": ("city =", lambda v: v),
    "language": ("language =", lambda v: v),
    "rm_id": ("rm_id =", lambda v: v),
    "op_id": ("op_id =", lambda v: v),
    "referral_id": ("referral_id =", lambda v: v),
}

ARRAY_FILTERS = {
    "service_required": ("service_required", "ANY"),
    "services_required_all": ("service_required", "@>"),
    "services_required_any": ("service_required", "&&"),

    "service_provided": ("service_provided", "ANY"),
    "services_provided_all": ("service_provided", "@>"),
    "services_provided_any": ("service_provided", "&&"),
}

from fastapi import Query
from datetime import datetime


@router.get(
    "/customer_get/filter",
    summary="Filter Customers (Enterprise Dynamic Filter)",
    responses={
        200: {"description": "Customers fetched successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
)
async def filter_customers(
    customer_id: Optional[int] = None,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    mobile: Optional[str] = None,
    business_type: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    language: Optional[str] = None,
    rm_id: Optional[int] = None,
    op_id: Optional[int] = None,
    referral_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),

    # service filters
    service_required: Optional[str] = None,
    services_required_all: Optional[List[str]] = Query(None),
    services_required_any: Optional[List[str]] = Query(None),

    service_provided: Optional[str] = None,
    services_provided_all: Optional[List[str]] = Query(None),
    services_provided_any: Optional[List[str]] = Query(None),

    # date filters
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,

    # pagination
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),

    # NEW: cursor pagination
    cursor: Optional[datetime] = None,

    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    role = current_user.get("role")   # ✅ role from JWT

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "filter_customers"},
    )

    log.info(
        "Incoming customer filter | limit=%s offset=%s cursor=%s",
        limit,
        offset,
        cursor,
    )

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be greater than to_date.",
        )

    role_norm = (role or "").strip().upper() or None
    filter_cache_key = build_cache_key(
        "customer:filter",
        role=role_norm,
        emp_id=emp_id,
        customer_id=customer_id,
        full_name=full_name,
        email=email,
        mobile=mobile,
        business_type=business_type,
        state=state,
        city=city,
        language=language,
        rm_id=rm_id,
        op_id=op_id,
        referral_id=referral_id,
        is_active=is_active,
        include_inactive=include_inactive,
        service_required=service_required,
        services_required_all=services_required_all,
        services_required_any=services_required_any,
        service_provided=service_provided,
        services_provided_all=services_provided_all,
        services_provided_any=services_provided_any,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
        cursor=cursor,
    )
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail="Database connection error.",
        )

    try:
        async def _load_filtered_customers():
            conditions = []
            values = []
            idx = 1

            # --------------------------------------------------
            # STANDARD FILTERS
            # --------------------------------------------------
            for key, (sql_op, formatter) in STANDARD_FILTERS.items():

                value = {
                    "customer_id": customer_id,
                    "full_name": full_name,
                    "email": email,
                    "mobile": mobile,
                    "business_type": business_type,
                    "state": state,
                    "city": city,
                    "language": language,
                    "rm_id": rm_id,
                    "op_id": op_id,
                    "referral_id": referral_id,
                }.get(key)

                if value is not None:
                    conditions.append(f"{sql_op} ${idx}")
                    values.append(formatter(value))
                    idx += 1

        # --------------------------------------------------
        # ARRAY FILTERS
        # --------------------------------------------------
            for key, (column, operator) in ARRAY_FILTERS.items():

                value = {
                    "service_required": service_required,
                    "services_required_all": services_required_all,
                    "services_required_any": services_required_any,
                    "service_provided": service_provided,
                    "services_provided_all": services_provided_all,
                    "services_provided_any": services_provided_any,
                }.get(key)

                if not value:
                    continue

                if isinstance(value, list):
                    cleaned = [v.strip() for v in value if isinstance(v, str) and v.strip()]
                    if not cleaned:
                        continue
                    value = cleaned

                elif isinstance(value, str):
                    value = value.strip()

                if operator == "ANY":
                    conditions.append(f"${idx} = ANY({column})")
                else:
                    conditions.append(f"{column} {operator} ${idx}")

                values.append(value)
                idx += 1

        # --------------------------------------------------
        # STATUS FILTER
        # --------------------------------------------------
            if is_active is not None:
                conditions.append(f"is_active = ${idx}")
                values.append(is_active)
                idx += 1

            elif not include_inactive:
                conditions.append("is_active = TRUE")

        # --------------------------------------------------
        # DATE FILTER
        # --------------------------------------------------
            if from_date:
                conditions.append(f"created_at >= ${idx}")
                values.append(from_date)
                idx += 1

            if to_date:
                conditions.append(f"created_at <= ${idx}")
                values.append(to_date)
                idx += 1

        # --------------------------------------------------
        # CURSOR PAGINATION
        # --------------------------------------------------
            if cursor:
                conditions.append(f"created_at < ${idx}")
                values.append(cursor)
                idx += 1

        # --------------------------------------------------
        # ROLE BASED VISIBILITY (TEAM / MANAGER / RM / OP)
        # --------------------------------------------------

            visibility_sql, visibility_values, idx = build_customer_visibility(
                role,
                emp_id,
                idx,
                DB_SCHEMA
            )

            if visibility_sql:
                conditions.append(visibility_sql)
                values.extend(visibility_values)

        # --------------------------------------------------
        # WHERE CLAUSE
        # --------------------------------------------------
        # Build a WHERE clause and safely qualify simple column
        # references with the customer table alias `c` without
        # corrupting placeholders or complex expressions.
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            if conditions:
                qualified_conditions = []
                for cond in conditions:
                    stripped = cond.lstrip()

                # Leave complex/parenthesized or placeholder-first
                # expressions as-is (e.g. "$1 = ANY(...)", "(...)" etc.)
                    if (
                        not stripped
                        or stripped[0] in "($"
                    ):
                        qualified_conditions.append(cond)
                        continue

                    parts = stripped.split(" ", 1)
                    first = parts[0]
                    rest = parts[1] if len(parts) > 1 else ""

                # If the first token looks like a bare column name,
                # prefix it with the alias `c.`
                    if first.isidentifier() and not first.upper() in {"NOT", "EXISTS"}:
                        first = f"c.{first}"

                    qualified = f"{first} {rest}".rstrip() if rest else first

                    # Preserve original leading whitespace
                    leading_ws_len = len(cond) - len(cond.lstrip(" "))
                    qualified_conditions.append(" " * leading_ws_len + qualified)

                where_clause_c = f"WHERE {' AND '.join(qualified_conditions)}"
            else:
                where_clause_c = ""

            count_sql = f"""
                SELECT COUNT(*)
                FROM {DB_SCHEMA}.customers c
                {where_clause_c}
            """

        # --------------------------------------------------
        # PAGINATION LOGIC
        # --------------------------------------------------
            if cursor:
                pagination_sql = f"LIMIT ${idx}"
                values_with_pagination = values + [limit]
            else:
                pagination_sql = f"LIMIT ${idx} OFFSET ${idx + 1}"
                values_with_pagination = values + [limit, offset]

            main_sql = f"""
                SELECT c.*,
                       e_rm.first_name AS rm_name,
                       e_op.first_name AS op_name
                FROM {DB_SCHEMA}.customers c
                LEFT JOIN {DB_SCHEMA}.employees e_rm
                       ON c.rm_id = e_rm.emp_id
                LEFT JOIN {DB_SCHEMA}.employees e_op
                       ON c.op_id = e_op.emp_id
                {where_clause_c}
                ORDER BY c.created_at DESC
                {pagination_sql}
            """

            async with pool.acquire() as conn:

                total_count = await conn.fetchval(count_sql, *values)

                rows = await conn.fetch(main_sql, *values_with_pagination)

            next_cursor = rows[-1]["created_at"] if rows else None

            log.info(
                "Customer filter success | total=%s returned=%s",
                total_count,
                len(rows),
            )
            return {
                "data": [dict(row) for row in rows],
                "next_cursor": next_cursor
            }

        response_payload = await redis_get_or_set_json(
            filter_cache_key,
            loader=_load_filtered_customers,
            ttl_seconds=300,
            tags=[_customer_filter_tag()],
        )
        return response_payload

    except asyncpg.PostgresError:

        log.exception("Database error during customer filtering")

        raise HTTPException(
            status_code=500,
            detail="Database error occurred.",
        )

    except HTTPException:
        raise

    except Exception:

        log.exception("Unexpected error during customer filtering")

        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# EDIT CUSTOMER (Dynamic PATCH + Services Support + Version Audit)
# -------------------------------------------------------------------

@router.post(
    "/{customer_id}/edit",
    summary="Edit Customer (Dynamic PATCH + Audit)",
    responses={
        200: {"description": "Customer updated successfully."},
        400: {"description": "Validation failed."},
        404: {"description": "Customer not found."},
        409: {"description": "Duplicate value violation."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_customer(
    customer_id: int,
    payload: CustomerEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")

    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "edit_customer"},
    )

    log.info("Incoming edit customer request | customer_id=%s", customer_id)

    # --------------------------------------------------
    # Extract payload fields
    # --------------------------------------------------

    try:
        update_data = payload.model_dump(exclude_unset=True)

    except Exception:

        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "validation_error",
                    "message": "Invalid request payload.",
                    "fields": {}
                }
            },
        )

    if not update_data:

        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "validation_error",
                    "message": "No fields provided for update.",
                    "fields": {}
                }
            },
        )

    # --------------------------------------------------
    # Service Array Normalization Function
    # --------------------------------------------------

    def normalize_services(values):

        if values is None:
            return []

        if not isinstance(values, list):

            raise HTTPException(
                status_code=400,
                detail="Services must be a list of strings.",
            )

        cleaned = []

        for v in values:

            if not isinstance(v, str):

                raise HTTPException(
                    status_code=400,
                    detail="Service values must be strings.",
                )

            v = v.strip()

            if v:
                cleaned.append(v)

        return list(dict.fromkeys(cleaned))

    # --------------------------------------------------
    # Normalize service arrays
    # --------------------------------------------------

    if "service_required" in update_data:

        update_data["service_required"] = normalize_services(
            update_data["service_required"]
        )

    if "service_provided" in update_data:

        update_data["service_provided"] = normalize_services(
            update_data["service_provided"]
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
            detail={
                "error": {
                    "type": "server_error",
                    "message": "Database connection error.",
                    "fields": {}
                }
            }
        )

    async with pool.acquire() as conn:

        try:

            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Fetch Existing Customer (Row Lock)
                # --------------------------------------------------

                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.customers
                    WHERE customer_id = $1
                    FOR UPDATE
                    """,
                    customer_id,
                )

                if not old_row:

                    raise HTTPException(
                        status_code=404,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer not found.",
                                "fields": {}
                            }
                        }
                    )

                # --------------------------------------------------
                # PROACTIVE DUPLICATE CHECK (Exclude current record)
                # --------------------------------------------------

                duplicate_checks = []
                values = []
                idx = 1
                field_errors = {}

                if "email" in update_data:
                    duplicate_checks.append(
                        f"EXISTS (SELECT 1 FROM {DB_SCHEMA}.customers WHERE lower(trim(email)) = lower(trim(${idx})) AND customer_id != ${idx+1}) AS email_match"
                    )
                    values.append(update_data["email"])
                    values.append(customer_id)
                    idx += 2

                if "mobile" in update_data:
                    duplicate_checks.append(
                        f"EXISTS (SELECT 1 FROM {DB_SCHEMA}.customers WHERE trim(mobile) = trim(${idx}) AND customer_id != ${idx+1}) AS mobile_match"
                    )
                    values.append(update_data["mobile"])
                    values.append(customer_id)
                    idx += 2

                if duplicate_checks:

                    dup_sql = f"SELECT {', '.join(duplicate_checks)}"

                    dup_row = await conn.fetchrow(dup_sql, *values)

                    if dup_row:

                        if "email_match" in dup_row and dup_row["email_match"]:
                            field_errors["email"] = "Email already exists."

                        if "mobile_match" in dup_row and dup_row["mobile_match"]:
                            field_errors["mobile"] = "Mobile number already exists."

                if field_errors:

                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": field_errors
                            }
                        }
                    )

                # --------------------------------------------------
                # 2️⃣ Reject if no actual change
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
                # 3️⃣ Build Dynamic Update
                # --------------------------------------------------

                fields = []
                values = []
                idx = 1

                for key, value in update_data.items():

                    fields.append(f"{key} = ${idx}")

                    values.append(value)

                    idx += 1

                fields.append("updated_at = NOW()")

                values.append(customer_id)

                update_sql = f"""
                    UPDATE {DB_SCHEMA}.customers
                    SET {', '.join(fields)}
                    WHERE customer_id = ${idx}
                    RETURNING *
                """

                new_row = await conn.fetchrow(update_sql, *values)

                if not new_row:

                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer state changed. Please retry.",
                                "fields": {}
                            }
                        }
                    )

                # --------------------------------------------------
                # 4️⃣ Version Audit
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
                    "CUSTOMER",
                    customer_id,
                    customer_id,
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

            log.info(
                "Customer updated successfully | customer_id=%s",
                customer_id,
            )

            await _invalidate_customer_cache(customer_id)
            return {
                **dict(new_row),
                "message": "Customer updated successfully.",
                "request_id": request_id,
            }

        except asyncpg.PostgresError:

            log.exception("Database error during customer update")

            raise HTTPException(
                status_code=500,
                detail="Database error occurred.",
            )

        except HTTPException:
            raise

        except Exception:

            log.exception("Unexpected error during customer update")

            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )
# =========================================================
# SOFT DELETE CUSTOMER (Customer-First Mode + Conditional Cascade)
# =========================================================

@router.delete(
    "/{customer_id}/soft_delete",
    summary="Soft delete customer with conditional GST cascade",
    responses={
        200: {"description": "Customer deactivated successfully."},
        400: {"description": "Business validation failed."},
        404: {"description": "Customer not found."},
        500: {"description": "Internal server error."},
    },
)
async def soft_delete_customer(
    customer_id: int,
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
            "api": "conditional_customer_soft_delete",
        },
    )

    log.info("Incoming customer soft delete | customer_id=%s", customer_id)

    # --------------------------------------------------
    # DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool error")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "type": "server_error",
                    "message": "Database connection error.",
                    "fields": {}
                }
            },
        )

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 1️⃣ Lock Customer
                # --------------------------------------------------
                customer = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.customers
                     WHERE customer_id = $1
                     FOR UPDATE
                    """,
                    customer_id,
                )

                if not customer:
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer not found.",
                                "fields": {}
                            }
                        }
                    )

                if customer["is_active"] is False:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer already inactive.",
                                "fields": {}
                            }
                        }
                    )

                # --------------------------------------------------
                # 2️⃣ Count ACTIVE GSTs
                # --------------------------------------------------
                gst_count = await conn.fetchval(
                    f"""
                    SELECT COUNT(*)
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE customer_id = $1
                       AND is_active = TRUE
                    """,
                    customer_id,
                )

                gst_id = None

                # --------------------------------------------------
                # 3️⃣ GST Handling Logic
                # --------------------------------------------------
                if gst_count == 1:

                    gst_row = await conn.fetchrow(
                        f"""
                        SELECT *
                          FROM {DB_SCHEMA}.gst_registration
                         WHERE customer_id = $1
                           AND is_active = TRUE
                         FOR UPDATE
                        """,
                        customer_id,
                    )

                    if not gst_row:
                        raise HTTPException(
                            409,
                            "GST state changed. Please retry.",
                        )

                    gst_id = gst_row["id"]

                elif gst_count > 1:
                    # 🔥 NEW RULE: BLOCK CUSTOMER DEACTIVATION
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Cannot deactivate customer. Multiple active GST registrations detected.",
                                "fields": {}
                            }
                        }
                    )

                # --------------------------------------------------
                # 4️⃣ Soft Delete Customer
                # --------------------------------------------------
                deleted_customer = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.customers
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE customer_id = $1
                     RETURNING *
                    """,
                    customer_id,
                )

                # --------------------------------------------------
                # 5️⃣ If Exactly ONE GST → Cascade Deactivation
                # --------------------------------------------------
                if gst_id:

                    # Deactivate GST
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration
                           SET is_active = FALSE,
                               updated_at = NOW()
                         WHERE id = $1
                        """,
                        gst_id,
                    )

                    # Deactivate Persons
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration_persons
                           SET is_active = FALSE,
                               updated_at = NOW()
                         WHERE gst_registration_id = $1
                        """,
                        gst_id,
                    )

                    # Deactivate Documents
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration_documents d
                           SET is_active = FALSE,
                               updated_at = NOW()
                          FROM {DB_SCHEMA}.gst_registration_persons p
                         WHERE d.person_id = p.person_id
                           AND p.gst_registration_id = $1
                        """,
                        gst_id,
                    )

                # --------------------------------------------------
                # 6️⃣ Version Audit (CUSTOMER ONLY)
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
                    "CUSTOMER",
                    customer_id,
                    customer_id,
                    "DELETE",
                    None,
                    None,
                )

            # --------------------------------------------------
            # Response Handling
            # --------------------------------------------------
            if gst_id:
                message = "Customer and associated GST, persons and documents fully deactivated."
            else:
                message = "Customer deactivated successfully."

            log.info(
                "Customer soft delete completed | customer_id=%s | gst_id=%s | gst_count=%s",
                customer_id,
                gst_id,
                gst_count,
            )

            await _invalidate_customer_cache(customer_id)
            return {
                "customer_id": customer_id,
                "gst_id": gst_id,
                "gst_count": gst_count,
                "message": message,
                "request_id": request_id,
            }

        except asyncpg.PostgresError as e:
            log.exception("Postgres error")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Database error occurred.",
                        "fields": {}
                    }
                }
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Internal server error.",
                        "fields": {}
                    }
                }
            )

# =========================================================
# ACTIVATE CUSTOMER (Customer-First Mode + Conditional Cascade)
# =========================================================

@router.post(
    "/{customer_id}/activate",
    summary="Activate Customer (Conditional + Cascade + Audit)",
    responses={
        200: {"description": "Customer activated successfully."},
        400: {"description": "Business validation failed."},
        404: {"description": "Customer not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def activate_customer(
    customer_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    # --------------------------------------------------
    # 1️⃣ Request Context
    # --------------------------------------------------
    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "emp_id": emp_id,
            "api": "activate_customer",
        },
    )

    log.info("Incoming customer activation | customer_id=%s", customer_id)

    # --------------------------------------------------
    # 2️⃣ DB Pool
    # --------------------------------------------------
    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "type": "server_error",
                    "message": "Database connection error.",
                    "fields": {}
                }
            },
        )

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                # --------------------------------------------------
                # 3️⃣ Lock Customer Row (Concurrency Safe)
                # --------------------------------------------------
                customer = await conn.fetchrow(
                    f"""
                    SELECT *
                      FROM {DB_SCHEMA}.customers
                     WHERE customer_id = $1
                     FOR UPDATE
                    """,
                    customer_id,
                )

                if not customer:
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer not found.",
                                "fields": {}
                            }
                        },
                    )

                if customer["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Customer is already active.",
                                "fields": {}
                            }
                        },
                    )


                # --------------------------------------------------
                # 4️⃣ Count GST Registrations
                # --------------------------------------------------
                gst_count = await conn.fetchval(
                    f"""
                    SELECT COUNT(*)
                      FROM {DB_SCHEMA}.gst_registration
                     WHERE customer_id = $1
                    """,
                    customer_id,
                )

                gst_id = None
                manual_gst_activation_required = False

                # --------------------------------------------------
                # 5️⃣ GST Handling Logic
                # --------------------------------------------------
                if gst_count == 1:

                    gst_row = await conn.fetchrow(
                        f"""
                        SELECT *
                          FROM {DB_SCHEMA}.gst_registration
                         WHERE customer_id = $1
                         FOR UPDATE
                        """,
                        customer_id,
                    )

                    if not gst_row:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "error": {
                                    "type": "validation_error",
                                    "message": "GST state changed. Please retry.",
                                    "fields": {}
                                }
                            },
                        )


                    gst_id = gst_row["id"]

                elif gst_count > 1:
                    manual_gst_activation_required = True

                # --------------------------------------------------
                # 6️⃣ Activate Customer
                # --------------------------------------------------
                activated_customer = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.customers
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE customer_id = $1
                       AND is_active = FALSE
                     RETURNING *
                    """,
                    customer_id,
                )

                if not activated_customer:
                    raise HTTPException(
                        status_code=409,
                        detail="Customer state changed. Please retry.",
                    )

                # --------------------------------------------------
                # 7️⃣ If Exactly ONE GST → Cascade Activation
                # --------------------------------------------------
                if gst_id:

                    # Activate GST
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration
                           SET is_active = TRUE,
                               updated_at = NOW()
                         WHERE id = $1
                        """,
                        gst_id,
                    )

                    # Activate Persons
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration_persons
                           SET is_active = TRUE,
                               updated_at = NOW()
                         WHERE gst_registration_id = $1
                        """,
                        gst_id,
                    )

                    # Activate Documents
                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.gst_registration_documents d
                           SET is_active = TRUE,
                               updated_at = NOW()
                          FROM {DB_SCHEMA}.gst_registration_persons p
                         WHERE d.person_id = p.person_id
                           AND p.gst_registration_id = $1
                        """,
                        gst_id,
                    )

                # --------------------------------------------------
                # 8️⃣ Version Audit (CUSTOMER ONLY)
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
                    "CUSTOMER",
                    customer_id,
                    customer_id,
                    "ACTIVATE",
                    None,
                    None,
                )

            # --------------------------------------------------
            # 9️⃣ Response
            # --------------------------------------------------
            if gst_id:
                message = (
                    "Customer and associated GST, persons, and documents "
                    "activated successfully."
                )
            elif manual_gst_activation_required:
                message = (
                    "Customer activated successfully. "
                    "Multiple GST registrations detected. "
                    "Please activate the required GST registrations individually "
                    "from the GST Registration page."
                )
            else:
                message = "Customer activated successfully."

            log.info(
                "Customer activation completed | customer_id=%s | gst_id=%s | gst_count=%s",
                customer_id,
                gst_id,
                gst_count,
            )

            await _invalidate_customer_cache(customer_id)
            return {
                "customer_id": customer_id,
                "gst_id": gst_id,
                "gst_count": gst_count,
                "message": message,
                "request_id": request_id,
            }

        # --------------------------------------------------
        # Exception Handling
        # --------------------------------------------------
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Foreign key constraint violation."}
                    }
                },
            )

        except asyncpg.exceptions.CheckViolationError as e:
            log.exception("CHECK constraint error")
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": str(e)}
                    }
                },
            )

        except asyncpg.exceptions.DataError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Invalid data format."}
                    }
                },
            )

        except asyncpg.PostgresError as e:
            log.exception("Database error during activation")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Database error occurred.",
                        "fields": {}
                    }
                },
            )

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during activation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error.",
            )