from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from starlette.exceptions import HTTPException as StarletteHTTPException
from dotenv import load_dotenv
import os
import sys

# Add parent directory to path BEFORE imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.token_validator import TokenValidatorMiddleware

load_dotenv()

import logging
import multiprocessing

logging.basicConfig(level=logging.INFO)

from fastapi.openapi.utils import get_openapi
from starlette.middleware.base import BaseHTTPMiddleware

# Environment flag — set APP_ENV=production in prod to disable interactive API
# docs and enable HSTS. Defaults to development so local runs are unaffected.
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
_is_production = APP_ENV in ("production", "prod")

# Optional error tracking (Sentry). No-op unless SENTRY_DSN is set AND the SDK is
# installed — never breaks environments that don't configure it.
_SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=APP_ENV,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        )
        logging.info("Sentry error tracking enabled")
    except Exception:
        logging.warning(
            "SENTRY_DSN set but sentry_sdk unavailable; error tracking disabled",
            exc_info=True,
        )

app = FastAPI(
    title="Slove Tax",
    version="1.0.0",
    # Don't expose the full API schema / interactive docs in production.
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

# Ensure DB pool is created once per process and closed on shutdown.
from backend.utils import get_db_pool, close_db_pool
from backend.redis_cache import close_redis_client
from backend.schedular.schedular import start_scheduler_if_enabled, stop_scheduler
import asyncio

@app.on_event("startup")
async def _startup_init_db_pool():
    await get_db_pool()
    # Indexes are no longer created here. They live in db/migrations/ (see
    # 2026-07-17_performance_indexes.sql) and are applied deliberately, because
    # a failed CREATE INDEX CONCURRENTLY leaves an INVALID index that
    # IF NOT EXISTS then skips forever -- so retrying at every boot never
    # repaired it, it only hid it behind a warning log.
    start_scheduler_if_enabled()


@app.on_event("shutdown")
async def _shutdown_close_db_pool():
    await stop_scheduler()
    await close_db_pool()
    await close_redis_client()

# Add middleware in correct order (they execute in reverse order)
# First add TokenValidator, then CORS - so CORS runs before TokenValidator
app.add_middleware(TokenValidatorMiddleware)

# Add CORS middleware AFTER TokenValidator so it runs FIRST.
# Explicit allow-list from ALLOWED_ORIGINS (comma-separated). Reflecting any
# origin with credentials is unsafe, so we never use a wildcard here. Defaults
# to local dev origins; set ALLOWED_ORIGINS in prod (e.g. https://admin.example.com).
_default_cors_origins = "http://localhost:5174,http://127.0.0.1:5174,http://localhost:5173"
_allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", _default_cors_origins).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,  # safe now that origins are an explicit allow-list
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set baseline security response headers on every response.

    Note: we deliberately DON'T set a resource-restricting CSP (default-src/
    img-src) here — the app renders customer documents/images from Azure Blob
    SAS URLs, so a strict CSP would break them. We only set frame-ancestors
    (anti-clickjacking); a tuned full CSP is a follow-up.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        # HSTS only in production (over HTTPS); harmless-but-noise on local HTTP.
        if _is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        return response


# Added last → outermost, so headers land on every response (incl. errors).
app.add_middleware(SecurityHeadersMiddleware)


# --------------------------------------------------
# Global exception handlers — consistent envelope, no internal leakage, full
# server-side logging (also feeds Sentry when configured). Without these, an
# unhandled error returns FastAPI's default 500 with no structured log line.
# --------------------------------------------------
_err_logger = logging.getLogger("FastAPIApp")


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "Request validation failed", "errors": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception):
    # Explicitly-raised HTTP errors keep their intended status/detail.
    if isinstance(exc, (StarletteHTTPException, HTTPException)):
        return JSONResponse(
            status_code=getattr(exc, "status_code", 500),
            content={"detail": getattr(exc, "detail", "Error")},
            headers=getattr(exc, "headers", None) or {},
        )
    # Truly unhandled: log full detail server-side, return a generic 500.
    _err_logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})

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
            "bearerFormat": "JWT",
        },
        "PublicApiKey": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Public-Api-Key",
        },
    }

    public_api_key_paths = {
        "/api/v1/crm/leads/marketing",
        "/api/v1/customers",
        "/api/v1/contact-support",
        "/api/v1/event-logs",
        "/api/v1/event-logs/debug/smoke",
        "/api/v1/payments_config/payment-config/public",
        "/api/v1/payments_config/payment-config/public/service-prices",
    }

    for path_key, path_item in openapi_schema["paths"].items():
        for method_name, operation in path_item.items():
            if path_key in public_api_key_paths:
                operation["security"] = [{"PublicApiKey": []}]
            else:
                operation.setdefault("security", []).append({"BearerAuth": []})
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Import signup and login routers

