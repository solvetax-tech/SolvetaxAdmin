import hashlib
import os
import uuid
import re
import asyncpg
import ssl
import logging
import logging
from datetime import datetime
from typing import Dict, Any
from asyncpg.exceptions import PostgresError
from dotenv import load_dotenv
from typing import Optional
from azure.storage.blob import BlobServiceClient


# Load .env from project root
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Make DB_SCHEMA available at module level
DB_SCHEMA = os.getenv("DB_SCHEMA", "solvetax")


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

    if not hasattr(get_db_pool, "pool"):
        ssl_context = ssl.create_default_context()
        get_db_pool.pool = await asyncpg.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            ssl=ssl_context,
            command_timeout=60,
        )

    return get_db_pool.pool


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