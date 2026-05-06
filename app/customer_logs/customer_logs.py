from datetime import datetime, timezone
from uuid import uuid4
import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.customer_logs.schemas import CustomerEventLogIn
from app.security.public_security import enforce_public_security
from app.security.rbac import require_admin
from app.utils import DB_SCHEMA, generate_uuid, get_db_pool

router = APIRouter(prefix="/api/v1/event-logs", tags=["Customer Logs"])
logger = logging.getLogger(__name__)

def _derive_run_status(payload: CustomerEventLogIn) -> str:
    event_name = (payload.event_name or "").lower()
    event_status = (payload.event_status or "").lower()
    if event_status == "success" and "submit" in event_name:
        return "completed"
    if event_status == "failed" and "submit" in event_name:
        return "failed"
    return "in_progress"


def _derive_step_status(payload: CustomerEventLogIn) -> str:
    event_status = (payload.event_status or "").lower()
    if event_status in {"success", "failed"}:
        return "completed" if event_status == "success" else "failed"
    return "entered"


async def _fetch_non_repetitive_rows(conn, dataset: str, limit: int):
    dataset = (dataset or "").strip().lower()
    if dataset == "customer_event_logs":
        return await conn.fetch(
            f"""
            SELECT *
            FROM (
                SELECT DISTINCT ON (
                    session_id,
                    COALESCE(client_event_id::text, ''),
                    event_name,
                    COALESCE(journey_id::text, ''),
                    COALESCE(funnel_step_number, -1),
                    COALESCE(page_path, '')
                )
                *
                FROM {DB_SCHEMA}.customer_event_logs
                ORDER BY
                    session_id,
                    COALESCE(client_event_id::text, ''),
                    event_name,
                    COALESCE(journey_id::text, ''),
                    COALESCE(funnel_step_number, -1),
                    COALESCE(page_path, ''),
                    event_timestamp DESC,
                    id DESC
            ) dedup
            ORDER BY event_timestamp DESC, id DESC
            LIMIT $1
            """,
            limit,
        )
    if dataset == "customer_sessions":
        return await conn.fetch(
            f"""
            SELECT *
            FROM {DB_SCHEMA}.customer_sessions
            ORDER BY last_seen_at DESC NULLS LAST, started_at DESC
            LIMIT $1
            """,
            limit,
        )
    if dataset == "customer_funnel_runs":
        return await conn.fetch(
            f"""
            SELECT *
            FROM {DB_SCHEMA}.customer_funnel_runs
            ORDER BY last_event_at DESC NULLS LAST, started_at DESC, funnel_run_id DESC
            LIMIT $1
            """,
            limit,
        )
    if dataset == "customer_funnel_steps":
        return await conn.fetch(
            f"""
            SELECT *
            FROM (
                SELECT DISTINCT ON (funnel_run_id, step_number, step_name, step_status)
                    *
                FROM {DB_SCHEMA}.customer_funnel_steps
                ORDER BY funnel_run_id, step_number, step_name, step_status, created_at DESC, funnel_step_event_id DESC
            ) dedup
            ORDER BY created_at DESC, funnel_step_event_id DESC
            LIMIT $1
            """,
            limit,
        )
    if dataset == "customer_session_page_metrics":
        return await conn.fetch(
            f"""
            SELECT *
            FROM {DB_SCHEMA}.customer_session_page_metrics
            ORDER BY updated_at DESC, id DESC
            LIMIT $1
            """,
            limit,
        )
    raise HTTPException(status_code=400, detail=f"Unsupported dataset: {dataset}")


