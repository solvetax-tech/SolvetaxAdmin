"""Business description via Azure OpenAI (Microsoft Foundry). See app.utils for env vars."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import aiohttp

from backend.utils import get_azure_openai_business_description_settings

MAX_OUTPUT_CHARS = 2000

SYSTEM_PROMPT = """You write short professional business descriptions for a tax / compliance CRM in India.
Rules:
- Output plain text only (no markdown, no bullet labels).
- 2–4 sentences, professional tone.
- Infer cautiously from the facts given; do not invent legal status, turnover, or registrations not stated.
- Do not repeat email addresses or phone numbers in the description.
- If almost no business context is given, write a neutral one-line description using only the customer or business name if provided."""


def _extract_message_content(data: dict) -> Optional[str]:
    choices = data.get("choices") or []
    if not choices:
        return None
    msg = (choices[0] or {}).get("message") or {}
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


async def request_business_description(
    body: Dict[str, Any],
    *,
    log: Optional[logging.LoggerAdapter] = None,
) -> Optional[str]:
    cfg = get_azure_openai_business_description_settings()
    if not (cfg.endpoint and cfg.deployment and cfg.api_key):
        if log:
            log.warning("Azure OpenAI settings incomplete (endpoint, deployment, api_key)")
        return None

    url = (
        f"{cfg.endpoint}/openai/deployments/{cfg.deployment}/chat/completions"
        f"?api-version={cfg.api_version}"
    )
    user_content = (
        "Using only the JSON facts below, write the business description.\n\n"
        + json.dumps(body, ensure_ascii=False, default=str)
    )
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.4,
        "max_tokens": 400,
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": cfg.api_key,
    }
    timeout = aiohttp.ClientTimeout(total=max(5, cfg.timeout_sec))

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                raw = await resp.text()
                if resp.status != 200:
                    if log:
                        log.warning(
                            "Azure OpenAI HTTP %s | body=%s",
                            resp.status,
                            raw[:800],
                        )
                    return None
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    if log:
                        log.warning("Azure OpenAI invalid JSON")
                    return None
                text = _extract_message_content(data)
    except (aiohttp.ClientError, TimeoutError) as e:
        if log:
            log.warning("Azure OpenAI request failed | %s", e)
        return None

    if not text:
        return None
    text = text.strip()
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[: MAX_OUTPUT_CHARS - 1].rstrip() + "…"
    return text
