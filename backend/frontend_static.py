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
        if full_path.startswith(_API_PREFIXES) or full_path in _DOC_PATHS:
            raise HTTPException(status_code=404, detail="Not found")

        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(FRONTEND_DIST / "index.html")
