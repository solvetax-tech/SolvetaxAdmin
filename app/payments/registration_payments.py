import logging
import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List
from app.security.rbac import require_permission
from app.payments.schemas import RegistrationPaymentIn, RegistrationPaymentEditIn
from app.utils import get_db_pool, DB_SCHEMA, generate_uuid, build_customer_visibility
from app.logger import logger
from datetime import datetime
from zoneinfo import ZoneInfo
import json

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["Registration Payments"]
)

# -------------------------------------------------------------------
# CREATE REGISTRATION PAYMENT (Production Ready + Audit + Full Validation)
# -------------------------------------------------------------------

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create Registration Payment",
    responses={
        201: {"description": "Registration payment created successfully."},
        400: {"description": "Validation failed."},
        404: {"description": "Entity not found."},
        409: {"description": "Business rule violation."},
        500: {"description": "Database or internal error."},
    },
)
async def create_registration_payment(
    payload: RegistrationPaymentIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    """
    ✔ Atomic transaction (Payment + Version)
    ✔ Partial payment supported
    ✔ Remaining balance validation
    ✔ Reject if already PAID
    ✔ Version audit
    ✔ Structured logging
    ✔ All DB errors mapped to UI
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")

    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "create_registration_payment"},
    )

    entity_type = "GST_REGISTRATION"

    log.info(
        "Incoming registration payment create | entity_type=%s | entity_id=%s | amount=%s | paid_amount=%s",
        entity_type,
        payload.entity_id,
        payload.amount,
        payload.paid_amount,
    )

    # --------------------------------------------------
    # Input Validation
    # --------------------------------------------------

    field_errors = {}

    if payload.amount is None or payload.amount <= 0:
        field_errors["amount"] = "Amount must be greater than zero."

    if payload.discount is not None and payload.discount < 0:
        field_errors["discount"] = "Discount cannot be negative."

    if payload.paid_amount is not None and payload.paid_amount < 0:
        field_errors["paid_amount"] = "Paid amount cannot be negative."

    if field_errors:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "validation_error",
                    "message": "Validation failed",
                    "fields": field_errors,
                }
            },
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
                    "fields": {},
                }
            },
        )

    async with pool.acquire() as conn:

        try:

            # --------------------------------------------------
            # Validate GST Registration
            # --------------------------------------------------

            entity_row = await conn.fetchrow(
                f"""
                SELECT id,
                       customer_id,
                       is_active
                FROM {DB_SCHEMA}.gst_registration
                WHERE id = $1
                LIMIT 1
                """,
                payload.entity_id,
            )

            if not entity_row:

                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": {
                            "type": "validation_error",
                            "message": "Validation failed",
                            "fields": {"entity_id": "GST registration not found."},
                        }
                    },
                )

            if not entity_row["is_active"]:

                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "type": "validation_error",
                            "message": "Validation failed",
                            "fields": {"entity_id": "GST registration is inactive."},
                        }
                    },
                )

            customer_id = entity_row["customer_id"]

            # --------------------------------------------------
            # Reject if payment already completed
            # --------------------------------------------------

            paid_row = await conn.fetchrow(
                f"""
                SELECT id
                FROM {DB_SCHEMA}.registration_payments
                WHERE customer_id = $1
                AND entity_id = $2
                AND entity_type = $3
                AND payment_status = 'PAID'
                AND is_active = true
                LIMIT 1
                """,
                customer_id,
                payload.entity_id,
                entity_type,
            )

            if paid_row:

                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": {
                            "type": "business_rule_violation",
                            "message": "Payment already completed for this registration.",
                            "fields": {},
                        }
                    },
                )

            # --------------------------------------------------
            # LOCK existing payments (ADDED FOR RACE CONDITION SAFETY)
            # --------------------------------------------------

            await conn.fetch(
                f"""
                SELECT id
                FROM {DB_SCHEMA}.registration_payments
                WHERE customer_id = $1
                AND entity_id = $2
                AND entity_type = $3
                AND is_active = true
                FOR UPDATE
                """,
                customer_id,
                payload.entity_id,
                entity_type,
            )

            # --------------------------------------------------
            # Remaining Amount Calculation
            # --------------------------------------------------

            summary_row = await conn.fetchrow(
                f"""
                SELECT
                    COALESCE(
                        (
                            SELECT net_amount
                            FROM {DB_SCHEMA}.registration_payments
                            WHERE customer_id = $3
                            AND entity_id = $4
                            AND entity_type = $5
                            AND is_active = true
                            ORDER BY created_at DESC
                            LIMIT 1
                        ),
                        $1 - COALESCE($2,0)
                    ) AS net_amount,
                    COALESCE(SUM(paid_amount),0) AS total_paid
                FROM {DB_SCHEMA}.registration_payments
                WHERE customer_id = $3
                AND entity_id = $4
                AND entity_type = $5
                AND is_active = true
                AND payment_status != 'CANCELLED'
                """,
                payload.amount,
                payload.discount or 0,
                customer_id,
                payload.entity_id,
                entity_type,
            )

            net_amount = summary_row["net_amount"]

            total_paid = summary_row["total_paid"]

            remaining_amount = net_amount - total_paid

            log.info(
                "Payment validation summary | net_amount=%s | total_paid=%s | remaining=%s",
                net_amount,
                total_paid,
                remaining_amount,
            )

            if payload.paid_amount > remaining_amount:

                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "type": "validation_error",
                            "message": "Validation failed",
                            "fields": {
                                "paid_amount": f"Paid amount exceeds remaining balance ({remaining_amount})."
                            },
                        }
                    },
                )

            # --------------------------------------------------
            # Transaction Start
            # --------------------------------------------------

            async with conn.transaction():

                payment_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {DB_SCHEMA}.registration_payments
                    (
                        transaction_id,
                        customer_id,
                        entity_id,
                        entity_type,
                        amount,
                        discount,
                        paid_amount,
                        remarks,
                        created_at,
                        updated_at
                    )
                    VALUES
                    (
                        NULL,$1,$2,$3,$4,$5,$6,$7,NOW(),NOW()
                    )
                    RETURNING *
                    """,
                    customer_id,
                    payload.entity_id,
                    entity_type,
                    payload.amount,
                    payload.discount or 0,
                    payload.paid_amount or 0,
                    payload.remarks,
                )

                if not payment_row:

                    raise HTTPException(
                        status_code=500,
                        detail={
                            "error": {
                                "type": "server_error",
                                "message": "Payment creation failed.",
                                "fields": {},
                            }
                        },
                    )

                # --------------------------------------------------
                # Version Audit
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
                    "REGISTRATION_PAYMENT",
                    payment_row["id"],
                    customer_id,
                    "CREATE",
                    json.dumps(dict(payment_row), default=str),
                    None,
                )

            log.info(
                "Registration payment created successfully | payment_id=%s",
                payment_row["id"],
            )

            return {
                **dict(payment_row),
                "message": "Registration payment created successfully.",
                "request_id": request_id,
            }

        # --------------------------------------------------
        # UNIQUE CONSTRAINT
        # --------------------------------------------------

        except asyncpg.exceptions.UniqueViolationError as e:

            constraint = getattr(e, "constraint_name", "")

            field_errors = {}

            if constraint == "registration_payments_transaction_id_key":
                field_errors["transaction_id"] = "Transaction ID already exists."

            elif constraint == "uq_registration_paid":
                field_errors["payment"] = "Payment already completed for this registration."

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": field_errors or {"non_field_error": "Duplicate value violation."},
                    }
                },
            )

        # --------------------------------------------------
        # FOREIGN KEY VIOLATION
        # --------------------------------------------------

        except asyncpg.exceptions.ForeignKeyViolationError:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Invalid foreign key reference."},
                    }
                },
            )

        # --------------------------------------------------
        # CHECK CONSTRAINT
        # --------------------------------------------------

        except asyncpg.exceptions.CheckViolationError as e:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {
                            "non_field_error": f"Data violates constraint: {getattr(e, 'constraint_name','')}"
                        },
                    }
                },
            )

        # --------------------------------------------------
        # NOT NULL
        # --------------------------------------------------

        except asyncpg.exceptions.NotNullViolationError:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Missing required field value."},
                    }
                },
            )

        # --------------------------------------------------
        # DATA TYPE ERROR
        # --------------------------------------------------

        except asyncpg.exceptions.DataError:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Validation failed",
                        "fields": {"non_field_error": "Invalid data format provided."},
                    }
                },
            )

        # --------------------------------------------------
        # TRIGGER BUSINESS RULE
        # --------------------------------------------------

        except asyncpg.exceptions.RaiseError as e:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "business_rule_violation",
                        "message": str(e),
                        "fields": {},
                    }
                },
            )

        # --------------------------------------------------
        # GENERIC DB ERROR
        # --------------------------------------------------

        except asyncpg.PostgresError:

            log.exception("Database error during registration payment creation")

            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Database error occurred.",
                        "fields": {},
                    }
                },
            )

        except HTTPException:
            raise

        except Exception:

            log.exception("Unexpected error during registration payment creation")

            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Internal server error.",
                        "fields": {},
                    }
                },
            )
