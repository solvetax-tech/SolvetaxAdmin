"""Unit tests for validate_flow() — all 6 checks + cycle detection.

No database access — pure function tests that run in any environment.

Coverage
--------
- Check 1  trigger_node   : 0 triggers, 2 triggers, trigger has incoming edge
- Check 2  unreachable_node: node not connected to the start
- Check 3  condition_handles: condition missing true_output or false_output
- Check 4  wait_reply_handles: wait(reply) missing on_reply or on_timeout
- Check 5  no_end_flow    : no endFlow reachable
- Check 6  missing_config : required field absent or blank
- Cycle    DFS detects back-edge
- Valid    GSTR-3B shaped graph passes all checks (empty issues list)
"""
import pytest

from backend.whatsapp.flow_validation import validate_flow


# ---------------------------------------------------------------------------
# Graph building helpers
# ---------------------------------------------------------------------------

def _node(node_id: str, ntype: str, config: dict | None = None) -> dict:
    return {"id": node_id, "type": ntype, "data": {"config": config or {}}}


def _edge(edge_id: str, src: str, tgt: str,
          src_handle: str = "output", tgt_handle: str = "input") -> dict:
    return {
        "id": edge_id,
        "source": src,
        "target": tgt,
        "sourceHandle": src_handle,
        "targetHandle": tgt_handle,
    }


def _draft(nodes: list, edges: list) -> dict:
    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 1}}


# ---------------------------------------------------------------------------
# GSTR-3B shaped valid graph — used for the "happy path" test
# Graph:  scheduledDate → sendMessage → wait(delay) → condition
#                                                    ↙ true_output: sendMessage2 → endFlow2
#                                                    ↘ false_output: endFlow1
# ---------------------------------------------------------------------------

def _gstr3b_graph() -> dict:
    """Valid 7-node GSTR-3B reminder flow; all 6 checks must pass."""
    nodes = [
        _node("t1", "scheduledDate",
              {"source": "gstr3b_due_date", "days_before": 7}),
        _node("n1", "sendMessage",
              {"body": "Your GSTR-3B is due in 7 days. Please share sales data."}),
        _node("n2", "wait",
              {"type": "delay", "delay_minutes": 2880}),
        _node("n3", "condition",
              {"variable": "filing_status", "operator": "neq", "value": "FILED"}),
        _node("n4", "sendMessage",
              {"body": "Reminder: GSTR-3B still pending. Please file now."}),
        _node("n5", "endFlow", {}),   # false_output branch (already filed)
        _node("n6", "endFlow", {}),   # after follow-up
    ]
    edges = [
        _edge("e1", "t1", "n1"),
        _edge("e2", "n1", "n2"),
        _edge("e3", "n2", "n3"),
        _edge("e4", "n3", "n4", src_handle="true_output"),   # filing_status != FILED
        _edge("e5", "n3", "n5", src_handle="false_output"),  # already filed
        _edge("e6", "n4", "n6"),
    ]
    return _draft(nodes, edges)


# ---------------------------------------------------------------------------
# Check 1 — trigger_node
# ---------------------------------------------------------------------------

def test_check1_no_trigger_node():
    """No trigger node → issue with check='trigger_node'."""
    draft = _draft(
        nodes=[_node("n1", "sendMessage", {"body": "Hi"}), _node("n2", "endFlow", {})],
        edges=[_edge("e1", "n1", "n2")],
    )
    issues = validate_flow(draft)
    assert any(i["check"] == "trigger_node" for i in issues), issues


def test_check1_two_trigger_nodes():
    """Two trigger nodes → issues for both."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("t2", "inboundKeyword", {"keyword": "GST", "match_mode": "equals"}),
            _node("n1", "endFlow", {}),
        ],
        edges=[_edge("e1", "t1", "n1")],
    )
    issues = validate_flow(draft)
    trigger_issues = [i for i in issues if i["check"] == "trigger_node"]
    assert len(trigger_issues) >= 2, issues


def test_check1_trigger_has_incoming_edge():
    """Trigger node with an incoming edge → issue (it must be the start)."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "endFlow", {}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "t1"),  # back-edge to trigger (cycle + incoming)
        ],
    )
    issues = validate_flow(draft)
    # Could be cycle or trigger_node issue; either way graph is invalid
    assert issues, "Expected validation issues for trigger with incoming edge"


# ---------------------------------------------------------------------------
# Check 2 — unreachable_node
# ---------------------------------------------------------------------------

def test_check2_orphaned_node():
    """Node not connected to the start → unreachable_node issue."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "endFlow", {}),
            _node("n2", "sendMessage", {"body": "orphan"}),  # not reachable
        ],
        edges=[_edge("e1", "t1", "n1")],
    )
    issues = validate_flow(draft)
    assert any(
        i["check"] == "unreachable_node" and i["node_id"] == "n2"
        for i in issues
    ), issues


# ---------------------------------------------------------------------------
# Check 3 — condition_handles
# ---------------------------------------------------------------------------

def test_check3_condition_missing_true_output():
    """Condition node with only false_output → missing true_output issue."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "condition",
                  {"variable": "filing_status", "operator": "eq", "value": "FILED"}),
            _node("n2", "endFlow", {}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "n2", src_handle="false_output"),  # only false_output
        ],
    )
    issues = validate_flow(draft)
    assert any(
        i["check"] == "condition_handles" and "true_output" in i["message"]
        for i in issues
    ), issues


