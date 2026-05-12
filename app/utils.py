import hashlib
import os
import uuid
import re
import asyncpg
import asyncio
import ssl
import logging
import logging
from datetime import datetime
from typing import Dict, Any
from asyncpg.exceptions import PostgresError
from dotenv import load_dotenv
from typing import Optional
from dataclasses import dataclass
from azure.storage.blob import BlobServiceClient
from urllib.parse import urlparse

# Load .env from project root
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Make DB_SCHEMA available at module level
DB_SCHEMA = os.getenv("DB_SCHEMA", "solvetax")

# Redis configuration from .env
# Supports both existing keys (host/port/password) and REDIS_* variants.
REDIS_HOST = (os.getenv("REDIS_HOST") or os.getenv("host") or "").strip()
REDIS_PORT = int((os.getenv("REDIS_PORT") or os.getenv("port") or "6379").strip())
REDIS_PASSWORD = (os.getenv("REDIS_PASSWORD") or os.getenv("password") or "").strip()


@dataclass(frozen=True)
class AzureOpenAIBusinessDescriptionSettings:
    endpoint: str
    api_key: str
    deployment: str
    api_version: str
    timeout_sec: int


def get_azure_openai_business_description_settings() -> AzureOpenAIBusinessDescriptionSettings:
    raw_timeout = os.getenv("AZURE_OPENAI_TIMEOUT_SEC", "45").strip() or "45"
    try:
        timeout_sec = max(5, int(raw_timeout))
    except ValueError:
        timeout_sec = 45
    return AzureOpenAIBusinessDescriptionSettings(
        endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY", "").strip(),
        deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip(),
        api_version=(
            os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview").strip()
            or "2024-12-01-preview"
        ),
        timeout_sec=timeout_sec,
    )


def is_business_description_ai_configured() -> bool:
    s = get_azure_openai_business_description_settings()
    return bool(s.endpoint and s.deployment and s.api_key)


_db_pool = None
_db_pool_lock = asyncio.Lock()


import hashlib

def hash_password(password: str) -> str:
    hash_obj = hashlib.sha512()
    hash_obj.update(password.encode("utf-8"))
    return hash_obj.hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    hash_obj = hashlib.sha512()
    hash_obj.update(password.encode("utf-8"))
    computed_hash = hash_obj.hexdigest()

    return computed_hash == stored_hash


def is_password_strong(password: str) -> bool:
    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"[0-9]", password):
        return False
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False
    return True


def generate_uuid() -> str:
    return str(uuid.uuid4())


async def get_db_pool():
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
   

    print(
        f"[DB DEBUG] DB_HOST={DB_HOST} DB_PORT={DB_PORT} "
        f"DB_NAME={DB_NAME} DB_USER={DB_USER} DB_SCHEMA={DB_SCHEMA}"
    )

    if not DB_HOST or not DB_NAME or not DB_USER:
        raise RuntimeError("Database environment variables are not loaded")

    global _db_pool
    if _db_pool is None:
        async with _db_pool_lock:
            if _db_pool is None:
                ssl_context = ssl.create_default_context()
                pool_min_size = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
                pool_max_size = int(os.getenv("DB_POOL_MAX_SIZE", "5"))
                app_name = os.getenv("DB_APP_NAME", "slovetax-api")
                _db_pool = await asyncpg.create_pool(
                    host=DB_HOST,
                    port=DB_PORT,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD,
                    ssl=ssl_context,
                    command_timeout=60,
                    min_size=pool_min_size,
                    max_size=pool_max_size,
                    max_inactive_connection_lifetime=60,
                    server_settings={"application_name": app_name},
                )

    return _db_pool


async def close_db_pool() -> None:
    global _db_pool
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None


def mask_sensitive_data(data: Optional[str]) -> str:
    if not data:
        return ""

    data = data.strip()

    # Email masking
    if "@" in data:
        try:
            name, domain = data.split("@", 1)
            if len(name) <= 2:
                masked_name = "*" * len(name)
            else:
                masked_name = name[:2] + "*" * (len(name) - 2)
            return f"{masked_name}@{domain}"
        except Exception:
            return "***"

    # Mobile / numeric masking
    if data.isdigit():
        if len(data) <= 4:
            return "*" * len(data)
        return data[:2] + "*" * (len(data) - 4) + data[-2:]

    # Generic masking
    if len(data) <= 4:
        return "*" * len(data)

    return data[:2] + "*" * (len(data) - 4) + data[-2:]



def passwords_match(password1: str, password2: str) -> bool:
    
    return password1 == password2


