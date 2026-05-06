"""
Run analytics smoke endpoint and print proof.

Required env:
- API_BASE_URL (example: http://127.0.0.1:8000)
- PUBLIC_API_KEY
- ANALYTICS_DEBUG_TOKEN
"""

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    api_base = (os.getenv("API_BASE_URL") or "").strip().rstrip("/")
    public_api_key = (os.getenv("PUBLIC_API_KEY") or "").strip()
    debug_token = (os.getenv("ANALYTICS_DEBUG_TOKEN") or "").strip()

    missing = []
    if not api_base:
        missing.append("API_BASE_URL")
    if not public_api_key:
        missing.append("PUBLIC_API_KEY")
    if not debug_token:
        missing.append("ANALYTICS_DEBUG_TOKEN")
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}")
        return 2

    url = f"{api_base}/api/v1/event-logs/debug/smoke"
    req = urllib.request.Request(
        url=url,
        method="POST",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "X-Public-Api-Key": public_api_key,
            "X-Analytics-Debug-Token": debug_token,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            body = response.read().decode("utf-8")
            payload = json.loads(body)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8")
        print(f"HTTP {err.code}: {detail}")
        return 1
    except Exception as err:
        print(f"Failed to call smoke endpoint: {err}")
        return 1

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
