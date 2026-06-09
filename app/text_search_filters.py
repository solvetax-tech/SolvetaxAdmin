"""Reusable partial/fuzzy text filters for GET list endpoints (~30-40% word match)."""

from __future__ import annotations

import math
import re
from typing import List, Optional, Sequence, Tuple

# Default: 35% of query words must match (within requested 30-40% band).
DEFAULT_NAME_WORD_MATCH_RATIO = 0.35
DEFAULT_TRIGRAM_SIMILARITY = 0.35
MIN_TEXT_SEARCH_LEN = 2


def normalize_search_text(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def split_search_words(query: str) -> List[str]:
    return [w for w in re.split(r"\s+", query.strip()) if len(w) >= MIN_TEXT_SEARCH_LEN]


def build_fuzzy_name_clause(
    sql_expr: str,
    query: Optional[str],
    start_idx: int,
    *,
    word_match_ratio: float = DEFAULT_NAME_WORD_MATCH_RATIO,
    use_trigram: bool = False,
    trigram_threshold: float = DEFAULT_TRIGRAM_SIMILARITY,
) -> Tuple[Optional[str], List[object], int]:
    """
    Fuzzy name match without pg_trgm by default:
    - single token: ILIKE %query%
    - multi-word: >= ceil(word_count * ratio) words must ILIKE-match
    - optional: OR similarity(expr, query) >= threshold (pg_trgm)
    """
    raw = normalize_search_text(query)
    if not raw or len(raw) < MIN_TEXT_SEARCH_LEN:
        return None, [], start_idx

    words = split_search_words(raw)
    parts: List[str] = []
    values: List[object] = []
    idx = start_idx

    if len(words) <= 1:
        parts.append(f"{sql_expr} ILIKE ${idx}")
        values.append(f"%{raw}%")
        idx += 1
    else:
        min_match = max(1, math.ceil(len(words) * word_match_ratio))
        word_cases: List[str] = []
        for word in words:
            word_cases.append(f"CASE WHEN {sql_expr} ILIKE ${idx} THEN 1 ELSE 0 END")
            values.append(f"%{word}%")
            idx += 1
        parts.append(f"(({' + '.join(word_cases)}) >= {min_match})")

    if use_trigram:
        parts.append(f"similarity({sql_expr}, ${idx}) >= {trigram_threshold}")
        values.append(raw)
        idx += 1

    clause = parts[0] if len(parts) == 1 else f"({' OR '.join(parts)})"
    return clause, values, idx


def append_fuzzy_name_filter(
    conditions: list,
    values: list,
    idx: int,
    sql_expr: str,
    query: Optional[str],
    **kwargs,
) -> int:
    clause, clause_values, idx = build_fuzzy_name_clause(sql_expr, query, idx, **kwargs)
    if clause:
        conditions.append(clause)
        values.extend(clause_values)
    return idx


def append_fuzzy_name_or_filter(
    conditions: list,
    values: list,
    idx: int,
    sql_exprs: Sequence[str],
    query: Optional[str],
    **kwargs,
) -> int:
    """OR fuzzy match across multiple columns (e.g. full_name OR business_name)."""
    raw = normalize_search_text(query)
    if not raw or len(raw) < MIN_TEXT_SEARCH_LEN:
        return idx

    or_parts: List[str] = []
    for expr in sql_exprs:
        clause, clause_values, next_idx = build_fuzzy_name_clause(expr, raw, idx, **kwargs)
        if clause:
            or_parts.append(f"({clause})")
            values.extend(clause_values)
            idx = next_idx
    if or_parts:
        conditions.append(f"({' OR '.join(or_parts)})")
    return idx


def append_ilike_contains(
    conditions: list,
    values: list,
    idx: int,
    sql_expr: str,
    query: Optional[str],
) -> int:
    raw = normalize_search_text(query)
    if not raw:
        return idx
    conditions.append(f"{sql_expr} ILIKE ${idx}")
    values.append(f"%{raw}%")
    return idx + 1
