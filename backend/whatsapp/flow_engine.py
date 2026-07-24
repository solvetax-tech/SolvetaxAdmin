"""WhatsApp Flow Execution Engine (Workflow Builder Slice 1).

Scheduler steps 14a / 14b / 14c — called from schedular.py background_jobs().

Step 14a  _start_scheduled_flows(conn)
    Enrolls customers into published scheduled_date flows when their CRM due-date
    falls within the trigger window.  Skipped during IST quiet hours.

Step 14b  _tick_wa_flow_runs(conn)
    Claims up to 10 runnable runs (running or delay-wait past wake_at), executes
    node handlers synchronously until a Wait or EndFlow halt, then commits state.
    Handler exception → transaction rollback → run retried next tick.
    Stale-run reaper at end: heartbeat_at > 15 min old → failed.

Step 14c  _dispatch_outbox(conn, redis, sink)
    Claim-then-release: a short transaction claims ≤ 5 pending outbox rows
    (status='sending') and commits; then for each row calls send_service.send(),
    maps outcomes, and commits results row-by-row.  Stuck 'sending' rows older
    than 5 minutes are re-queued.  Requires exactly one active wa_instance_config
    row; skips dispatch entirely otherwise.

Body text is FINAL at enqueue time: tokens are resolved into the outbox body when
the SendMessage handler writes the row.  The stored body is the audit record.
This is a deliberate deviation from the doc's send-time resolution; noted here
for transparency.

Halt points: Wait and EndFlow only.  SendMessage is a pass-through — it writes
its outbox row and execution continues in the same tick.

Simulation:  the simulate_flow() function runs the same handler logic in-memory
(no DB writes, DryRunSink) and returns a trace + would_send list.  Condition
nodes use the context value at simulation time (no live DB re-read).

Sources:
    doc 09 §3.5 (tables + steps 14a/14b/14c)
    doc 09 §3.6 (versioning — context.__flow_def snapshot per run)
    doc 09 §3.7 (guardrails — enforced via send_service, not here)
    doc 09 §3.8 (simulation + DryRunSink)
    doc 09 §5   (Slice 1 exit criteria)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import pytz

from backend.employee_tasks.employee_tasks import create_task_for_emp
from backend.utils import DB_SCHEMA as S
from backend.whatsapp.flow_validation import _ntype
from backend.whatsapp.send_service import (
    ConsentError,
    QuietHoursError,
    RateLimitError,
    send as _svc_send,
)
from backend.whatsapp.sinks import DryRunSink
from backend.whatsapp.variable_resolver import resolve as _resolve_tokens
from backend.whatsapp.client import EvolutionAPIError

logger = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")

# Maximum runs to claim per tick (step 14b).
_TICK_BATCH = 10
# Maximum customers to enroll per flow per tick (step 14a).
_ENROLL_BATCH = 500
# Maximum outbox rows to dispatch per tick (step 14c).
_DISPATCH_BATCH = 5
# Max retries before permanent outbox failure.
_MAX_RETRIES = 5
# Stale running run threshold.
_STALE_MINUTES = 15
# Claim-then-release: rows stuck in 'sending' older than this are requeued.
_SENDING_STUCK_MINUTES = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_ist() -> datetime:
    return datetime.now(_IST)


def _parse_jsonb(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, str):
        return json.loads(val)
    return val


def _next_9am_ist() -> datetime:
    """Return the next 09:00 IST datetime (tomorrow if current IST hour >= 9)."""
    now = _now_ist()
    candidate = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now.hour >= 9:
        candidate += timedelta(days=1)
    return candidate


def _find_trigger_node(live_data: dict) -> dict | None:
    """Return the single trigger node from the flow definition, or None."""
    _TRIGGER_TYPES = frozenset({"inboundKeyword", "scheduledDate", "crmEvent"})
    nodes = live_data.get("nodes") or []
    for n in nodes:
        if _ntype(n) in _TRIGGER_TYPES:
            return n
    return None


def _find_node(live_data: dict, node_id: str) -> dict | None:
    for n in (live_data.get("nodes") or []):
        if n.get("id") == node_id:
            return n
    return None


def _next_node(live_data: dict, from_node_id: str, handle: str | None = None) -> str | None:
    """Return the target node_id of the first matching outgoing edge.

    If handle is specified, the edge must have that sourceHandle.
    Falls back to any outgoing edge when handle is None.
    """
    edges = live_data.get("edges") or []
    for e in edges:
        if e.get("source") != from_node_id:
            continue
        if handle is None or (e.get("sourceHandle") or "") == handle:
            return e.get("target")
    return None


# ---------------------------------------------------------------------------
# Source table → due-date column mapping (step 14a)
# ---------------------------------------------------------------------------

# Maps trigger source config value → (table_alias, join_sql, due_date_col, status_col)
# The status_col is used to populate 'filing_status' in the context snapshot and
# to anchor Condition live re-reads.
_GST_SOURCE_MAP: dict[str, tuple[str, str]] = {
    "gstr3b_due_date": ("gstr3b_due_date", "gstr3b_status"),
    "gstr1_due_date":  ("gstr1_due_date",  "gstr1_status"),
}


def _source_status_col(source: str) -> str | None:
    """Return the status column name for a GST due-date source."""
    return _GST_SOURCE_MAP.get(source, (None, None))[1]


# ---------------------------------------------------------------------------
# Enrollment query builders (step 14a)
# ---------------------------------------------------------------------------

async def _enroll_gst_source(
    conn,
    flow_id: str,
    flow_version: int,
    live_data: dict,
    trigger_node_id: str,
    source: str,
    days_before: int,
    due_date_col: str,
    status_col: str,
) -> int:
    live_data_json = json.dumps(live_data)
    # Warn about multi-mobile customers before enrollment
    multi_mobile_count = await conn.fetchval(
        f"""
        SELECT COUNT(DISTINCT c.customer_id)
        FROM {S}.customers c
        WHERE (SELECT COUNT(*) FROM {S}.customers c2 WHERE c2.mobile = c.mobile) > 1
          AND c.is_active = TRUE
        """
    )
    if multi_mobile_count:
        logger.warning(
            "flow_engine step14a flow_id=%s source=%s "
            "multi_mobile_customers_skipped=%s",
            flow_id, source, multi_mobile_count,
        )

    tag = await conn.execute(
        f"""
        INSERT INTO {S}.wa_flow_runs
            (flow_id, flow_version, customer_id, phone, current_node_id, context, heartbeat_at)
        SELECT
            $1, $2, c.customer_id, c.mobile, $3,
            jsonb_build_object(
                'customer_name',  c.full_name,
                'gst_number',     f.gstin,
                'filing_status',  d.{status_col},
                'gstr3b_due_date', d.gstr3b_due_date,
                'gstr1_due_date',  d.gstr1_due_date,
                'rm_id',          c.rm_id,
                'op_id',          c.op_id,
                'phone',          c.mobile,
                '__flow_def',     $4::jsonb,
                '__source_row_id', d.id
            ),
            now()
        FROM {S}.gst_filing_return_details d
        JOIN {S}.gst_filings f
          ON f.id = d.gst_filing_id AND f.is_active = TRUE
        JOIN {S}.customers c
          ON c.customer_id = f.customer_id AND c.is_active = TRUE
        JOIN {S}.wa_consent wc
          ON wc.phone = c.mobile AND wc.revoked_at IS NULL
        WHERE d.is_active = TRUE
          AND d.{due_date_col} IS NOT NULL
          AND d.{due_date_col} > now()
          AND d.{due_date_col} <= now() + ($5 || ' days')::interval
          AND NOT EXISTS (
              SELECT 1 FROM {S}.wa_flow_runs r
              WHERE r.flow_id = $1
                AND r.customer_id = c.customer_id
                AND r.created_at >= d.{due_date_col} - ($5 || ' days')::interval
          )
          AND (
              SELECT COUNT(*) FROM {S}.customers c2
              WHERE c2.mobile = c.mobile
          ) = 1
        LIMIT $6
        ON CONFLICT DO NOTHING
        """,
        flow_id, flow_version, trigger_node_id,
        live_data_json, str(days_before), _ENROLL_BATCH,
    )
    return _parse_tag_count(tag)


async def _enroll_payment_source(
    conn,
    flow_id: str,
    flow_version: int,
    live_data: dict,
    trigger_node_id: str,
    days_before: int,
) -> int:
    live_data_json = json.dumps(live_data)
    tag = await conn.execute(
        f"""
        INSERT INTO {S}.wa_flow_runs
            (flow_id, flow_version, customer_id, phone, current_node_id, context, heartbeat_at)
        SELECT
            $1, $2, c.customer_id, c.mobile, $3,
            jsonb_build_object(
                'customer_name',       c.full_name,
                'payment_amount_due',  p.remaining_amount,
                'payment_due_date',    p.followup_at,
                'rm_id',               c.rm_id,
                'op_id',               c.op_id,
                'phone',               c.mobile,
                '__flow_def',          $4::jsonb,
                '__source_row_id',     p.id
            ),
            now()
        FROM {S}.payments p
        JOIN {S}.customers c
          ON c.customer_id = p.customer_id AND c.is_active = TRUE
        JOIN {S}.wa_consent wc
          ON wc.phone = c.mobile AND wc.revoked_at IS NULL
        WHERE p.is_active = TRUE
          AND p.payment_status = 'PENDING'
          AND p.remaining_amount > 0
          AND p.followup_at IS NOT NULL
          AND p.followup_at > now()
          AND p.followup_at <= now() + ($5 || ' days')::interval
          AND NOT EXISTS (
              SELECT 1 FROM {S}.wa_flow_runs r
              WHERE r.flow_id = $1
                AND r.customer_id = c.customer_id
                AND r.created_at >= p.followup_at - ($5 || ' days')::interval
          )
          AND (
              SELECT COUNT(*) FROM {S}.customers c2
              WHERE c2.mobile = c.mobile
          ) = 1
        LIMIT $6
        ON CONFLICT DO NOTHING
        """,
        flow_id, flow_version, trigger_node_id,
        live_data_json, str(days_before), _ENROLL_BATCH,
    )
    return _parse_tag_count(tag)


async def _enroll_crm_source(
    conn,
    flow_id: str,
    flow_version: int,
    live_data: dict,
    trigger_node_id: str,
    days_before: int,
) -> int:
    live_data_json = json.dumps(live_data)
    # Log leads with no customer match (prospect messaging OOS in v1)
    no_customer_count = await conn.fetchval(
        f"""
        SELECT COUNT(*)
        FROM {S}.crm_leads l
        WHERE l.is_active = TRUE
          AND l.followup_at IS NOT NULL
          AND l.followup_at > now()
          AND l.followup_at <= now() + ($1 || ' days')::interval
          AND NOT EXISTS (
              SELECT 1 FROM {S}.customers c WHERE c.mobile = l.mobile AND c.is_active = TRUE
          )
        """,
        str(days_before),
    )
    if no_customer_count:
        logger.debug(
            "flow_engine step14a crm_source leads_with_no_customer=%s (skipped; prospect OOS in v1)",
            no_customer_count,
        )

    tag = await conn.execute(
        f"""
        INSERT INTO {S}.wa_flow_runs
            (flow_id, flow_version, customer_id, phone, current_node_id, context, heartbeat_at)
        SELECT
            $1, $2, c.customer_id, c.mobile, $3,
            jsonb_build_object(
                'customer_name',   c.full_name,
                'pipeline_stage',  l.stage,
                'rm_id',           l.rm_id,
                'op_id',           l.op_id,
                'phone',           c.mobile,
                '__flow_def',      $4::jsonb,
                '__source_row_id', l.id
            ),
            now()
        FROM {S}.crm_leads l
        JOIN {S}.customers c
          ON c.mobile = l.mobile AND c.is_active = TRUE
        JOIN {S}.wa_consent wc
          ON wc.phone = c.mobile AND wc.revoked_at IS NULL
        WHERE l.is_active = TRUE
          AND l.followup_at IS NOT NULL
          AND l.followup_at > now()
          AND l.followup_at <= now() + ($5 || ' days')::interval
          AND NOT EXISTS (
              SELECT 1 FROM {S}.wa_flow_runs r
              WHERE r.flow_id = $1
                AND r.customer_id = c.customer_id
                AND r.created_at >= l.followup_at - ($5 || ' days')::interval
          )
          AND (
              SELECT COUNT(*) FROM {S}.customers c2
              WHERE c2.mobile = c.mobile
          ) = 1
        LIMIT $6
        ON CONFLICT DO NOTHING
        """,
        flow_id, flow_version, trigger_node_id,
        live_data_json, str(days_before), _ENROLL_BATCH,
    )
    return _parse_tag_count(tag)


def _parse_tag_count(tag: str) -> int:
    """Parse the row-count integer from an asyncpg command tag like 'INSERT 0 5'."""
    if not tag:
        return 0
    parts = tag.split()
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return 0


# ---------------------------------------------------------------------------
# Step 14a — enroll customers into scheduled flows
# ---------------------------------------------------------------------------

async def _start_scheduled_flows(conn) -> int:
    """Enroll customers into published scheduled_date flows (step 14a).

    Skips the entire tick if IST time is outside quiet hours.
    Returns total rows inserted across all flows.
    """
    now_ist = _now_ist()

    # Load active instance config for quiet-hours check
    cfg = await conn.fetchrow(
        f"SELECT quiet_hours_start, quiet_hours_end FROM {S}.wa_instance_config"
        f" WHERE is_active = true LIMIT 1"
    )
    if cfg is None:
        logger.warning("flow_engine step14a skip=no_active_instance_config")
        return 0
    if not (cfg["quiet_hours_start"] <= now_ist.hour < cfg["quiet_hours_end"]):
        logger.info(
            "flow_engine step14a skip=quiet_hours hour=%s window=[%s,%s)",
            now_ist.hour, cfg["quiet_hours_start"], cfg["quiet_hours_end"],
        )
        return 0

    flows = await conn.fetch(
        f"SELECT id, live_data, version FROM {S}.wa_flows"
        f" WHERE trigger_type = 'scheduled_date'"
        f"   AND status = 'published' AND is_active = true"
    )
    if not flows:
        return 0

    total = 0
    for flow in flows:
        flow_id = str(flow["id"])
        flow_version = flow["version"]
        live_data = _parse_jsonb(flow["live_data"])
        if not live_data:
            logger.warning("flow_engine step14a flow_id=%s skip=empty_live_data", flow_id)
            continue

        trigger_node = _find_trigger_node(live_data)
        if trigger_node is None:
            logger.warning("flow_engine step14a flow_id=%s skip=no_trigger_node", flow_id)
            continue

        trigger_cfg = (trigger_node.get("data") or {}).get("config") or {}
        source: str = trigger_cfg.get("source", "")
        days_before_raw = trigger_cfg.get("days_before")
        if not source or days_before_raw is None:
            logger.warning(
                "flow_engine step14a flow_id=%s skip=missing_trigger_config source=%r days_before=%r",
                flow_id, source, days_before_raw,
            )
            continue
        days_before = int(days_before_raw)
        trigger_node_id: str = trigger_node["id"]

        t0 = time.monotonic()
        try:
            if source in _GST_SOURCE_MAP:
                due_date_col, status_col = _GST_SOURCE_MAP[source]
                enrolled = await _enroll_gst_source(
                    conn, flow_id, flow_version, live_data,
                    trigger_node_id, source, days_before, due_date_col, status_col,
                )
            elif source == "payment_followup_at":
                enrolled = await _enroll_payment_source(
                    conn, flow_id, flow_version, live_data,
                    trigger_node_id, days_before,
                )
            elif source == "crm_followup_at":
                enrolled = await _enroll_crm_source(
                    conn, flow_id, flow_version, live_data,
                    trigger_node_id, days_before,
                )
            else:
                logger.warning(
                    "flow_engine step14a flow_id=%s skip=unknown_source source=%r",
                    flow_id, source,
                )
                continue
        except Exception:
            logger.exception("flow_engine step14a error flow_id=%s source=%s", flow_id, source)
            continue

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "flow_engine step14a flow_id=%s source=%s enrolled=%s query_ms=%.1f",
            flow_id, source, enrolled, elapsed_ms,
        )
        if elapsed_ms > 50:
            logger.warning(
                "flow_engine step14a SLOW flow_id=%s source=%s query_ms=%.1f "
                "consider adding a partial index on the due-date column",
                flow_id, source, elapsed_ms,
            )
        total += enrolled

    return total


# ---------------------------------------------------------------------------
# Condition live re-read (step 14b)
# ---------------------------------------------------------------------------

async def _live_read_condition_variable(conn, variable: str, context: dict) -> Any:
    """Re-read a condition variable live from the source table.

    Anchors the query to context.__source_row_id and uses the trigger source
    (from context.__flow_def trigger node config) to determine which
    table/column to query.

    Returns the fresh value, or the current context value on any failure.
    """
    source_row_id = context.get("__source_row_id")
    if source_row_id is None:
        logger.warning("condition live-read: no __source_row_id in context; using snapshot value")
        return context.get(variable)

    flow_def = context.get("__flow_def") or {}
    trigger_node = _find_trigger_node(flow_def)
    if trigger_node is None:
        return context.get(variable)

    trigger_cfg = (trigger_node.get("data") or {}).get("config") or {}
    source = trigger_cfg.get("source", "")

    if variable == "filing_status" and source in _GST_SOURCE_MAP:
        _, status_col = _GST_SOURCE_MAP[source]
        val = await conn.fetchval(
            f"SELECT {status_col} FROM {S}.gst_filing_return_details WHERE id = $1",
            int(source_row_id),
        )
        return val

    if variable == "payment_amount_due" and source == "payment_followup_at":
        val = await conn.fetchval(
            f"SELECT remaining_amount FROM {S}.payments WHERE id = $1",
            int(source_row_id),
        )
        return val

    if variable == "pipeline_stage" and source == "crm_followup_at":
        val = await conn.fetchval(
            f"SELECT stage FROM {S}.crm_leads WHERE id = $1",
            int(source_row_id),
        )
        return val

    # For other variable/source combos fall back to context snapshot
    logger.debug(
        "condition live-read: no DB mapping for variable=%r source=%r; using snapshot",
        variable, source,
    )
    return context.get(variable)


# ---------------------------------------------------------------------------
# Condition comparison
# ---------------------------------------------------------------------------

def _compare(actual: Any, operator: str, expected: str) -> bool:
    if actual is None:
        return False
    actual_str = str(actual)
    op = operator.lower()
    if op == "eq":
        return actual_str == expected
    if op == "neq":
        return actual_str != expected
    if op == "contains":
        return expected in actual_str
    if op == "gt":
        try:
            return float(actual_str) > float(expected)
        except (ValueError, TypeError):
            return actual_str > expected
    if op == "lt":
        try:
            return float(actual_str) < float(expected)
        except (ValueError, TypeError):
            return actual_str < expected
    return False


# ---------------------------------------------------------------------------
# Step 14b — tick flow runs
# ---------------------------------------------------------------------------

async def _execute_run(conn, run: dict) -> None:
    """Process one run until a halt point (Wait/EndFlow) or error."""
    run_id = str(run["id"])
    context = _parse_jsonb(run["context"]) or {}
    flow_def = context.get("__flow_def") or {}
    current_node_id: str = run["current_node_id"]

    MAX_STEPS = 100  # safety cap against infinite loops (validation blocks cycles at publish)
    steps = 0

    while current_node_id and steps < MAX_STEPS:
        steps += 1
        node = _find_node(flow_def, current_node_id)
        if node is None:
            raise RuntimeError(f"node {current_node_id!r} not found in flow_def")

        ntype = _ntype(node)
        cfg = (node.get("data") or {}).get("config") or {}

        # ---- scheduledDate / crmEvent: no-op start → follow single outgoing edge ----
        if ntype in ("scheduledDate", "crmEvent", "inboundKeyword"):
            next_id = _next_node(flow_def, current_node_id)
            if next_id is None:
                raise RuntimeError(f"trigger node {current_node_id!r} has no outgoing edge")
            current_node_id = next_id

        # ---- sendMessage: write outbox row, advance, CONTINUE ----
        elif ntype == "sendMessage":
            body_template = cfg.get("body", "")
            body = _resolve_tokens(body_template, context)
            idem_key = f"{run_id}:{current_node_id}"
            await conn.execute(
                f"""
                INSERT INTO {S}.wa_outbox
                    (flow_run_id, node_id, phone, body, idempotency_key)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                run_id, current_node_id, run["phone"], body, idem_key,
            )
            next_id = _next_node(flow_def, current_node_id)
            if next_id is None:
                raise RuntimeError(f"sendMessage node {current_node_id!r} has no outgoing edge")
            current_node_id = next_id

        # ---- wait ----
        elif ntype == "wait":
            wait_type = cfg.get("type")
            if wait_type == "delay":
                delay_minutes = int(cfg.get("delay_minutes", 0))
                wake = datetime.now(pytz.utc) + timedelta(minutes=delay_minutes)
                await conn.execute(
                    f"""
                    UPDATE {S}.wa_flow_runs
                    SET status = 'waiting',
                        wait_type = 'delay',
                        wake_at = $1,
                        current_node_id = $2,
                        heartbeat_at = now(),
                        updated_at = now()
                    WHERE id = $3
                    """,
                    wake, current_node_id, run_id,
                )
                return  # halt
            else:
                # reply-type wait — not supported until Slice 3
                context["__error"] = "wait(reply) not supported until Slice 3"
                await conn.execute(
                    f"""
                    UPDATE {S}.wa_flow_runs
                    SET status = 'failed',
                        context = $1::jsonb,
                        current_node_id = $2,
                        updated_at = now()
                    WHERE id = $3
                    """,
                    json.dumps(context), current_node_id, run_id,
                )
                return  # halt

        # ---- condition: live re-read, compare, branch ----
        elif ntype == "condition":
            variable = cfg.get("variable", "")
            operator = cfg.get("operator", "eq")
            expected = str(cfg.get("value", ""))
            fresh_val = await _live_read_condition_variable(conn, variable, context)
            if fresh_val is not None:
                context[variable] = str(fresh_val)
            result = _compare(fresh_val, operator, expected)
            handle = "true_output" if result else "false_output"
            next_id = _next_node(flow_def, current_node_id, handle)
            if next_id is None:
                raise RuntimeError(
                    f"condition node {current_node_id!r} has no edge on handle {handle!r}"
                )
            current_node_id = next_id

        # ---- assignTask ----
        elif ntype == "assignTask":
            assignee = cfg.get("assignee", "")
            title = _resolve_tokens(cfg.get("title", ""), context)
            description = _resolve_tokens(cfg.get("description", ""), context)
            if assignee == "RM_OF_CUSTOMER":
                emp_id = context.get("rm_id")
            elif assignee == "OP_OF_CUSTOMER":
                emp_id = context.get("op_id")
            else:
                emp_id = None
            if emp_id is not None:
                await create_task_for_emp(conn, int(emp_id), title, description or None)
            else:
                logger.warning(
                    "flow_engine assignTask run_id=%s assignee=%r emp_id=None; task skipped",
                    run_id, assignee,
                )
            next_id = _next_node(flow_def, current_node_id)
            if next_id is None:
                raise RuntimeError(f"assignTask node {current_node_id!r} has no outgoing edge")
            current_node_id = next_id

        # ---- endFlow ----
        elif ntype == "endFlow":
            await conn.execute(
                f"""
                UPDATE {S}.wa_flow_runs
                SET status = 'completed',
                    current_node_id = $1,
                    context = $2::jsonb,
                    updated_at = now()
                WHERE id = $3
                """,
                current_node_id, json.dumps(context), run_id,
            )
            return  # halt

        else:
            raise RuntimeError(f"unknown node type {ntype!r} at node {current_node_id!r}")

    # If we exit the loop without halting at Wait/EndFlow, update heartbeat and node
    if steps >= MAX_STEPS:
        raise RuntimeError(f"run {run_id} exceeded {MAX_STEPS} steps; possible cycle")

    # Normal mid-chain update (shouldn't reach here; all paths return in handlers)
    await conn.execute(
        f"""
        UPDATE {S}.wa_flow_runs
        SET current_node_id = $1,
            context = $2::jsonb,
            heartbeat_at = now(),
            updated_at = now()
        WHERE id = $3
        """,
        current_node_id, json.dumps(context), run_id,
    )