# -------------------------------------------------------------------
# LIST REGISTRATION PAYMENTS (DYNAMIC FILTER + PAGINATION)
# -------------------------------------------------------------------
@router.get(
    "/dynamic_filter",
    summary="Filter Registration Payments (Table Only)",
    responses={
        200: {"description": "Registration payments filtered successfully."},
        400: {"description": "Validation failed."},
        500: {"description": "Database or internal error."},
    },
)
async def list_registration_payments(
    payment_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    payment_status: Optional[str] = None,
    payment_mode: Optional[str] = None,

    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,

    amount: Optional[float] = None,
    amount_operator: Optional[str] = None,

    # NEW FILTER (Remaining amount)
    min_remaining: Optional[float] = None,
    max_remaining: Optional[float] = None,

    is_active: Optional[bool] = None,
    include_inactive: bool = Query(False),

    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,

    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),

    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

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
        "Incoming registration payments filter | limit=%s offset=%s",
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
    # Amount Range Validation
    # --------------------------------------------------

    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise HTTPException(
            status_code=400,
            detail="min_amount cannot be greater than max_amount.",
        )

    # --------------------------------------------------
    # Remaining Amount Validation (NEW)
    # --------------------------------------------------

    if min_remaining is not None and max_remaining is not None and min_remaining > max_remaining:
        raise HTTPException(
            status_code=400,
            detail="min_remaining cannot be greater than max_remaining.",
        )

    # --------------------------------------------------
    # Operator Validation
    # --------------------------------------------------

    ALLOWED_OPERATORS = {">", "<", "="}

    if amount_operator and amount_operator not in ALLOWED_OPERATORS:
        raise HTTPException(
            status_code=400,
            detail="Invalid amount_operator. Allowed values are > < =",
        )

    # --------------------------------------------------
    # Enum Validation
    # --------------------------------------------------

    ALLOWED_STATUS = {
        "PENDING",
        "PAID",
        "CANCELLED",
    }

    ALLOWED_MODES = {
        "CASH",
        "UPI",
        "BANK_TRANSFER",
        "CARD",
        "GATEWAY",
    }

    if payment_status and payment_status.strip():

        payment_status = payment_status.strip().upper()

        if payment_status not in ALLOWED_STATUS:
            raise HTTPException(
                status_code=400,
                detail="Invalid payment_status value.",
            )

    if payment_mode and payment_mode.strip():

        payment_mode = payment_mode.strip().upper()

        if payment_mode not in ALLOWED_MODES:
            raise HTTPException(
                status_code=400,
                detail="Invalid payment_mode value.",
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

        if payment_id is not None:
            conditions.append(f"rp.id = ${param_index}")
            values.append(payment_id)
            param_index += 1

        if customer_id is not None:
            conditions.append(f"rp.customer_id = ${param_index}")
            values.append(customer_id)
            param_index += 1

        if entity_id is not None:
            conditions.append(f"rp.entity_id = ${param_index}")
            values.append(entity_id)
            param_index += 1

        if entity_type and entity_type.strip():
            conditions.append(f"rp.entity_type = ${param_index}")
            values.append(entity_type.strip().upper())
            param_index += 1

        if payment_status:
            conditions.append(f"rp.payment_status = ${param_index}")
            values.append(payment_status)
            param_index += 1

        if payment_mode:
            conditions.append(f"rp.payment_mode = ${param_index}")
            values.append(payment_mode)
            param_index += 1

        # --------------------------------------------------
        # Net Amount Range Filtering
        # --------------------------------------------------

        if min_amount is not None:
            conditions.append(f"rp.net_amount >= ${param_index}")
            values.append(min_amount)
            param_index += 1

        if max_amount is not None:
            conditions.append(f"rp.net_amount <= ${param_index}")
            values.append(max_amount)
            param_index += 1

        # --------------------------------------------------
        # Remaining Amount Filtering (NEW)
        # --------------------------------------------------

        if min_remaining is not None:
            conditions.append(f"rp.remaining_amount >= ${param_index}")
            values.append(min_remaining)
            param_index += 1

        if max_remaining is not None:
            conditions.append(f"rp.remaining_amount <= ${param_index}")
            values.append(max_remaining)
            param_index += 1

        # --------------------------------------------------
        # Net Amount Comparison Filtering
        # --------------------------------------------------

        if amount is not None:

            operator = amount_operator if amount_operator else "="

            conditions.append(f"rp.net_amount {operator} ${param_index}")
            values.append(amount)
            param_index += 1

        # --------------------------------------------------
        # Active Filtering Pattern
        # --------------------------------------------------

        if is_active is not None:
            conditions.append(f"rp.is_active = ${param_index}")
            values.append(is_active)
            param_index += 1

        elif not include_inactive:
            conditions.append("rp.is_active = TRUE")

        # --------------------------------------------------
        # Date Filters
        # --------------------------------------------------

        if from_date:
            conditions.append(f"rp.created_at >= ${param_index}")
            values.append(from_date)
            param_index += 1

        if to_date:
            conditions.append(f"rp.created_at <= ${param_index}")
            values.append(to_date)
            param_index += 1

        # --------------------------------------------------
        # ROLE BASED VISIBILITY (CUSTOMER → PAYMENT)
        # --------------------------------------------------

        visibility_sql, visibility_values, param_index = build_customer_visibility(
            role,
            int(current_emp_id) if str(current_emp_id).isdigit() else None,
            param_index,
            DB_SCHEMA,
        )

        if visibility_sql:
            conditions.append(visibility_sql)
            values.extend(visibility_values)

        # --------------------------------------------------
        # WHERE Builder
        # --------------------------------------------------

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # --------------------------------------------------
        # COUNT QUERY
        # --------------------------------------------------

        count_sql = f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.registration_payments rp
            LEFT JOIN {DB_SCHEMA}.customers c
                   ON rp.customer_id = c.customer_id
            {where_clause}
        """

        # --------------------------------------------------
        # DATA QUERY
        # --------------------------------------------------

        data_sql = f"""
            SELECT
                rp.*,
                rp.remaining_amount,   -- NEW FIELD
                c.full_name,
                c.rm_id,
                c.op_id,
                e_rm.first_name AS rm_name,
                e_op.first_name AS op_name
            FROM {DB_SCHEMA}.registration_payments rp
            LEFT JOIN {DB_SCHEMA}.customers c
                   ON rp.customer_id = c.customer_id
            LEFT JOIN {DB_SCHEMA}.employees e_rm
                   ON c.rm_id = e_rm.emp_id
            LEFT JOIN {DB_SCHEMA}.employees e_op
                   ON c.op_id = e_op.emp_id
            {where_clause}
            ORDER BY rp.created_at DESC, rp.id DESC
            LIMIT ${param_index} OFFSET ${param_index + 1}
        """

        values_with_pagination = values + [limit, offset]

        async with pool.acquire() as conn:

            total_count = await conn.fetchval(count_sql, *values)

            rows = await conn.fetch(data_sql, *values_with_pagination)

        log.info(
            "Registration payments filter success | returned=%s total=%s",
            len(rows),
            total_count,
        )

        return {
            "data": [dict(row) for row in rows],
            "total": total_count,
            "limit": limit,
            "offset": offset,
        }

    except asyncpg.PostgresError as e:

        log.error(
            "Database error during registration payments filtering | error=%s",
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

        log.exception("Unexpected error during registration payments filtering")

        raise HTTPException(
            status_code=500,
            detail="Internal server error.",
        )
# -------------------------------------------------------------------
# EDIT REGISTRATION PAYMENT (Production Ready + Discount Propagation)
# -------------------------------------------------------------------

@router.post(
    "/{payment_id}/edit",
    summary="Edit Registration Payment",
    responses={
        200: {"description": "Registration payment updated successfully."},
        400: {"description": "Validation failed."},
        404: {"description": "Payment not found."},
        409: {"description": "State conflict."},
        500: {"description": "Database or internal error."},
    },
)
async def edit_registration_payment(
    payment_id: int,
    payload: RegistrationPaymentEditIn,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    """
    ✔ Only PENDING / CANCELLED payments editable
    ✔ Discount update propagates to all active payments
    ✔ Partial payment integrity maintained
    ✔ Row locking prevents concurrent updates
    ✔ Full DB error mapping for UI
    ✔ Version audit
    """

    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")

    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id, "api": "edit_registration_payment"},
    )

    log.info("Incoming registration payment edit | payment_id=%s", payment_id)

    # --------------------------------------------------
    # Extract payload
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
                    "fields": {},
                }
            },
        )

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "validation_error",
                    "message": "No editable fields provided.",
                    "fields": {},
                }
            },
        )

    # --------------------------------------------------
    # Normalize inputs
    # --------------------------------------------------

    if "remarks" in update_data and update_data["remarks"]:
        update_data["remarks"] = update_data["remarks"].strip()

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
                    "fields": {},
                }
            },
        )

    async with pool.acquire() as conn:

        try:

            async with conn.transaction():

                # --------------------------------------------------
                # Fetch payment with lock
                # --------------------------------------------------

                old_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.registration_payments
                    WHERE id = $1
                    AND is_active = TRUE
                    FOR UPDATE
                    """,
                    payment_id,
                )

                if not old_row:
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": {
                                    "payment_id": "Registration payment not found or inactive."
                                },
                            }
                        },
                    )

                # --------------------------------------------------
                # Prevent editing completed payments
                # --------------------------------------------------

                if old_row["payment_status"] == "PAID":

                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": {
                                "type": "business_rule_violation",
                                "message": "Completed payments cannot be modified.",
                                "fields": {},
                            }
                        },
                    )

                # --------------------------------------------------
                # Discount Validation
                # --------------------------------------------------

                new_discount = update_data.get("discount", old_row["discount"])

                if new_discount > old_row["amount"]:

                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "Validation failed",
                                "fields": {
                                    "discount": "Discount cannot exceed original amount."
                                },
                            }
                        },
                    )

                # --------------------------------------------------
                # Calculate total already paid
                # --------------------------------------------------

                total_paid = await conn.fetchval(
                    f"""
                    SELECT COALESCE(SUM(paid_amount),0)
                    FROM {DB_SCHEMA}.registration_payments
                    WHERE
                        customer_id = $1
                    AND entity_id = $2
                    AND entity_type = $3
                    AND is_active = TRUE
                    """,
                    old_row["customer_id"],
                    old_row["entity_id"],
                    old_row["entity_type"],
                )

                new_net = old_row["amount"] - new_discount

                # --------------------------------------------------
                # Prevent discount breaking payment integrity
                # --------------------------------------------------

                if new_net < total_paid:

                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "business_rule_violation",
                                "message": "Discount cannot be applied because payments already made exceed the new net amount.",
                                "fields": {
                                    "discount": f"Maximum allowed discount is {old_row['amount'] - total_paid}."
                                },
                            }
                        },
                    )

                # --------------------------------------------------
                # Detect no change
                # --------------------------------------------------

                no_change = all(
                    old_row.get(k) == v for k, v in update_data.items()
                )

                if no_change:

                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "type": "validation_error",
                                "message": "No changes detected.",
                                "fields": {},
                            }
                        },
                    )

                # --------------------------------------------------
                # Discount Propagation Logic
                # --------------------------------------------------

                if "discount" in update_data:

                    new_net = old_row["amount"] - new_discount

                    await conn.execute(
                        f"""
                        UPDATE {DB_SCHEMA}.registration_payments
                        SET
                            discount = $1,
                            net_amount = $2,
                            updated_at = NOW()
                        WHERE
                            customer_id = $3
                        AND entity_id = $4
                        AND entity_type = $5
                        AND is_active = TRUE
                        AND payment_status IN ('PENDING','CANCELLED')
                        """,
                        new_discount,
                        new_net,
                        old_row["customer_id"],
                        old_row["entity_id"],
                        old_row["entity_type"],
                    )

                # --------------------------------------------------
                # Build dynamic update query
                # --------------------------------------------------

                fields = []
                values = []
                idx = 1

                for k, v in update_data.items():
                    fields.append(f"{k} = ${idx}")
                    values.append(v)
                    idx += 1

                fields.append("updated_at = NOW()")

                values.append(payment_id)

                update_sql = f"""
                    UPDATE {DB_SCHEMA}.registration_payments
                    SET {', '.join(fields)}
                    WHERE id = ${idx}
                    AND is_active = TRUE
                    RETURNING *
                """

                new_row = await conn.fetchrow(update_sql, *values)

                if not new_row:

                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": {
                                "type": "state_conflict",
                                "message": "Payment state changed. Please retry.",
                                "fields": {},
                            }
                        },
                    )

                # --------------------------------------------------
                # Version Audit
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
                    "REGISTRATION_PAYMENT",
                    payment_id,
                    old_row["customer_id"],
                    "UPDATE",
                    json.dumps(dict(old_row), default=str),
                    json.dumps(dict(new_row), default=str),
                )

                log.info(
                    "Registration payment updated successfully | payment_id=%s",
                    payment_id,
                )

                return {
                    **dict(new_row),
                    "message": "Registration payment updated successfully.",
                    "request_id": request_id,
                }

        # --------------------------------------------------
        # UNIQUE CONSTRAINT
        # --------------------------------------------------

        except asyncpg.exceptions.UniqueViolationError:

            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Duplicate value violates unique constraint.",
                        "fields": {},
                    }
                },
            )

        # --------------------------------------------------
        # CHECK CONSTRAINT
        # --------------------------------------------------

        except asyncpg.exceptions.CheckViolationError as e:

            constraint = getattr(e, "constraint_name", None)

            CHECK_MAP = {
                "chk_amount_positive": "Amount cannot be negative.",
                "chk_discount_positive": "Discount cannot be negative.",
                "chk_paid_amount_positive": "Paid amount cannot be negative.",
                "chk_payment_status": "Invalid payment status.",
            }

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": CHECK_MAP.get(
                            constraint,
                            f"Data violates constraint: {constraint}",
                        ),
                        "fields": {},
                    }
                },
            )

        # --------------------------------------------------
        # FOREIGN KEY
        # --------------------------------------------------

        except asyncpg.exceptions.ForeignKeyViolationError:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Invalid foreign key reference.",
                        "fields": {},
                    }
                },
            )

        # --------------------------------------------------
        # DATA TYPE
        # --------------------------------------------------

        except asyncpg.exceptions.DataError:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "validation_error",
                        "message": "Invalid data format provided.",
                        "fields": {},
                    }
                },
            )

        # --------------------------------------------------
        # TRIGGER RAISE
        # --------------------------------------------------

        except asyncpg.exceptions.RaiseError as e:

            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "type": "business_rule_violation",
                        "message": str(e),
                        "fields": {},
                    }
                },
            )

        # --------------------------------------------------
        # GENERIC DB ERROR
        # --------------------------------------------------

        except asyncpg.PostgresError:

            log.exception("Database error during payment update")

            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Database error occurred.",
                        "fields": {},
                    }
                },
            )

        except HTTPException:
            raise

        except Exception:

            log.exception("Unexpected error during payment update")

            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "server_error",
                        "message": "Internal server error.",
                        "fields": {},
                    }
                },
            )
