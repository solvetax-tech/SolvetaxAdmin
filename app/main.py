from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import sys

# Add parent directory to path BEFORE imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.token_validator import TokenValidatorMiddleware

load_dotenv()

import logging
import multiprocessing

logging.basicConfig(level=logging.INFO)

from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer

app = FastAPI(title="Slove Tax", version="1.0.0")

# Ensure DB pool is created once per process and closed on shutdown.
from app.utils import get_db_pool, close_db_pool


@app.on_event("startup")
async def _startup_init_db_pool():
    await get_db_pool()


@app.on_event("shutdown")
async def _shutdown_close_db_pool():
    await close_db_pool()

# Add middleware in correct order (they execute in reverse order)
# First add TokenValidator, then CORS - so CORS runs before TokenValidator
app.add_middleware(TokenValidatorMiddleware)

# Add CORS middleware AFTER TokenValidator so it runs FIRST
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",  # Regex to match all origins
    allow_credentials=True,  # Allow credentials
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
    expose_headers=["*"],  # Expose all headers
)

# Add BearerAuth to OpenAPI docs for global JWT authorization
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }
    for path in openapi_schema["paths"].values():
        for method in path.values():
            method.setdefault("security", []).append({"BearerAuth": []})
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Import signup and login routers

from app.sign_up.email_verification import router as email_verification
from app.sign_up.signup import router as signup_router
from app.sign_up.login import router as login_router
from app.sign_up.forgot import router as forgot_password_router
from app.security.teams_api import router as teams_api
from app.sign_up.employee_edit import router as employee_edit_router
from app.customer_registration.customer import router as customer_router
from app.gst_registration.gst_registration import router as gst_registration_router
from app.gst_registration.gst_people import router as gst_people_router
from app.gst_registration.gst_documents import router as gst_documents_router
from app.gst_registration.gst_registration_config import router as gst_registration_config_router
from app.Dashboard.dashboard import router as dashboard_router
from app.version.version import router as version_router
from app.payments.registration_payments import router as registration_payments_router
from app.payments.payments_config import router as payments_config
from app.gst_registration.gst_blob import router as gst_blob
from app.gst_registration.document_config import router as document_config
from app.customer_registration.services import router as services
from app.customer_registration.service_config import router as service_config




if email_verification:
    app.include_router(email_verification)
if signup_router:
    app.include_router(signup_router)
if login_router:
    app.include_router(login_router)
if forgot_password_router:
    app.include_router(forgot_password_router)
if teams_api:
    app.include_router(teams_api)
if customer_router:
    app.include_router(customer_router)
if gst_registration_router:
    app.include_router(gst_registration_router)
if gst_people_router:
    app.include_router(gst_people_router)
if employee_edit_router:
    app.include_router(employee_edit_router)
if gst_registration_config_router:
    app.include_router(gst_registration_config_router)
if gst_documents_router:
    app.include_router(gst_documents_router)
if dashboard_router:
    app.include_router(dashboard_router)
if version_router:
    app.include_router(version_router)
if registration_payments_router:
    app.include_router(registration_payments_router)
if payments_config:
    app.include_router(payments_config)
if gst_blob:
    app.include_router(gst_blob)
if document_config:
    app.include_router(document_config)
if services:
    app.include_router(services)
if service_config:
    app.include_router(service_config)


@app.get("/health")
async def health_check():
    return {"status": "ok"}

# Production runner with uvicorn
if __name__ == "__main__":
    import uvicorn

    # IMPORTANT: Each worker is a separate process and will create its own DB pool.
    # Keep this low for Azure Postgres connection limits; override via WORKERS env var.
    workers = int(os.getenv("WORKERS", "1"))

    # Get host and port from environment or use defaults
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))

    # Production configuration
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        workers=workers,
        loop="asyncio",  # Use default asyncio event loop
        access_log=True,
        log_level="info"
    )