def test_check3_condition_missing_false_output():
    """Condition node with only true_output → missing false_output issue."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "condition",
                  {"variable": "filing_status", "operator": "eq", "value": "FILED"}),
            _node("n2", "endFlow", {}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "n2", src_handle="true_output"),  # only true_output
        ],
    )
    issues = validate_flow(draft)
    assert any(
        i["check"] == "condition_handles" and "false_output" in i["message"]
        for i in issues
    ), issues


# ---------------------------------------------------------------------------
# Check 4 — wait_reply_handles
# ---------------------------------------------------------------------------

def test_check4_wait_reply_missing_on_timeout():
    """wait(reply) with only on_reply → missing on_timeout issue."""
    draft = _draft(
        nodes=[
            _node("t1", "inboundKeyword", {"keyword": "GST", "match_mode": "equals"}),
            _node("n1", "wait", {"type": "reply", "timeout_hours": 24}),
            _node("n2", "endFlow", {}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "n2", src_handle="on_reply"),  # no on_timeout
        ],
    )
    issues = validate_flow(draft)
    assert any(
        i["check"] == "wait_reply_handles" and "on_timeout" in i["message"]
        for i in issues
    ), issues


def test_check4_wait_reply_missing_on_reply():
    """wait(reply) with only on_timeout → missing on_reply issue."""
    draft = _draft(
        nodes=[
            _node("t1", "inboundKeyword", {"keyword": "GST", "match_mode": "equals"}),
            _node("n1", "wait", {"type": "reply", "timeout_hours": 24}),
            _node("n2", "endFlow", {}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "n2", src_handle="on_timeout"),  # no on_reply
        ],
    )
    issues = validate_flow(draft)
    assert any(
        i["check"] == "wait_reply_handles" and "on_reply" in i["message"]
        for i in issues
    ), issues


def test_check4_wait_delay_does_not_require_reply_handles():
    """wait(delay) nodes are NOT checked for on_reply/on_timeout."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "wait", {"type": "delay", "delay_minutes": 60}),
            _node("n2", "endFlow", {}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "n2"),
        ],
    )
    issues = validate_flow(draft)
    assert not any(i["check"] == "wait_reply_handles" for i in issues), issues


# ---------------------------------------------------------------------------
# Check 5 — no_end_flow
# ---------------------------------------------------------------------------

def test_check5_no_end_flow_reachable():
    """Graph with no endFlow node → no_end_flow issue."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "sendMessage", {"body": "Reminder"}),
        ],
        edges=[_edge("e1", "t1", "n1")],
    )
    issues = validate_flow(draft)
    assert any(i["check"] == "no_end_flow" for i in issues), issues


# ---------------------------------------------------------------------------
# Check 6 — missing_config
# ---------------------------------------------------------------------------

def test_check6_scheduled_date_missing_days_before():
    """scheduledDate missing days_before → missing_config issue."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date"}),  # no days_before
            _node("n1", "endFlow", {}),
        ],
        edges=[_edge("e1", "t1", "n1")],
    )
    issues = validate_flow(draft)
    assert any(
        i["check"] == "missing_config" and "days_before" in i["message"]
        for i in issues
    ), issues


def test_check6_send_message_missing_body():
    """sendMessage with empty body → missing_config issue."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "sendMessage", {"body": ""}),  # blank body
            _node("n2", "endFlow", {}),
        ],
        edges=[_edge("e1", "t1", "n1"), _edge("e2", "n1", "n2")],
    )
    issues = validate_flow(draft)
    assert any(
        i["check"] == "missing_config" and "body" in i["message"]
        for i in issues
    ), issues


def test_check6_condition_missing_operator():
    """condition missing operator → missing_config issue."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "condition",
                  {"variable": "filing_status", "value": "FILED"}),  # no operator
            _node("n2", "endFlow", {}),
            _node("n3", "endFlow", {}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "n2", src_handle="true_output"),
            _edge("e3", "n1", "n3", src_handle="false_output"),
        ],
    )
    issues = validate_flow(draft)
    assert any(
        i["check"] == "missing_config" and "operator" in i["message"]
        for i in issues
    ), issues