async def _tick_wa_flow_runs(conn) -> int:
    """Claim and execute up to _TICK_BATCH runnable runs (step 14b).

    Each run is processed in its own transaction; an exception rolls back
    that run's changes and the run is retried on the next tick (reaper backstop).

    Returns total runs processed.
    """
    processed = 0
    for _ in range(_TICK_BATCH):
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    SELECT id, flow_id, flow_version, customer_id, phone,
                           status, current_node_id, context,
                           wait_type, wake_at, heartbeat_at
                    FROM {S}.wa_flow_runs
                    WHERE (
                        status = 'running'
                        OR (
                            status = 'waiting'
                            AND wait_type = 'delay'
                            AND wake_at <= now()
                        )
                    )
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
                if row is None:
                    break

                run = dict(row)
                run_id = str(run["id"])

                # Update heartbeat and advance past Wait node if resuming
                if run["status"] == "waiting" and run["wait_type"] == "delay":
                    # Resume: advance past the wait node to its outgoing edge
                    context = _parse_jsonb(run["context"]) or {}
                    flow_def = context.get("__flow_def") or {}
                    wait_node_id = run["current_node_id"]
                    next_id = _next_node(flow_def, wait_node_id)
                    if next_id is None:
                        raise RuntimeError(
                            f"wait node {wait_node_id!r} has no outgoing edge to resume"
                        )
                    await conn.execute(
                        f"""
                        UPDATE {S}.wa_flow_runs
                        SET status = 'running',
                            wait_type = NULL,
                            wake_at = NULL,
                            current_node_id = $1,
                            heartbeat_at = now(),
                            updated_at = now()
                        WHERE id = $2
                        """,
                        next_id, run_id,
                    )
                    run["current_node_id"] = next_id
                    run["status"] = "running"
                else:
                    # Update heartbeat before processing
                    await conn.execute(
                        f"""
                        UPDATE {S}.wa_flow_runs
                        SET heartbeat_at = now(), updated_at = now()
                        WHERE id = $1
                        """,
                        run_id,
                    )

                await _execute_run(conn, run)
                processed += 1

        except Exception:
            logger.exception("flow_engine step14b error processing run; transaction rolled back")
            # Transaction already rolled back by the async with conn.transaction() context
            # Continue to next run
            continue

    # Stale-run reaper: status='running' with heartbeat_at > 15 min old → failed
    # NEVER touch 'waiting' runs (they may sleep for days)
    await conn.execute(
        f"""
        UPDATE {S}.wa_flow_runs
        SET status = 'failed',
            context = context || '{{"__error": "stale: heartbeat timeout"}}'::jsonb,
            updated_at = now()
        WHERE status = 'running'
          AND heartbeat_at < now() - interval '{_STALE_MINUTES} minutes'
        """
    )

    return processed