def employee_report_tree_subquery(schema: str, idx: int) -> str:
    """
    Active employees under emp_id's reporting tree (recursive ``manager_emp_id``),
    including emp_id as root. Used for manager visibility instead of team tables.
    """
    return (
        f"(WITH RECURSIVE report_tree AS ("
        f" SELECT emp_id FROM {schema}.employees WHERE emp_id = ${idx}"
        f" AND COALESCE(is_active, TRUE)"
        f" UNION ALL"
        f" SELECT e.emp_id FROM {schema}.employees e"
        f" INNER JOIN report_tree r ON e.manager_emp_id = r.emp_id"
        f" WHERE COALESCE(e.is_active, TRUE)"
        f") SELECT emp_id FROM report_tree)"
    )


def build_customer_visibility(role: str, emp_id: int, idx: int, schema: str):

    # --------------------------------------------------
    # ADMIN → Full Access
    # --------------------------------------------------
    if role == "ADMIN":
        return None, [], idx

    # --------------------------------------------------
    # RM → Own Customers
    # --------------------------------------------------
    if role == "RM":
        if not emp_id:
            return "1=0", [], idx
        return f"c.rm_id = ${idx}", [emp_id], idx + 1

    # --------------------------------------------------
    # OP → Own Customers
    # --------------------------------------------------
    if role == "OP":
        if not emp_id:
            return "1=0", [], idx
        return f"c.op_id = ${idx}", [emp_id], idx + 1

    # --------------------------------------------------
    # Managers → reporting-tree customers (rm/op slots)
    # --------------------------------------------------
    if role in ["SALES_MANAGER", "OP_MANAGER"]:
        if not emp_id:
            return "1=0", [], idx
        tree = employee_report_tree_subquery(schema, idx)
        sql = f"(c.rm_id IN {tree} OR c.op_id IN {tree})"
        return sql, [emp_id], idx + 1

    # --------------------------------------------------
    # Everyone else → only rows assigned to them as RM or OP
    # --------------------------------------------------
    if not emp_id:
        return "1=0", [], idx
    return f"(c.rm_id = ${idx} OR c.op_id = ${idx})", [emp_id], idx + 1
def build_gst_visibility(role: str, emp_id: int, idx: int, schema: str):
    

    if role == "ADMIN":
        return None, [], idx

    if role == "RM":
        if not emp_id:
            return "1=0", [], idx
        return f"g.rm_id = ${idx}", [emp_id], idx + 1

    if role == "OP":
        if not emp_id:
            return "1=0", [], idx
        return f"g.created_by = ${idx}", [emp_id], idx + 1

    if role in ["SALES_MANAGER", "OP_MANAGER"]:
        if not emp_id:
            return "1=0", [], idx
        tree = employee_report_tree_subquery(schema, idx)
        sql = f"(g.rm_id IN {tree} OR g.created_by IN {tree})"
        return sql, [emp_id], idx + 1

    if not emp_id:
        return "1=0", [], idx
    return f"(g.rm_id = ${idx} OR g.created_by = ${idx})", [emp_id], idx + 1
def build_gst_filing_visibility(role: str, emp_id: int, idx: int, schema: str):

    if role == "ADMIN":
        return None, [], idx

    if role == "RM":
        if not emp_id:
            return "1=0", [], idx
        return f"f.rm_id = ${idx}", [emp_id], idx + 1

    if role == "OP":
        if not emp_id:
            return "1=0", [], idx
        return f"f.op_id = ${idx}", [emp_id], idx + 1

    if role in ["SALES_MANAGER", "OP_MANAGER"]:
        if not emp_id:
            return "1=0", [], idx
        tree = employee_report_tree_subquery(schema, idx)
        sql = f"(f.rm_id IN {tree} OR f.op_id IN {tree})"
        return sql, [emp_id], idx + 1

    if not emp_id:
        return "1=0", [], idx
    return f"(f.rm_id = ${idx} OR f.op_id = ${idx})", [emp_id], idx + 1


def build_income_tax_visibility(
    role: str,
    emp_id: int,
    idx: int,
    schema: str,
    alias: str = "i",
):
    if role == "ADMIN":
        return None, [], idx

    if role == "RM":
        if not emp_id:
            return "1=0", [], idx
        return f"{alias}.rm_id = ${idx}", [emp_id], idx + 1

    if role == "OP":
        if not emp_id:
            return "1=0", [], idx
        return f"{alias}.op_id = ${idx}", [emp_id], idx + 1

    if role in ["SALES_MANAGER", "OP_MANAGER"]:
        if not emp_id:
            return "1=0", [], idx
        tree = employee_report_tree_subquery(schema, idx)
        sql = f"({alias}.rm_id IN {tree} OR {alias}.op_id IN {tree})"
        return sql, [emp_id], idx + 1

    if not emp_id:
        return "1=0", [], idx
    return f"({alias}.rm_id = ${idx} OR {alias}.op_id = ${idx})", [emp_id], idx + 1