def test_check6_wait_delay_missing_delay_minutes():
    """wait(delay) missing delay_minutes → missing_config issue."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "wait", {"type": "delay"}),  # no delay_minutes
            _node("n2", "endFlow", {}),
        ],
        edges=[_edge("e1", "t1", "n1"), _edge("e2", "n1", "n2")],
    )
    issues = validate_flow(draft)
    assert any(
        i["check"] == "missing_config" and "delay_minutes" in i["message"]
        for i in issues
    ), issues


def test_check6_wait_reply_missing_timeout_hours():
    """wait(reply) missing timeout_hours → missing_config issue."""
    draft = _draft(
        nodes=[
            _node("t1", "inboundKeyword", {"keyword": "GST", "match_mode": "equals"}),
            _node("n1", "wait", {"type": "reply"}),  # no timeout_hours
            _node("n2", "endFlow", {}),
            _node("n3", "endFlow", {}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "n2", src_handle="on_reply"),
            _edge("e3", "n1", "n3", src_handle="on_timeout"),
        ],
    )
    issues = validate_flow(draft)
    assert any(
        i["check"] == "missing_config" and "timeout_hours" in i["message"]
        for i in issues
    ), issues


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

def test_cycle_two_node_loop():
    """Two nodes that point to each other → cycle issue."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "sendMessage", {"body": "A"}),
            _node("n2", "sendMessage", {"body": "B"}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "n2"),
            _edge("e3", "n2", "n1"),  # back-edge → cycle
        ],
    )
    issues = validate_flow(draft)
    assert any(i["check"] == "cycle" for i in issues), issues


def test_cycle_self_loop():
    """Node pointing to itself → cycle."""
    draft = _draft(
        nodes=[
            _node("t1", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _node("n1", "sendMessage", {"body": "loop"}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "n1"),  # self-loop
        ],
    )
    issues = validate_flow(draft)
    assert any(i["check"] == "cycle" for i in issues), issues


# ---------------------------------------------------------------------------
# Valid graph — all checks pass
# ---------------------------------------------------------------------------

def test_gstr3b_valid_graph_passes():
    """GSTR-3B shaped graph must have zero validation issues."""
    issues = validate_flow(_gstr3b_graph())
    assert issues == [], f"Expected no issues, got: {issues}"


def test_empty_nodes_edges_fails_gracefully():
    """Empty draft returns issues, not an exception."""
    issues = validate_flow({})
    assert isinstance(issues, list)
    assert len(issues) > 0  # at minimum: no trigger node


def test_inbound_keyword_valid_graph():
    """InboundKeyword trigger with wait(reply) — both handles connected → valid."""
    draft = _draft(
        nodes=[
            _node("t1", "inboundKeyword", {"keyword": "GST", "match_mode": "equals"}),
            _node("n1", "wait", {"type": "reply", "timeout_hours": 24}),
            _node("n2", "endFlow", {}),
            _node("n3", "endFlow", {}),
        ],
        edges=[
            _edge("e1", "t1", "n1"),
            _edge("e2", "n1", "n2", src_handle="on_reply"),
            _edge("e3", "n1", "n3", src_handle="on_timeout"),
        ],
    )
    issues = validate_flow(draft)
    assert issues == [], f"Expected no issues, got: {issues}"


def _canvas_node(nid, node_type, config=None):
    """Node exactly as the React Flow canvas serializes it (QA bug 1 regression):
    renderer type 'waNode', logical type in data.nodeType."""
    return {
        "id": nid,
        "type": "waNode",
        "position": {"x": 0, "y": 0},
        "data": {"nodeType": node_type, "config": config or {}},
    }


def test_canvas_serialization_shape_valid_graph():
    """A canvas-serialized (waNode) GSTR-3B graph must validate clean."""
    draft = {
        "nodes": [
            _canvas_node("t", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _canvas_node("m1", "sendMessage", {"body": "reminder"}),
            _canvas_node("w", "wait", {"type": "delay", "delay_minutes": 2880}),
            _canvas_node("c", "condition", {"variable": "filing_status", "operator": "neq", "value": "FILED"}),
            _canvas_node("m2", "sendMessage", {"body": "follow-up"}),
            _canvas_node("task", "assignTask", {"assignee": "RM_OF_CUSTOMER", "title": "Chase filing"}),
            _canvas_node("end", "endFlow"),
        ],
        "edges": [
            {"id": "e1", "source": "t", "sourceHandle": "output", "target": "m1"},
            {"id": "e2", "source": "m1", "sourceHandle": "output", "target": "w"},
            {"id": "e3", "source": "w", "sourceHandle": "continue", "target": "c"},
            {"id": "e4", "source": "c", "sourceHandle": "true_output", "target": "m2"},
            {"id": "e5", "source": "c", "sourceHandle": "false_output", "target": "end"},
            {"id": "e6", "source": "m2", "sourceHandle": "output", "target": "task"},
            {"id": "e7", "source": "task", "sourceHandle": "output", "target": "end"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    assert validate_flow(draft) == []


def test_canvas_serialization_shape_catches_missing_handle():
    """waNode-shaped graph with a disconnected condition handle must be caught."""
    draft = {
        "nodes": [
            _canvas_node("t", "scheduledDate", {"source": "gstr3b_due_date", "days_before": 7}),
            _canvas_node("c", "condition", {"variable": "filing_status", "operator": "neq", "value": "FILED"}),
            _canvas_node("end", "endFlow"),
        ],
        "edges": [
            {"id": "e1", "source": "t", "sourceHandle": "output", "target": "c"},
            {"id": "e2", "source": "c", "sourceHandle": "true_output", "target": "end"},
        ],
    }
    issues = validate_flow(draft)
    assert any(i["check"] == "condition_handles" and i["node_id"] == "c" for i in issues)