from backend.sign_up.email_verification import router as email_verification
from backend.sign_up.signup import router as signup_router
from backend.sign_up.login import router as login_router
from backend.sign_up.forgot import router as forgot_password_router
from backend.sign_up.employee_edit import router as employee_edit_router
from backend.customer_registration.customer import router as customer_router
from backend.gst_registration.gst_registration import router as gst_registration_router
from backend.gst_registration.gst_people import router as gst_people_router
from backend.gst_registration.gst_documents import router as gst_documents_router
from backend.gst_registration.gst_registration_config import router as gst_registration_config_router
from backend.version.version import router as version_router
from backend.payments.registration_payments import router as registration_payments_router
from backend.payments.gst_filing_payments import router as gst_filing_payments_router
from backend.payments.gst_filing_return_details_payments import (
    router as gst_filing_return_details_payments_router,
)
from backend.payments.income_tax_payments import router as income_tax_payments_router
from backend.payments.customer_service_payments import router as customer_service_payments_router
from backend.payments.payments_config import router as payments_config
from backend.gst_registration.gst_blob import router as gst_blob
from backend.gst_registration.document_config import router as document_config
from backend.follow_ups.customer_service_followups import router as customer_service_followups_router
from backend.follow_ups.payments_followup import router as payments_followup_router
from backend.customer_registration.entity_types import router as entity_types_router
from backend.gst_registration_filing.gst_filing_config import router as gst_filing_config
from backend.gst_registration_filing.gst_registration_filing import router as gst_registration_filing
from backend.gst_registration_filing.gst_filing_document import router as gst_filing_document_router
from backend.crm.crm_leads_gst import router as crm_leads_router
from backend.crm.crm_leads_common import router as crm_leads_common_router
from backend.crm.crm_leads_itr import router as crm_leads_itr_router
from backend.gst_registration_filing.gst_filing_rule_engine import router as gst_filing_rule_engine_router
from backend.Income_tax.income_tax import router as income_tax_router
from backend.Income_tax.income_tax_config import router as income_tax_config_router
from backend.contact_support.contact_support import router as contact_support_router
from backend.campaign.campaign import router as campaign_router
from backend.customer_service.customer_service import router as customer_service_staff_router
from backend.customer_service.service_config import router as customer_service_config_router
from backend.issue_reports.issue_reports import router as issue_reports_router
from backend.employee_tasks.employee_tasks import router as employee_tasks_router
from backend.Dashboard.service_done_payment_pending import router as dashboard_router
from backend.Dashboard.gst_filing_monthly_matrix import router as gst_filing_matrix_router


if email_verification:
    app.include_router(email_verification)
if signup_router:
    app.include_router(signup_router)
if login_router:
    app.include_router(login_router)
if forgot_password_router:
    app.include_router(forgot_password_router)
if customer_router:
    app.include_router(customer_router)
if gst_registration_router:
    app.include_router(gst_registration_router)
if gst_people_router:
    app.include_router(gst_people_router)
if employee_edit_router:
    app.include_router(employee_edit_router)
if gst_documents_router:
    app.include_router(gst_documents_router)
if gst_registration_config_router:
    app.include_router(gst_registration_config_router)
if gst_registration_filing:
    app.include_router(gst_registration_filing)
if gst_filing_document_router:
    app.include_router(gst_filing_document_router)
if gst_filing_config:
    app.include_router(gst_filing_config)
if version_router:
    app.include_router(version_router)
if registration_payments_router:
    app.include_router(registration_payments_router)
if gst_filing_payments_router:
    app.include_router(gst_filing_payments_router)
if gst_filing_return_details_payments_router:
    app.include_router(gst_filing_return_details_payments_router)
if income_tax_payments_router:
    app.include_router(income_tax_payments_router)
if customer_service_payments_router:
    app.include_router(customer_service_payments_router)
if payments_config:
    app.include_router(payments_config)
if gst_blob:
    app.include_router(gst_blob)
if document_config:
    app.include_router(document_config)
if customer_service_followups_router:
    app.include_router(customer_service_followups_router)
if payments_followup_router:
    app.include_router(payments_followup_router)
if entity_types_router:
    app.include_router(entity_types_router)
if crm_leads_router:
    app.include_router(crm_leads_router)
if crm_leads_common_router:
    app.include_router(crm_leads_common_router)
if crm_leads_itr_router:
    app.include_router(crm_leads_itr_router)
if gst_filing_rule_engine_router:
    app.include_router(gst_filing_rule_engine_router)
if income_tax_router:
    app.include_router(income_tax_router)
if income_tax_config_router:
    app.include_router(income_tax_config_router)
if contact_support_router:
    app.include_router(contact_support_router)
if campaign_router:
    app.include_router(campaign_router)
if customer_service_staff_router:
    app.include_router(customer_service_staff_router)
if customer_service_config_router:
    app.include_router(customer_service_config_router)
if issue_reports_router:
    app.include_router(issue_reports_router)
if employee_tasks_router:
    app.include_router(employee_tasks_router)
if dashboard_router:
    app.include_router(dashboard_router)
if gst_filing_matrix_router:
    app.include_router(gst_filing_matrix_router)

@app.get("/health")
async def health_check():
    """Liveness — cheap, no dependencies. For load-balancer 'is the process up'."""
    return {"status": "ok"}


@app.get("/ready")
async def readiness_check():
    """Readiness — checks DB and Redis so a load balancer stops routing to an
    instance whose dependencies are down. Returns 503 if the DB is unreachable.
    Redis is reported but non-fatal (the app fails open on Redis outage)."""
    import asyncio as _asyncio
    from backend.redis_cache import redis_ping, is_redis_configured

    db_ok = False
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await _asyncio.wait_for(conn.execute("SELECT 1"), timeout=3)
        db_ok = True
    except Exception:
        db_ok = False

    if is_redis_configured():
        try:
            redis_ok = await _asyncio.wait_for(redis_ping(), timeout=2)
        except Exception:
            redis_ok = False
    else:
        redis_ok = None  # not configured → not a readiness dependency

    ready = db_ok  # DB is the hard dependency
    body = {"status": "ready" if ready else "not_ready", "db": db_ok, "redis": redis_ok}
    return JSONResponse(status_code=200 if ready else 503, content=body)


from backend.frontend_static import mount_frontend

mount_frontend(app)

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
        "backend.main:app",
        host=host,
        port=port,
        workers=workers,
        loop="asyncio",  # Use default asyncio event loop
        access_log=True,
        log_level="info"
    )