# ---------------------------------------------------------------------------
# Step 14c — dispatch outbox
# ---------------------------------------------------------------------------

async def _dispatch_outbox(conn, redis, sink) -> int:
    """Claim-then-release outbox dispatch (step 14c).

    Returns total rows dispatched (sent + cancelled + deferred).
    """
    # Requeue stuck 'sending' rows first (idempotency key protects against double-send)
    await conn.execute(
        f"""
        UPDATE {S}.wa_outbox
        SET status = 'pending', next_retry_at = NULL, updated_at = now()
        WHERE status = 'sending'
          AND updated_at < now() - interval '{_SENDING_STUCK_MINUTES} minutes'
        """
    )

    # Resolve single active instance — skip dispatch if not exactly 1
    instance_rows = await conn.fetch(
        f"SELECT instance_name FROM {S}.wa_instance_config WHERE is_active = true"
    )
    if len(instance_rows) == 0:
        logger.error("flow_engine step14c SKIP: no active wa_instance_config row; dispatch halted")
        return 0
    if len(instance_rows) > 1:
        names = [r["instance_name"] for r in instance_rows]
        logger.error(
            "flow_engine step14c SKIP: %d active wa_instance_config rows (%s); "
            "exactly one required; dispatch halted",
            len(instance_rows), names,
        )
        return 0
    resolved_instance = instance_rows[0]["instance_name"]

    # Claim up to _DISPATCH_BATCH pending rows — short txn, commit immediately
    async with conn.transaction():
        rows = await conn.fetch(
            f"""
            SELECT id, flow_run_id, node_id, phone, body, retry_count, idempotency_key
            FROM {S}.wa_outbox
            WHERE status = 'pending'
              AND (next_retry_at IS NULL OR next_retry_at <= now())
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT {_DISPATCH_BATCH}
            """
        )
        if not rows:
            return 0
        row_ids = [r["id"] for r in rows]
        await conn.executemany(
            f"UPDATE {S}.wa_outbox SET status = 'sending', updated_at = now() WHERE id = $1",
            [(rid,) for rid in row_ids],
        )
    # Transaction committed — locks released; rows are now 'sending'

    dispatched = 0
    for i, row in enumerate(rows):
        if i > 0:
            await asyncio.sleep(2)  # intra-send pacing

        row_id = row["id"]
        phone = row["phone"]
        body = row["body"]
        retry_count = int(row["retry_count"])

        try:
            msg_id = await _svc_send(conn, redis, phone, body, "flow", sink)
            # Success
            await conn.execute(
                f"""
                UPDATE {S}.wa_outbox
                SET status = 'sent',
                    evolution_msg_id = $1,
                    instance_name = $2,
                    sent_at = now(),
                    updated_at = now()
                WHERE id = $3
                """,
                msg_id, resolved_instance, row_id,
            )
            dispatched += 1

        except ConsentError:
            await conn.execute(
                f"""
                UPDATE {S}.wa_outbox
                SET status = 'cancelled', updated_at = now()
                WHERE id = $1
                """,
                row_id,
            )

        except QuietHoursError:
            next_retry = _next_9am_ist()
            await conn.execute(
                f"""
                UPDATE {S}.wa_outbox
                SET status = 'pending',
                    next_retry_at = $1,
                    updated_at = now()
                WHERE id = $2
                """,
                next_retry, row_id,
            )

        except RateLimitError as exc:
            # Distinguish redis-down (5 min retry) from cap-hit (tomorrow 09:00)
            if "Redis unavailable" in str(exc):
                next_retry = datetime.now(pytz.utc) + timedelta(minutes=5)
            else:
                next_retry = _next_9am_ist()
            await conn.execute(
                f"""
                UPDATE {S}.wa_outbox
                SET status = 'pending',
                    next_retry_at = $1,
                    updated_at = now()
                WHERE id = $2
                """,
                next_retry, row_id,
            )

        except EvolutionAPIError:
            new_retry_count = retry_count + 1
            if new_retry_count >= _MAX_RETRIES:
                await conn.execute(
                    f"""
                    UPDATE {S}.wa_outbox
                    SET status = 'failed',
                        retry_count = $1,
                        updated_at = now()
                    WHERE id = $2
                    """,
                    new_retry_count, row_id,
                )
            else:
                backoff_minutes = 2 ** new_retry_count
                next_retry = datetime.now(pytz.utc) + timedelta(minutes=backoff_minutes)
                await conn.execute(
                    f"""
                    UPDATE {S}.wa_outbox
                    SET status = 'pending',
                        retry_count = $1,
                        next_retry_at = $2,
                        updated_at = now()
                    WHERE id = $3
                    """,
                    new_retry_count, next_retry, row_id,
                )

        except Exception:
            logger.exception(
                "flow_engine step14c unexpected error dispatching outbox row_id=%s", row_id
            )
            # Re-queue with a short backoff so we don't drop it
            next_retry = datetime.now(pytz.utc) + timedelta(minutes=5)
            await conn.execute(
                f"""
                UPDATE {S}.wa_outbox
                SET status = 'pending',
                    next_retry_at = $1,
                    updated_at = now()
                WHERE id = $2
                """,
                next_retry, row_id,
            )

    return dispatched