# -------------------------------------------------------------------
# SOFT DELETE REGISTRATION PAYMENT (Production Ready + Audit)
# -------------------------------------------------------------------
@router.delete(
    "/{payment_id}/soft_delete",
    summary="Soft delete Registration Payment",
    responses={
        200: {"description": "Registration payment soft deleted successfully."},
        400: {"description": "Validation failed or already inactive."},
        404: {"description": "Registration payment not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def soft_delete_registration_payment(
    payment_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()
    current_emp_id = current_user.get("emp_id") or current_user.get("sub") or "-"
    emp_id = int(current_emp_id) if str(current_emp_id).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": current_emp_id},
    )

    log.info("Incoming payment soft delete | payment_id=%s", payment_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.registration_payments
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    payment_id,
                )

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration payment not found.",
                    )

                if not row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Registration payment already inactive.",
                    )

                # Optional protection (recommended)
                if row["payment_status"] == "PAID":
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot delete a completed (PAID) payment.",
                    )

                deleted_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_payments
                       SET is_active = FALSE,
                           updated_at = NOW()
                     WHERE id = $1
                     RETURNING *
                    """,
                    payment_id,
                )

                # --------------------------------------------------
                # Version Audit
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
                    "REGISTRATION_PAYMENT",
                    payment_id,
                    deleted_row["customer_id"],
                    "DELETE",
                    None,
                    json.dumps(dict(deleted_row), default=str),
                )

            log.info(
                "Registration payment soft deleted successfully | payment_id=%s",
                payment_id,
            )

            return {
                **dict(deleted_row),
                "message": "Registration payment soft deleted successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError:
            log.exception("Database error during payment soft delete")
            raise HTTPException(status_code=500, detail="Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during payment soft delete")
            raise HTTPException(status_code=500, detail="Internal server error.")


# -------------------------------------------------------------------
# ACTIVATE REGISTRATION PAYMENT (Production Ready + Audit)
# -------------------------------------------------------------------
@router.post(
    "/{payment_id}/activate",
    summary="Activate Registration Payment",
    responses={
        200: {"description": "Registration payment activated successfully."},
        400: {"description": "Validation failed or already active."},
        404: {"description": "Registration payment not found."},
        409: {"description": "Conflict detected."},
        500: {"description": "Database or internal error."},
    },
)
async def activate_registration_payment(
    payment_id: int,
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    request_id = generate_uuid()
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming payment activation | payment_id=%s", payment_id)

    try:
        pool = await get_db_pool()
    except Exception:
        log.exception("Database pool acquisition failed")
        raise HTTPException(status_code=500, detail="Database connection error.")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():

                payment_row = await conn.fetchrow(
                    f"""
                    SELECT *
                    FROM {DB_SCHEMA}.registration_payments
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    payment_id,
                )

                if not payment_row:
                    raise HTTPException(
                        status_code=404,
                        detail="Registration payment not found.",
                    )

                if payment_row["is_active"]:
                    raise HTTPException(
                        status_code=400,
                        detail="Registration payment already active.",
                    )

                # --------------------------------------------------
                # Prevent duplicate active PAID payment
                # --------------------------------------------------
                if payment_row["payment_status"] == "PAID":

                    existing_paid = await conn.fetchrow(
                        f"""
                        SELECT id
                        FROM {DB_SCHEMA}.registration_payments
                        WHERE customer_id = $1
                        AND entity_id = $2
                        AND entity_type = $3
                        AND payment_status = 'PAID'
                        AND is_active = TRUE
                        """,
                        payment_row["customer_id"],
                        payment_row["entity_id"],
                        payment_row["entity_type"],
                    )

                    if existing_paid:
                        raise HTTPException(
                            status_code=409,
                            detail="Another active PAID payment already exists for this registration.",
                        )

                activated_row = await conn.fetchrow(
                    f"""
                    UPDATE {DB_SCHEMA}.registration_payments
                       SET is_active = TRUE,
                           updated_at = NOW()
                     WHERE id = $1
                     RETURNING *
                    """,
                    payment_id,
                )

                # --------------------------------------------------
                # Version Audit
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
                    "REGISTRATION_PAYMENT",
                    payment_id,
                    activated_row["customer_id"],
                    "ACTIVATE",
                    None,
                    json.dumps(dict(activated_row), default=str),
                )

            log.info(
                "Registration payment activated successfully | payment_id=%s",
                payment_id,
            )

            return {
                **dict(activated_row),
                "message": "Registration payment activated successfully.",
                "request_id": request_id,
            }

        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=400, detail="Foreign key constraint violation.")

        except asyncpg.exceptions.DataError:
            raise HTTPException(status_code=400, detail="Invalid data format.")

        except asyncpg.PostgresError:
            log.exception("Database error during payment activation")
            raise HTTPException(status_code=500, detail="Database error occurred.")

        except HTTPException:
            raise

        except Exception:
            log.exception("Unexpected error during payment activation")
            raise HTTPException(status_code=500, detail="Internal server error.")
