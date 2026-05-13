from fastapi import Request, HTTPException, status
import os
import jwt
from typing import Optional


JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


def get_employee_payload_if_bearer(request: Request) -> Optional[dict]:
    """
    Returns decoded JWT when Authorization: Bearer <token> is present and valid.
    Returns None when the header is absent (e.g. public API key flows).
    Raises HTTPException 401 when Bearer is present but token is invalid/expired.
    """
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1]
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_user_payload(request: Request) -> dict:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_permission(feature: str, permission: str):
    """
    Usage:
    Depends(require_permission("USER_ACCESS","WRITE"))
    """
    async def checker(request: Request):
        payload = get_current_user_payload(request)

        perms = payload.get("permissions", {}).get("platform", {})
        feature_perms = perms.get(feature, [])

        # ✅ optional: WRITE implies READ
        if permission == "READ" and "WRITE" in feature_perms:
            return payload

        if permission not in feature_perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: missing {feature}:{permission}"
            )

        return payload

    return checker


def require_admin():
    """
    Restrict route to employees whose JWT role is ADMIN.
    """
    async def checker(request: Request):
        payload = get_current_user_payload(request)
        role = str(payload.get("role") or "").strip().upper()
        if role != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: admin only",
            )
        return payload

    return checker