# ---------------------------------------------------------------------------
# Simulation (doc 09 §3.8)
# ---------------------------------------------------------------------------

async def simulate_flow(
    live_data: dict,
    initial_context: dict | None = None,
    simulated_replies: list | None = None,
) -> dict:
    """Run the flow engine in-memory without any DB writes.

    Returns {"trace": [...], "would_send": [...]}.

    Condition nodes use the context value only (no live DB re-read — noted
    as a sim limitation).  Wait(delay) is fast-forwarded with a trace entry.
    Wait(reply) consumes from simulated_replies or follows on_timeout.
    50-step cap.
    """
    context = dict(initial_context or {})
    context.setdefault("__flow_def", live_data)

    trigger_node = _find_trigger_node(live_data)
    if trigger_node is None:
        return {"trace": [], "would_send": [], "error": "no trigger node found"}

    current_node_id: str | None = trigger_node["id"]
    replies_iter = iter(simulated_replies or [])
    trace: list[dict] = []
    would_send: list[dict] = []
    MAX_STEPS = 50

    for step in range(MAX_STEPS):
        if current_node_id is None:
            break
        node = _find_node(live_data, current_node_id)
        if node is None:
            trace.append({
                "node_id": current_node_id,
                "node_type": "UNKNOWN",
                "decision": f"node {current_node_id!r} not found in flow_def",
                "output_handle": None,
            })
            break

        ntype = _ntype(node)
        cfg = (node.get("data") or {}).get("config") or {}

        if ntype in ("scheduledDate", "crmEvent", "inboundKeyword"):
            next_id = _next_node(live_data, current_node_id)
            trace.append({
                "node_id": current_node_id,
                "node_type": ntype,
                "decision": "trigger start",
                "output_handle": "output",
            })
            current_node_id = next_id
            if current_node_id is None:
                break

        elif ntype == "sendMessage":
            body = _resolve_tokens(cfg.get("body", ""), context)
            phone = context.get("phone", "UNKNOWN")
            would_send.append({"to": phone, "body": body})
            trace.append({
                "node_id": current_node_id,
                "node_type": ntype,
                "decision": "message enqueued (sim)",
                "output_handle": "output",
            })
            next_id = _next_node(live_data, current_node_id)
            current_node_id = next_id
            if current_node_id is None:
                break

        elif ntype == "wait":
            wait_type = cfg.get("type")
            if wait_type == "delay":
                delay_minutes = int(cfg.get("delay_minutes", 0))
                trace.append({
                    "node_id": current_node_id,
                    "node_type": ntype,
                    "decision": f"would wait {delay_minutes} minutes (fast-forwarded in sim)",
                    "output_handle": "continue",
                })
                next_id = _next_node(live_data, current_node_id)
                current_node_id = next_id
                if current_node_id is None:
                    break
            else:
                # reply wait — consume simulated reply or follow on_timeout
                reply = next(replies_iter, None)
                if reply is not None:
                    context["inbound_text"] = str(reply)
                    handle = "on_reply"
                    decision = f"consumed simulated reply: {reply!r}"
                else:
                    handle = "on_timeout"
                    decision = "no simulated reply; following on_timeout"
                trace.append({
                    "node_id": current_node_id,
                    "node_type": ntype,
                    "decision": decision,
                    "output_handle": handle,
                })
                next_id = _next_node(live_data, current_node_id, handle)
                current_node_id = next_id
                if current_node_id is None:
                    break

        elif ntype == "condition":
            variable = cfg.get("variable", "")
            operator = cfg.get("operator", "eq")
            expected = str(cfg.get("value", ""))
            # Sim: use snapshot value only (no live DB re-read)
            actual = context.get(variable)
            result = _compare(actual, operator, expected)
            handle = "true_output" if result else "false_output"
            trace.append({
                "node_id": current_node_id,
                "node_type": ntype,
                "decision": f"{variable}={actual!r} {operator} {expected!r} → {result} (snapshot-only in sim)",
                "output_handle": handle,
            })
            next_id = _next_node(live_data, current_node_id, handle)
            current_node_id = next_id
            if current_node_id is None:
                break

        elif ntype == "assignTask":
            assignee = cfg.get("assignee", "")
            title = _resolve_tokens(cfg.get("title", ""), context)
            trace.append({
                "node_id": current_node_id,
                "node_type": ntype,
                "decision": f"would assign task to {assignee}: {title!r} (sim; no DB write)",
                "output_handle": "output",
            })
            next_id = _next_node(live_data, current_node_id)
            current_node_id = next_id
            if current_node_id is None:
                break

        elif ntype == "endFlow":
            trace.append({
                "node_id": current_node_id,
                "node_type": ntype,
                "decision": "flow completed",
                "output_handle": None,
            })
            break

        else:
            trace.append({
                "node_id": current_node_id,
                "node_type": ntype,
                "decision": f"unknown node type {ntype!r}",
                "output_handle": None,
            })
            break
    else:
        trace.append({
            "node_id": current_node_id,
            "node_type": "SIM_CAP",
            "decision": f"simulation halted at {MAX_STEPS}-step cap",
            "output_handle": None,
        })

    return {"trace": trace, "would_send": would_send}