@router.post("", status_code=status.HTTP_201_CREATED, summary="Ingest customer event log")
async def ingest_customer_event_log(request: Request, payload: CustomerEventLogIn):
    await enforce_public_security(
        request=request,
        bucket="public:customer_event_logs",
        max_requests=120,
        window_seconds=60,
        block_seconds=120,
    )
    request_id = generate_uuid()
    event_ts = payload.event_timestamp
    if event_ts.tzinfo is None:
        event_ts = event_ts.replace(tzinfo=timezone.utc)

    stage = "init"
    logger.info(
        "event_logs_ingest_start request_id=%s event_name=%s session_id=%s client_event_id=%s journey_id=%s",
        request_id,
        payload.event_name,
        payload.session_id,
        payload.client_event_id,
        payload.journey_id,
    )
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                stage = "upsert_customer_sessions"
                await conn.execute(
                    f"""
                    INSERT INTO {DB_SCHEMA}.customer_sessions
                    (
                        session_id, customer_id, anonymous_customer_id,
                        started_at, last_seen_at,
                        entry_page_path, exit_page_path, entry_referrer_path,
                        platform, device_type, os_name, os_version,
                        browser_name, browser_version, app_version, user_agent,
                        environment, release_tag
                    )
                    VALUES
                    (
                        $1, $2, $3,
                        $4, $4,
                        $5, $5, $6,
                        $7, $8, $9, $10,
                        $11, $12, $13, $14,
                        $15, $16
                    )
                    ON CONFLICT (session_id) DO UPDATE
                    SET
                        customer_id = COALESCE(EXCLUDED.customer_id, {DB_SCHEMA}.customer_sessions.customer_id),
                        last_seen_at = EXCLUDED.last_seen_at,
                        exit_page_path = COALESCE(EXCLUDED.exit_page_path, {DB_SCHEMA}.customer_sessions.exit_page_path),
                        platform = COALESCE(EXCLUDED.platform, {DB_SCHEMA}.customer_sessions.platform),
                        device_type = COALESCE(EXCLUDED.device_type, {DB_SCHEMA}.customer_sessions.device_type),
                        os_name = COALESCE(EXCLUDED.os_name, {DB_SCHEMA}.customer_sessions.os_name),
                        os_version = COALESCE(EXCLUDED.os_version, {DB_SCHEMA}.customer_sessions.os_version),
                        browser_name = COALESCE(EXCLUDED.browser_name, {DB_SCHEMA}.customer_sessions.browser_name),
                        browser_version = COALESCE(EXCLUDED.browser_version, {DB_SCHEMA}.customer_sessions.browser_version),
                        app_version = COALESCE(EXCLUDED.app_version, {DB_SCHEMA}.customer_sessions.app_version),
                        user_agent = COALESCE(EXCLUDED.user_agent, {DB_SCHEMA}.customer_sessions.user_agent),
                        environment = COALESCE(EXCLUDED.environment, {DB_SCHEMA}.customer_sessions.environment),
                        release_tag = COALESCE(EXCLUDED.release_tag, {DB_SCHEMA}.customer_sessions.release_tag)
                    """,
                    payload.session_id,
                    payload.customer_id,
                    payload.anonymous_customer_id,
                    event_ts,
                    payload.page_path,
                    payload.referrer_path,
                    payload.platform,
                    payload.device_type,
                    payload.os_name,
                    payload.os_version,
                    payload.browser_name,
                    payload.browser_version,
                    payload.app_version,
                    payload.user_agent or request.headers.get("user-agent"),
                    payload.environment,
                    payload.release_tag,
                )

                stage = "dedupe_event_lookup"
                if payload.client_event_id is not None:
                    existing_event_id = await conn.fetchval(
                        f"""
                        SELECT id
                        FROM {DB_SCHEMA}.customer_event_logs
                        WHERE session_id = $1 AND client_event_id = $2
                        LIMIT 1
                        """,
                        payload.session_id,
                        payload.client_event_id,
                    )
                    if existing_event_id is not None:
                        logger.info(
                            "event_logs_ingest_duplicate request_id=%s session_id=%s client_event_id=%s",
                            request_id,
                            payload.session_id,
                            payload.client_event_id,
                        )
                        return {"message": "Duplicate event ignored", "request_id": request_id, "duplicate": True}

                stage = "insert_customer_event_logs"
                inserted_event_id = await conn.fetchval(
                    f"""
                    INSERT INTO {DB_SCHEMA}.customer_event_logs
                    (
                        session_id, journey_id, client_event_id,
                        event_name, event_category, event_action, event_status, event_label, severity,
                        page_path, page_url, referrer_path, route_name,
                        cta_name, form_name, funnel_name, funnel_step_number, funnel_step_name, service_code, phone_number,
                        event_timestamp,
                        dwell_time_seconds, active_time_seconds,
                        api_name, api_status_code, api_response_time_ms,
                        error_code, error_message,
                        ingestion_source, environment, release_tag,
                        platform, device_type, os_name, os_version, browser_name, browser_version, app_version, user_agent
                    )
                    VALUES
                    (
                        $1, $2, $3,
                        $4, $5, $6, $7, $8, $9,
                        $10, $11, $12, $13,
                        $14, $15, $16, $17, $18, $19, $20,
                        $21,
                        $22, $23,
                        $24, $25, $26,
                        $27, $28,
                        $29, $30, $31,
                        $32, $33, $34, $35, $36, $37, $38, $39
                    )
                    RETURNING id
                    """,
                    payload.session_id,
                    payload.journey_id,
                    payload.client_event_id,
                    payload.event_name,
                    payload.event_category,
                    payload.event_action,
                    payload.event_status,
                    payload.event_label,
                    payload.severity,
                    payload.page_path,
                    payload.page_url,
                    payload.referrer_path,
                    payload.route_name,
                    payload.cta_name,
                    payload.form_name,
                    payload.funnel_name,
                    payload.funnel_step_number,
                    payload.funnel_step_name,
                    payload.service_code,
                    payload.phone_number,
                    event_ts,
                    payload.dwell_time_seconds,
                    payload.active_time_seconds,
                    payload.api_name,
                    payload.api_status_code,
                    payload.api_response_time_ms,
                    payload.error_code,
                    payload.error_message,
                    payload.ingestion_source or "web_app",
                    payload.environment,
                    payload.release_tag,
                    payload.platform,
                    payload.device_type,
                    payload.os_name,
                    payload.os_version,
                    payload.browser_name,
                    payload.browser_version,
                    payload.app_version,
                    payload.user_agent or request.headers.get("user-agent"),
                )
                if inserted_event_id is None:
                    raise HTTPException(
                        status_code=500,
                        detail="Database error: customer_event_logs insert returned no id.",
                    )

                stage = "update_customer_sessions_totals"
                await conn.execute(
                    f"""
                    UPDATE {DB_SCHEMA}.customer_sessions
                    SET
                        last_seen_at = $2,
                        exit_page_path = COALESCE($3, exit_page_path),
                        total_events_count = total_events_count + 1,
                        total_page_views = total_page_views + CASE WHEN $4 THEN 1 ELSE 0 END,
                        total_dwell_seconds = total_dwell_seconds + COALESCE($5, 0),
                        total_active_seconds = total_active_seconds + COALESCE($6, 0)
                    WHERE session_id = $1
                    """,
                    payload.session_id,
                    event_ts,
                    payload.page_path,
                    payload.event_name == "page_view",
                    payload.dwell_time_seconds,
                    payload.active_time_seconds,
                )

                if payload.page_path:
                    stage = "upsert_customer_session_page_metrics"
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.customer_session_page_metrics
                        (
                            session_id, page_path, page_view_count,
                            first_view_at, last_view_at, total_dwell_seconds, total_active_seconds, bounce_flag
                        )
                        VALUES
                        (
                            $1, $2, CASE WHEN $3 THEN 1 ELSE 0 END,
                            $4, $4, COALESCE($5, 0), COALESCE($6, 0), FALSE
                        )
                        ON CONFLICT (session_id, page_path) DO UPDATE
                        SET
                            page_view_count = {DB_SCHEMA}.customer_session_page_metrics.page_view_count + CASE WHEN EXCLUDED.page_view_count > 0 THEN 1 ELSE 0 END,
                            last_view_at = EXCLUDED.last_view_at,
                            total_dwell_seconds = {DB_SCHEMA}.customer_session_page_metrics.total_dwell_seconds + COALESCE(EXCLUDED.total_dwell_seconds, 0),
                            total_active_seconds = {DB_SCHEMA}.customer_session_page_metrics.total_active_seconds + COALESCE(EXCLUDED.total_active_seconds, 0)
                        """,
                        payload.session_id,
                        payload.page_path,
                        payload.event_name == "page_view",
                        event_ts,
                        payload.dwell_time_seconds,
                        payload.active_time_seconds,
                    )

                if payload.journey_id and payload.funnel_name:
                    stage = "upsert_customer_funnel_runs"
                    await conn.execute(
                        f"""
                        INSERT INTO {DB_SCHEMA}.customer_funnel_runs
                        (
                            journey_id, session_id, customer_id, anonymous_customer_id, phone_number,
                            funnel_name, service_code, entry_page_path,
                            started_at, last_event_at, completed_at,
                            run_status, current_step_number, current_step_name,
                            steps_completed_count, submit_attempt_count, validation_error_count, api_failure_count,
                            total_duration_seconds, conversion_flag, drop_off_reason,
                            environment, release_tag
                        )
                        VALUES
                        (
                            $1, $2, $3, $4, $5,
                            $6, $7, $8,
                            $9, $9, NULL,
                            $10, $11, $12,
                            CASE WHEN $13 THEN 1 ELSE 0 END,
                            CASE WHEN $14 THEN 1 ELSE 0 END,
                            CASE WHEN $15 THEN 1 ELSE 0 END,
                            CASE WHEN $16 THEN 1 ELSE 0 END,
                            0, $17, $18,
                            $19, $20
                        )
                        ON CONFLICT (journey_id) DO UPDATE
                        SET
                            last_event_at = EXCLUDED.last_event_at,
                            completed_at = CASE WHEN EXCLUDED.run_status = 'completed' THEN EXCLUDED.last_event_at ELSE {DB_SCHEMA}.customer_funnel_runs.completed_at END,
                            run_status = CASE
                                WHEN {DB_SCHEMA}.customer_funnel_runs.run_status = 'completed' THEN {DB_SCHEMA}.customer_funnel_runs.run_status
                                ELSE EXCLUDED.run_status
                            END,
                            current_step_number = COALESCE(EXCLUDED.current_step_number, {DB_SCHEMA}.customer_funnel_runs.current_step_number),
                            current_step_name = COALESCE(EXCLUDED.current_step_name, {DB_SCHEMA}.customer_funnel_runs.current_step_name),
                            steps_completed_count = {DB_SCHEMA}.customer_funnel_runs.steps_completed_count + CASE WHEN EXCLUDED.steps_completed_count > 0 THEN 1 ELSE 0 END,
                            submit_attempt_count = {DB_SCHEMA}.customer_funnel_runs.submit_attempt_count + CASE WHEN EXCLUDED.submit_attempt_count > 0 THEN 1 ELSE 0 END,
                            validation_error_count = {DB_SCHEMA}.customer_funnel_runs.validation_error_count + CASE WHEN EXCLUDED.validation_error_count > 0 THEN 1 ELSE 0 END,
                            api_failure_count = {DB_SCHEMA}.customer_funnel_runs.api_failure_count + CASE WHEN EXCLUDED.api_failure_count > 0 THEN 1 ELSE 0 END,
                            conversion_flag = {DB_SCHEMA}.customer_funnel_runs.conversion_flag OR EXCLUDED.conversion_flag,
                            drop_off_reason = COALESCE(EXCLUDED.drop_off_reason, {DB_SCHEMA}.customer_funnel_runs.drop_off_reason),
                            service_code = COALESCE(EXCLUDED.service_code, {DB_SCHEMA}.customer_funnel_runs.service_code),
                            total_duration_seconds = GREATEST(
                                0,
                                EXTRACT(EPOCH FROM (EXCLUDED.last_event_at - {DB_SCHEMA}.customer_funnel_runs.started_at))::int
                            )
                        """,
                        payload.journey_id,
                        payload.session_id,
                        payload.customer_id,
                        payload.anonymous_customer_id,
                        payload.phone_number,
                        payload.funnel_name,
                        payload.service_code,
                        payload.page_path,
                        event_ts,
                        _derive_run_status(payload),
                        payload.funnel_step_number,
                        payload.funnel_step_name,
                        (payload.event_status or "").lower() == "success",
                        "submit_attempt" in (payload.event_name or "").lower(),
                        (payload.event_status or "").lower() == "failed" and (payload.error_code or "").lower().startswith("validation"),
                        (payload.event_status or "").lower() == "failed" and (payload.error_code or "").lower().startswith("api"),
                        _derive_run_status(payload) == "completed",
                        payload.error_message[:255] if payload.error_message else None,
                        payload.environment,
                        payload.release_tag,
                    )

                    stage = "fetch_funnel_run_id"
                    funnel_run_id = await conn.fetchval(
                        f"SELECT funnel_run_id FROM {DB_SCHEMA}.customer_funnel_runs WHERE journey_id = $1",
                        payload.journey_id,
                    )

                    if funnel_run_id is not None and payload.funnel_step_number is not None and payload.funnel_step_name:
                        step_status = _derive_step_status(payload)
                        exited_at = event_ts if step_status in {"completed", "failed"} else None
                        stage = "insert_customer_funnel_steps"
                        await conn.execute(
                            f"""
                            INSERT INTO {DB_SCHEMA}.customer_funnel_steps
                            (
                                funnel_run_id, step_number, step_name, step_status,
                                entered_at, exited_at, step_duration_seconds, retry_count,
                                event_name, page_path, error_code, error_message
                            )
                            VALUES
                            (
                                $1, $2, $3, $4,
                                $5, $6,
                                NULL, 0,
                                $7, $8, $9, $10
                            )
                            """,
                            funnel_run_id,
                            payload.funnel_step_number,
                            payload.funnel_step_name,
                            step_status,
                            event_ts,
                            exited_at,
                            payload.event_name,
                            payload.page_path,
                            payload.error_code,
                            payload.error_message,
                        )

        logger.info(
            "event_logs_ingest_success request_id=%s event_name=%s session_id=%s client_event_id=%s inserted_event_id=%s",
            request_id,
            payload.event_name,
            payload.session_id,
            payload.client_event_id,
            inserted_event_id,
        )
        return {"message": "Event ingested", "request_id": request_id, "duplicate": False}
    except asyncpg.PostgresError as exc:
        logger.exception(
            "event_logs_ingest_failed request_id=%s stage=%s event_name=%s session_id=%s client_event_id=%s",
            request_id,
            stage,
            payload.event_name,
            payload.session_id,
            payload.client_event_id,
        )
        raise HTTPException(status_code=500, detail=f"Database error at {stage}: {str(exc)}")


@router.post("/debug/smoke", summary="Run one analytics smoke event")
async def run_analytics_smoke_event(request: Request):
    await enforce_public_security(
        request=request,
        bucket="public:customer_event_logs_debug_smoke",
        max_requests=10,
        window_seconds=60,
        block_seconds=300,
    )
    session_id = uuid4()
    journey_id = uuid4()
    event_payload = CustomerEventLogIn(
        session_id=session_id,
        anonymous_customer_id=f"debug_{uuid4().hex[:24]}",
        journey_id=journey_id,
        client_event_id=uuid4(),
        event_name="debug_smoke_submit_success",
        event_category="debug",
        event_action="submit",
        event_status="success",
        event_label="debug smoke event",
        severity="info",
        page_path="/debug/smoke",
        page_url="https://debug.local/smoke",
        referrer_path="/",
        form_name="DebugSmokeForm",
        funnel_name="DEBUG_SMOKE_FORM",
        funnel_step_number=1,
        funnel_step_name="submit",
        service_code="DEBUG_SERVICE",
        phone_number="9000000000",
        event_timestamp=datetime.now(timezone.utc),
        dwell_time_seconds=2,
        active_time_seconds=2,
        api_name="/api/v1/event-logs/debug/smoke",
        api_status_code=201,
        api_response_time_ms=1,
        ingestion_source="debug_smoke",
        environment="development",
        release_tag="smoke_test",
        platform="WEB",
        device_type="DESKTOP",
        browser_name="DEBUG",
        browser_version="1.0",
        app_version="debug",
        user_agent=request.headers.get("user-agent"),
    )

    ingest_response = await ingest_customer_event_log(request=request, payload=event_payload)

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            session_row = await conn.fetchrow(
                f"SELECT * FROM {DB_SCHEMA}.customer_sessions WHERE session_id = $1",
                session_id,
            )
            event_row = await conn.fetchrow(
                f"SELECT * FROM {DB_SCHEMA}.customer_event_logs WHERE session_id = $1 ORDER BY id DESC LIMIT 1",
                session_id,
            )
            funnel_run_row = await conn.fetchrow(
                f"SELECT * FROM {DB_SCHEMA}.customer_funnel_runs WHERE journey_id = $1",
                journey_id,
            )
            funnel_steps_count = await conn.fetchval(
                f"SELECT COUNT(*)::bigint FROM {DB_SCHEMA}.customer_funnel_steps WHERE funnel_run_id = $1",
                funnel_run_row["funnel_run_id"] if funnel_run_row else None,
            ) if funnel_run_row else 0
            page_metric_row = await conn.fetchrow(
                f"SELECT * FROM {DB_SCHEMA}.customer_session_page_metrics WHERE session_id = $1 AND page_path = $2",
                session_id,
                "/debug/smoke",
            )
    except asyncpg.PostgresError:
        raise HTTPException(status_code=500, detail="Database error while validating smoke test.")

    return {
        "message": "Analytics smoke test completed",
        "ingest_response": ingest_response,
        "proof": {
            "session_id": str(session_id),
            "journey_id": str(journey_id),
            "customer_sessions": bool(session_row),
            "customer_event_logs": bool(event_row),
            "customer_funnel_runs": bool(funnel_run_row),
            "customer_funnel_steps_count": int(funnel_steps_count or 0),
            "customer_session_page_metrics": bool(page_metric_row),
        },
    }


@router.get("/non-repetitive/customer-events", summary="Get non-repetitive customer event logs (admin only)")
async def get_non_repetitive_customer_events(
    limit: int = Query(100, ge=1, le=1000),
    _admin=Depends(require_admin()),
):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await _fetch_non_repetitive_rows(conn, "customer_event_logs", limit)
        return {"dataset": "customer_event_logs", "count": len(rows), "items": [dict(r) for r in rows]}
    except asyncpg.PostgresError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {str(exc)}")


@router.get("/non-repetitive/customer-sessions", summary="Get non-repetitive customer sessions (admin only)")
async def get_non_repetitive_customer_sessions(
    limit: int = Query(100, ge=1, le=1000),
    _admin=Depends(require_admin()),
):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await _fetch_non_repetitive_rows(conn, "customer_sessions", limit)
        return {"dataset": "customer_sessions", "count": len(rows), "items": [dict(r) for r in rows]}
    except asyncpg.PostgresError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {str(exc)}")


@router.get("/non-repetitive/funnel-runs", summary="Get non-repetitive funnel runs (admin only)")
async def get_non_repetitive_funnel_runs(
    limit: int = Query(100, ge=1, le=1000),
    _admin=Depends(require_admin()),
):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await _fetch_non_repetitive_rows(conn, "customer_funnel_runs", limit)
        return {"dataset": "customer_funnel_runs", "count": len(rows), "items": [dict(r) for r in rows]}
    except asyncpg.PostgresError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {str(exc)}")


@router.get("/non-repetitive/funnel-steps", summary="Get non-repetitive funnel steps (admin only)")
async def get_non_repetitive_funnel_steps(
    limit: int = Query(100, ge=1, le=1000),
    _admin=Depends(require_admin()),
):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await _fetch_non_repetitive_rows(conn, "customer_funnel_steps", limit)
        return {"dataset": "customer_funnel_steps", "count": len(rows), "items": [dict(r) for r in rows]}
    except asyncpg.PostgresError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {str(exc)}")


@router.get("/non-repetitive/session-page-metrics", summary="Get non-repetitive session page metrics (admin only)")
async def get_non_repetitive_session_page_metrics(
    limit: int = Query(100, ge=1, le=1000),
    _admin=Depends(require_admin()),
):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await _fetch_non_repetitive_rows(conn, "customer_session_page_metrics", limit)
        return {"dataset": "customer_session_page_metrics", "count": len(rows), "items": [dict(r) for r in rows]}
    except asyncpg.PostgresError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {str(exc)}")
