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
from azure.storage.blob import BlobServiceClient
from urllib.parse import urlparse

# Load .env from project root
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Make DB_SCHEMA available at module level
DB_SCHEMA = os.getenv("DB_SCHEMA", "solvetax")

# --------------------------------------------------
# Asyncpg pool (singleton per process)
# Keep pool sizes small for Azure Postgres connection limits.
# --------------------------------------------------
_db_pool = None
_db_pool_lock = asyncio.Lock()


def hash_password(password: str) -> str:
    hash_obj = hashlib.sha512()
    hash_obj.update(password.encode("utf-8"))
    return hash_obj.hexdigest()


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
    # DB_SCHEMA is now imported from module level

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
    """
    Returns True if both passwords are exactly the same, False otherwise.
    """
    return password1 == password2



async def get_user_permissions(emp_id: int, conn, DB_SCHEMA="solvetax") -> Dict[str, Any]:
    """
    Fetch permissions from DB based on employee_roles only (no group_roles).

    Returns format:
    {
      "platform": {
         "EMPLOYEE": ["READ", "WRITE"],
         "USER_ACCESS": ["READ"]
      }
    }
    """
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

# --------------------------------------------------
# Generate Secure SAS URL for Blob
# --------------------------------------------------

from azure.storage.blob import generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
from urllib.parse import urlparse
import os

AZURE_SAS_EXPIRY_MINUTES = int(os.getenv("AZURE_SAS_EXPIRY_MINUTES", 15))


def generate_blob_sas_url(blob_path: str, disposition: str = "inline") -> str:
    """
    Generate temporary SAS URL for viewing or downloading blob.

    disposition:
        inline      -> preview in browser
        attachment  -> force download
    """

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

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=AZURE_STORAGE_CONTAINER,
        blob_name=blob_path,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(minutes=AZURE_SAS_EXPIRY_MINUTES),
        content_disposition=content_disposition,
    )

    url = (
        f"https://{account_name}.blob.core.windows.net/"
        f"{AZURE_STORAGE_CONTAINER}/{blob_path}?{sas_token}"
    )

    return url


# --------------------------------------------------
# Extract Blob Path From URL
# --------------------------------------------------

def extract_blob_path(blob_url: str) -> str:
    """
    Extract blob path safely from Azure blob URL.
    """

    parsed_url = urlparse(blob_url)

    if not parsed_url.path:
        raise ValueError("Invalid blob URL")

    blob_path = parsed_url.path.replace(f"/{AZURE_STORAGE_CONTAINER}/", "")

    if not blob_path:
        raise ValueError("Blob path could not be extracted")

    return blob_path