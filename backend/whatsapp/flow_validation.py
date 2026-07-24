"""Pure-function flow graph validation.

validate_flow(draft) -> list[dict]

Implements the 7 server-side checks documented in doc 09 §3.7:
  1. Exactly one trigger node (inboundKeyword|scheduledDate|crmEvent) and
     it is the start (no incoming edges).
  2. All non-start nodes reachable from start via BFS over edges.
  3. Every condition node has both true_output and false_output handles
     connected as sourceHandles.
  4. Every wait(type='reply') node has both on_reply and on_timeout handles
     connected as sourceHandles.
  5. At least one endFlow node reachable from start.
  6. All required config fields non-empty per node type.
  7. DFS cycle detection (reported as check='cycle').

No database access — fully unit-testable.

Issue shape: {"node_id": str | None, "check": str, "message": str}
"""
from __future__ import annotations

from collections import deque
from typing import Any

_TRIGGER_TYPES: frozenset[str] = frozenset({"inboundKeyword", "scheduledDate", "crmEvent"})

# Required non-empty config fields per node type.
# endFlow has no required fields.
_REQUIRED_CONFIG: dict[str, tuple[str, ...]] = {
    "inboundKeyword":  ("keyword", "match_mode"),
    "scheduledDate":   ("source", "days_before"),
    "crmEvent":        ("event_type",),
    "sendMessage":     ("body",),
    "assignTask":      ("assignee", "title"),
    "updateCrmField":  ("field", "value"),
    "condition":       ("variable", "operator", "value"),
    "wait":            ("type",),
    "endFlow":         (),
}


def _issue(node_id: str | None, check: str, message: str) -> dict[str, Any]:
    return {"node_id": node_id, "check": check, "message": message}


def _is_empty(val: Any) -> bool:
    """True when a config field value is missing or blank."""
    if val is None:
        return True
    if isinstance(val, str) and not val.strip():
        return True
    return False


def _ntype(node: dict[str, Any]) -> str:
    """Logical node type.

    The canvas serializes every node with the React Flow renderer type
    ('waNode') and stores the logical type in data.nodeType; plain API
    payloads may put it directly in 'type'.  (QA bug 1, 2026-07-24.)
    """
    data = node.get("data") or {}
    return data.get("nodeType") or node.get("type") or ""


