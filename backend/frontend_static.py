"""Serve the Vite production build from ../frontend/dist."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

_API_PREFIXES = ("/api/", "/app/v1/")
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json", "/health")


def frontend_dist_exists() -> bool:
    return FRONTEND_DIST.is_dir() and (FRONTEND_DIST / "index.html").is_file()


def mount_frontend(app: FastAPI) -> None:
    if not frontend_dist_exists():
        return

    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # The path param arrives without a leading slash (e.g. "api/foo"), while
        # our prefixes are absolute — normalize before matching so real API/doc
        # routes 404 instead of silently returning index.html.
        normalized = "/" + full_path
        if normalized.startswith(_API_PREFIXES) or normalized in _DOC_PATHS:
            raise HTTPException(status_code=404, detail="Not found")

        dist_root = FRONTEND_DIST.resolve()
        index_file = dist_root / "index.html"
        if full_path:
            candidate = (dist_root / full_path).resolve()
            # Containment check: reject any path that escapes the dist directory
            # (e.g. "../../etc/passwd") before serving it.
            if candidate.is_file() and dist_root in candidate.parents:
                return FileResponse(candidate)

        return FileResponse(index_file)