def build_customer_service_visibility(role: str, emp_id: int, idx: int, schema: str):

    # ADMIN → Full access
    if role == "ADMIN":
        return None, [], idx

    # RM → Own services
    if role == "RM":
        if not emp_id:
            return "1=0", [], idx
        return f"cs.rm_id = ${idx}", [emp_id], idx + 1

    # OP → Own services
    if role == "OP":
        if not emp_id:
            return "1=0", [], idx
        return f"cs.op_id = ${idx}", [emp_id], idx + 1

    if role in ["SALES_MANAGER", "OP_MANAGER"]:
        if not emp_id:
            return "1=0", [], idx
        tree = employee_report_tree_subquery(schema, idx)
        sql = f"(cs.rm_id IN {tree} OR cs.op_id IN {tree})"
        return sql, [emp_id], idx + 1

    if not emp_id:
        return "1=0", [], idx
    return f"(cs.rm_id = ${idx} OR cs.op_id = ${idx})", [emp_id], idx + 1


def build_filing_followup_assignment_visibility(role: str, emp_id: int, idx: int, schema: str):
    """
    Row visibility for ``customer_service_followups`` (alias ``f``) by ``f.assigned_to`` (emp_id).

    - ADMIN: no extra predicate (see all).
    - RM / OP: only followups assigned to the current employee.
    - SALES_MANAGER / OP_MANAGER: ``f.assigned_to`` is in their reporting subtree (``manager_emp_id`` chain).
    - Other roles: only followups assigned to themselves.
    """
    if role == "ADMIN":
        return None, [], idx

    if role in ("RM", "OP"):
        if emp_id is None:
            return "1=0", [], idx
        return f"f.assigned_to = ${idx}", [emp_id], idx + 1

    if role in ["SALES_MANAGER", "OP_MANAGER"]:
        if emp_id is None:
            return "1=0", [], idx
        tree = employee_report_tree_subquery(schema, idx)
        sql = f"f.assigned_to IN {tree}"
        return sql, [emp_id], idx + 1

    if emp_id is None or not emp_id:
        return "1=0", [], idx
    return f"f.assigned_to = ${idx}", [emp_id], idx + 1


async def get_user_permissions(emp_id: int, conn, DB_SCHEMA="solvetax") -> Dict[str, Any]:
    try:
        # ✅ 1) fetch role ids for this employee
        rows = await conn.fetch(
            f"""
            SELECT role_id
            FROM {DB_SCHEMA}.employee_roles
            WHERE emp_id = $1 AND is_active = true
            """,
            emp_id,
        )

        role_ids = [r["role_id"] for r in rows]

        if not role_ids:
            logging.info(f"[permissions] No roles found for emp_id={emp_id}")
            return {"platform": {}}

        # ✅ 2) fetch feature permissions for those roles
        rows = await conn.fetch(
            f"""
            SELECT f.feature_code, rf.permission_code
            FROM {DB_SCHEMA}.role_features rf
            JOIN {DB_SCHEMA}.features f ON rf.feature_id = f.id
            WHERE rf.role_id = ANY($1::bigint[]) AND rf.is_active = true
            """,
            role_ids
        )

        permissions = {"platform": {}}

        for row in rows:
            feature = row["feature_code"]
            perm = row["permission_code"]

            permissions["platform"].setdefault(feature, set()).add(perm)

        # ✅ convert set → list for JWT JSON
        for feature in permissions["platform"]:
            permissions["platform"][feature] = sorted(list(permissions["platform"][feature]))

        logging.info(f"[permissions] emp_id={emp_id} permissions={permissions}")
        return permissions

    except Exception as e:
        logging.error(f"[permissions] Error fetching permissions for emp_id={emp_id}: {e}")
        return {"platform": {}}

import secrets
import hashlib

# --------------------------------------------------
# Generate Secure Refresh Token
# --------------------------------------------------
def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


# --------------------------------------------------
# Hash Refresh Token (Store only hash in DB)
# --------------------------------------------------
def hash_refresh_token(refresh_token: str) -> str:
    hash_obj = hashlib.sha256()
    hash_obj.update(refresh_token.encode("utf-8"))
    return hash_obj.hexdigest()

# --------------------------------------------------
# Azure Blob Storage Configuration
# --------------------------------------------------

from azure.storage.blob import BlobServiceClient

AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_STORAGE_CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER")
# Customer business image uploads (separate container from GST documents)
AZURE_STORAGE_CONTAINER1 = os.getenv("AZURE_STORAGE_CONTAINER1", "").strip()

if not AZURE_STORAGE_CONNECTION_STRING:
    raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is missing in .env")

if not AZURE_STORAGE_CONTAINER:
    raise RuntimeError("AZURE_STORAGE_CONTAINER is missing in .env")


# --------------------------------------------------
# Lazy Singleton Blob Client
# --------------------------------------------------

_blob_service_client = None