def validate_flow(draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate a draft_data graph (reactFlowInstance.toObject() shape).

    Returns a list of issue dicts; empty list means the graph is valid and
    safe to publish.
    """
    nodes: list[dict] = draft.get("nodes") or []
    edges: list[dict] = draft.get("edges") or []
    issues: list[dict] = []

    node_by_id: dict[str, dict] = {n["id"]: n for n in nodes}

    # Adjacency list: source_id -> [(target_id, sourceHandle)]
    adj: dict[str, list[tuple[str, str]]] = {n["id"]: [] for n in nodes}
    # Count incoming edges per node (used to verify trigger is the start).
    in_degree: dict[str, int] = {n["id"]: 0 for n in nodes}
    # Set of (source_id, sourceHandle) pairs for handle-connection checks.
    connected_handles: set[tuple[str, str]] = set()

    for e in edges:
        src = e.get("source", "")
        tgt = e.get("target", "")
        handle = e.get("sourceHandle") or ""
        if src in adj:
            adj[src].append((tgt, handle))
        if tgt in in_degree:
            in_degree[tgt] += 1
        connected_handles.add((src, handle))

    # ------------------------------------------------------------------
    # Check 1: exactly one trigger node; it must be the start (no in-edges)
    # ------------------------------------------------------------------
    trigger_nodes = [n for n in nodes if _ntype(n) in _TRIGGER_TYPES]

    if len(trigger_nodes) == 0:
        issues.append(_issue(
            None, "trigger_node",
            "Flow must have exactly one trigger node "
            "(inboundKeyword, scheduledDate, or crmEvent); none found",
        ))
        return issues  # remaining checks are meaningless without a trigger

    if len(trigger_nodes) > 1:
        for n in trigger_nodes:
            issues.append(_issue(
                n["id"], "trigger_node",
                f"Flow must have exactly one trigger node; "
                f"found {len(trigger_nodes)} (remove extras)",
            ))
        return issues  # ambiguous start node; skip BFS checks

    trigger = trigger_nodes[0]
    trigger_id = trigger["id"]

    if in_degree.get(trigger_id, 0) > 0:
        issues.append(_issue(
            trigger_id, "trigger_node",
            "Trigger node must have no incoming edges (it must be the start node)",
        ))

    # ------------------------------------------------------------------
    # Cycle detection (DFS from trigger)
    # ------------------------------------------------------------------
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def _dfs(node_id: str) -> bool:
        """Return True if a cycle is detected."""
        visited.add(node_id)
        rec_stack.add(node_id)
        for tgt, _ in adj.get(node_id, []):
            if tgt not in node_by_id:
                continue
            if tgt not in visited:
                if _dfs(tgt):
                    return True
            elif tgt in rec_stack:
                return True
        rec_stack.discard(node_id)
        return False

    if _dfs(trigger_id):
        issues.append(_issue(
            None, "cycle",
            "Flow graph contains a cycle; remove the back-edge to publish",
        ))
        return issues  # BFS reachability is unreliable with a cycle

    # ------------------------------------------------------------------
    # BFS: reachability + endFlow presence
    # ------------------------------------------------------------------
    reachable: set[str] = set()
    queue: deque[str] = deque([trigger_id])
    has_end_flow = False

    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        n = node_by_id.get(current)
        if n and _ntype(n) == "endFlow":
            has_end_flow = True
        for tgt, _ in adj.get(current, []):
            if tgt in node_by_id and tgt not in reachable:
                queue.append(tgt)

    # ------------------------------------------------------------------
    # Check 2: all non-start nodes reachable
    # ------------------------------------------------------------------
    for n in nodes:
        if n["id"] != trigger_id and n["id"] not in reachable:
            issues.append(_issue(
                n["id"], "unreachable_node",
                f"Node '{_ntype(n) or n['id']}' (id={n['id']!r}) "
                "is not reachable from the start node",
            ))

    # ------------------------------------------------------------------
    # Check 3: condition nodes have both output handles connected
    # ------------------------------------------------------------------
    for n in nodes:
        if _ntype(n) == "condition":
            nid = n["id"]
            if (nid, "true_output") not in connected_handles:
                issues.append(_issue(
                    nid, "condition_handles",
                    "Condition node is missing a 'true_output' edge",
                ))
            if (nid, "false_output") not in connected_handles:
                issues.append(_issue(
                    nid, "condition_handles",
                    "Condition node is missing a 'false_output' edge",
                ))

    # ------------------------------------------------------------------
    # Check 4: wait(reply) nodes have both resume handles connected
    # ------------------------------------------------------------------
    for n in nodes:
        if _ntype(n) == "wait":
            config = (n.get("data") or {}).get("config") or {}
            if config.get("type") == "reply":
                nid = n["id"]
                if (nid, "on_reply") not in connected_handles:
                    issues.append(_issue(
                        nid, "wait_reply_handles",
                        "Wait(reply) node is missing an 'on_reply' edge",
                    ))
                if (nid, "on_timeout") not in connected_handles:
                    issues.append(_issue(
                        nid, "wait_reply_handles",
                        "Wait(reply) node is missing an 'on_timeout' edge",
                    ))

    # ------------------------------------------------------------------
    # Check 5: at least one endFlow reachable from start
    # ------------------------------------------------------------------
    if not has_end_flow:
        issues.append(_issue(
            None, "no_end_flow",
            "Flow must have at least one reachable EndFlow node",
        ))

    # ------------------------------------------------------------------
    # Check 6: required config fields non-empty per node type
    # ------------------------------------------------------------------
    for n in nodes:
        ntype = _ntype(n)
        required = _REQUIRED_CONFIG.get(ntype)
        if required is None:
            # Unknown node type — skip (forward-compatible)
            continue
        config = (n.get("data") or {}).get("config") or {}
        for field in required:
            if _is_empty(config.get(field)):
                issues.append(_issue(
                    n["id"], "missing_config",
                    f"Node '{ntype}' is missing required config field '{field}'",
                ))

        # wait(delay) additionally requires delay_minutes
        if ntype == "wait" and config.get("type") == "delay":
            if _is_empty(config.get("delay_minutes")):
                issues.append(_issue(
                    n["id"], "missing_config",
                    "Wait(delay) node is missing required config field 'delay_minutes'",
                ))
        # wait(reply) additionally requires timeout_hours
        if ntype == "wait" and config.get("type") == "reply":
            if _is_empty(config.get("timeout_hours")):
                issues.append(_issue(
                    n["id"], "missing_config",
                    "Wait(reply) node is missing required config field 'timeout_hours'",
                ))

    return issues
