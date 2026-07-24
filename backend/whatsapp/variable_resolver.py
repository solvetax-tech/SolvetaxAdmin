"""Variable resolver for WhatsApp flow message bodies.

Replaces {{variable_name}} tokens in message body text with values from
the run's context dict.  Only the 12-token whitelist is resolved; unrecognised
tokens are left as-is in the output (so staff see the literal placeholder and
can diagnose a mis-typed variable rather than getting a silent empty string).

12-token whitelist (doc 09 §3.3):
    customer_name, gst_number, gstr3b_due_date, gstr1_due_date,
    payment_amount_due, payment_due_date, rm_name, op_name,
    filing_status, pipeline_stage, income_tax_year, pending_documents_count

Unit-testable; no database access.
"""
from __future__ import annotations

import re
from typing import Any

_WHITELIST: frozenset[str] = frozenset({
    "customer_name",
    "gst_number",
    "gstr3b_due_date",
    "gstr1_due_date",
    "payment_amount_due",
    "payment_due_date",
    "rm_name",
    "op_name",
    "filing_status",
    "pipeline_stage",
    "income_tax_year",
    "pending_documents_count",
})

_TOKEN_RE = re.compile(r"\{\{([^}]+)\}\}")


def resolve(body: str, context: dict[str, Any]) -> str:
    """Replace whitelisted {{tokens}} in *body* from *context*.

    - Whitelisted token present in context  → substituted value (str-coerced).
    - Whitelisted token absent from context → left as {{token}}.
    - Unknown token                         → left as {{token}} (not in whitelist).
    """
    def _replace(m: re.Match) -> str:
        name = m.group(1).strip()
        if name not in _WHITELIST:
            return m.group(0)  # leave unknown tokens intact
        val = context.get(name)
        if val is None:
            return m.group(0)  # leave whitelisted-but-absent tokens intact
        return str(val)

    return _TOKEN_RE.sub(_replace, body)
