"""Reusable partial + typo-tolerant fuzzy text filters for GET list endpoints.

Every text column search runs through here. A match is either:
  - a substring / word ILIKE match  (fast: gin_trgm index accelerates ILIKE), OR
  - a pg_trgm word-similarity match at >= 0.5  (typo tolerance: "solvtax" ~ "Solve Tax").

REQUIRES the pg_trgm extension (migration V004). If word_similarity() is used
before that migration is applied, these queries error — apply the migration
before restarting the backend.
"""

from __future__ import annotations

import math
import re
from typing import List, Optional, Sequence, Tuple

# 50% fuzzy match everywhere (word-match ratio for multi-word + trigram threshold).
DEFAULT_NAME_WORD_MATCH_RATIO = 0.5
DEFAULT_TRIGRAM_SIMILARITY = 0.5
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
    use_trigram: bool = True,
    trigram_threshold: float = DEFAULT_TRIGRAM_SIMILARITY,
) -> Tuple[Optional[str], List[object], int]:
    """
    Partial + typo-tolerant fuzzy text match (default 50%):
    - substring: single token -> ILIKE %query%; multi-word -> >= ceil(words*ratio)
      of the words ILIKE-match. Fast via a gin_trgm index on the column.
    - fuzzy: OR word_similarity(query, expr) >= threshold (pg_trgm) so misspellings
      and partial words still match. word_similarity() finds the best-matching run
      of trigrams inside the column, which suits short partial queries.

    trigram_threshold is a trusted constant (never user input) so it is safe to
    inline; the query text itself is always a bound parameter.
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
        # word_similarity(query, column): how well the query matches the closest
        # word/substring inside the column. NULL columns yield NULL -> excluded.
        parts.append(f"word_similarity(${idx}, {sql_expr}) >= {trigram_threshold}")
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


def build_fuzzy_mobile_clause(
    mobile_column: str,
    query: Optional[str],
    start_idx: int,
    *,
    trigram_threshold: float = DEFAULT_TRIGRAM_SIMILARITY,
) -> Tuple[Optional[str], List[object], int]:
    """
    Fuzzy phone-number match on the DIGITS only (ignores spaces/+/-/() on both
    sides). A row matches if the searched digits are a substring of the stored
    number OR the two are >= 50% trigram-similar (so a mistyped digit still hits).
    """
    raw = normalize_search_text(query)
    if not raw:
        return None, [], start_idx
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) < MIN_TEXT_SEARCH_LEN:
        return None, [], start_idx

    # Normalize the stored value to digits too, so formatting never blocks a match.
    norm = f"regexp_replace(COALESCE({mobile_column}, '')::text, '[^0-9]', '', 'g')"
    idx = start_idx
    clause = f"({norm} ILIKE ${idx} OR word_similarity(${idx + 1}, {norm}) >= {trigram_threshold})"
    values: List[object] = [f"%{digits}%", digits]
    return clause, values, idx + 2


def append_fuzzy_mobile_filter(
    conditions: list,
    values: list,
    idx: int,
    mobile_column: str,
    query: Optional[str],
    **kwargs,
) -> int:
    clause, clause_values, idx = build_fuzzy_mobile_clause(mobile_column, query, idx, **kwargs)
    if clause:
        conditions.append(clause)
        values.extend(clause_values)
    return idx