def get_blob_service_client() -> BlobServiceClient:
    global _blob_service_client

    if _blob_service_client is None:
        _blob_service_client = BlobServiceClient.from_connection_string(
            AZURE_STORAGE_CONNECTION_STRING
        )

    return _blob_service_client


import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from app.logger import logger

load_dotenv()

async def send_email_otp(email: str, otp: str):

    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT"))
    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not all([smtp_server, smtp_port, smtp_email, smtp_password]):
        raise RuntimeError("SMTP configuration missing")

    subject = "SolveTax Password Reset OTP"

    body = f"""
Hello,

Your OTP for resetting your SolveTax account password is:

{otp}

This OTP will expire in 10 minutes.

If you did not request this, please ignore this email.

Regards,
SolveTax Security Team
"""

    message = MIMEMultipart()
    message["From"] = smtp_email
    message["To"] = email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, email, message.as_string())

        logger.info("OTP email sent successfully to %s", email)

    except Exception as e:
        logger.error("Email sending failed for %s | Error: %s", email, str(e))
        raise
    
async def send_email_otp(email: str, otp: str, purpose: str = "password_reset"):

    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT"))
    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not all([smtp_server, smtp_port, smtp_email, smtp_password]):
        raise RuntimeError("SMTP configuration missing")

    # --------------------------------------------------
    # Email Content
    # --------------------------------------------------

    if purpose == "email_verification":

        subject = "SolveTax Email Verification OTP"

        body = f"""
Hello,

Welcome to SolveTax.

Your OTP for verifying your SolveTax account email is:

{otp}

This OTP will expire in 10 minutes.

If you did not initiate this verification, please ignore this email.

Regards,
SolveTax Security Team
"""

    else:

        subject = "SolveTax Password Reset OTP"

        body = f"""
Hello,

Your OTP for resetting your SolveTax account password is:

{otp}

This OTP will expire in 10 minutes.

If you did not request this, please ignore this email.

Regards,
SolveTax Security Team
"""

    message = MIMEMultipart()
    message["From"] = smtp_email
    message["To"] = email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, email, message.as_string())

        logger.info("OTP email sent successfully to %s | purpose=%s", email, purpose)

    except Exception as e:
        logger.error("Email sending failed for %s | Error: %s", email, str(e))
        raise

# --------------------------------------------------
# Generate Secure SAS URL for Blob
# --------------------------------------------------

from azure.storage.blob import generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, quote, unquote
import os
import mimetypes

AZURE_SAS_EXPIRY_MINUTES = int(os.getenv("AZURE_SAS_EXPIRY_MINUTES", 15))


def generate_blob_sas_url(blob_path: str, disposition: str = "inline") -> str:

    blob_service_client = get_blob_service_client()

    account_name = blob_service_client.account_name
    account_key = blob_service_client.credential.account_key

    # Extract filename
    filename = blob_path.split("/")[-1]

    # Set content disposition
    if disposition == "attachment":
        content_disposition = f'attachment; filename="{filename}"'
    else:
        content_disposition = "inline"

    # Guess content type for preview
    content_type, _ = mimetypes.guess_type(filename)
    if not content_type:
        # Fallback based on extension if mimetypes fails
        ext = filename.split(".")[-1].lower()
        if ext == "pdf": content_type = "application/pdf"
        elif ext in ["jpg", "jpeg"]: content_type = "image/jpeg"
        elif ext == "png": content_type = "image/png"

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=AZURE_STORAGE_CONTAINER,
        blob_name=blob_path,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(minutes=AZURE_SAS_EXPIRY_MINUTES),
        content_disposition=content_disposition,
        content_type=content_type,
    )

    # URL encode the blob path for the final URL
    encoded_blob_path = quote(blob_path)

    url = (
        f"https://{account_name}.blob.core.windows.net/"
        f"{AZURE_STORAGE_CONTAINER}/{encoded_blob_path}?{sas_token}"
    )

    return url


# --------------------------------------------------
# Extract Blob Path From URL
# --------------------------------------------------

def extract_blob_path(blob_url: str) -> str:
    """
    Extract blob path safely from Azure blob URL and unquote it.
    """

    parsed_url = urlparse(blob_url)

    if not parsed_url.path:
        raise ValueError("Invalid blob URL")

    # Path starts with /container_name/
    prefix = f"/{AZURE_STORAGE_CONTAINER}/"
    path = parsed_url.path

    if path.startswith(prefix):
        blob_path = path[len(prefix):]
    else:
        # Fallback if container is not at start (unlikely for standard Azure URLs)
        blob_path = path.replace(prefix, "", 1).lstrip("/")

    if not blob_path:
        raise ValueError("Blob path could not be extracted")

    # Unquote to get the raw blob name (e.g., %20 -> space)
    return unquote(blob_path)