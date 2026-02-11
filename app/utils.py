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


def passwords_match(password1: str, password2: str) -> bool:
    """
    Returns True if both passwords are exactly the same, False otherwise.
    """
    return password1 == password2



def validate_mobile(v):
    if v is not None and (not v.isdigit() or len(v) != 10):
        raise ValueError('Mobile number must be exactly 10 digits')
    return v

def validate_gstin(v):
    if v is not None and (not v.isdigit() or len(v) != 15):
        raise ValueError('GSTIN must be exactly 15 alphanumeric characters')
    return v

def validate_pan(v):
    if v is not None:
        pattern = re.compile("^[A-Z]{5}[0-9]{4}[A-Z]$")
        if not pattern.match(v):
            raise ValueError('PAN must be 10 characters: 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F)')
    return v

def validate_aadhaar(v):
    if v is not None:
        if not (v.isdigit() and len(v) == 12):
            raise ValueError('Aadhaar must be exactly 12 digits')
    return v

def validate_email(v):
    if v is not None:
        email_regex = r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"
        if not re.match(email_regex, v):
            raise ValueError('Invalid email address')
    return v

def validate_url(v):
    if v is not None:
        url_regex = re.compile(
            r'^(https?://)?'  # http:// or https://
            r'(([A-Za-z0-9-]+\.)+[A-Za-z]{2,6})'  # domain...
            r'(:\d+)?'  # optional port
            r'(/[-A-Za-z0-9@:%._\+~#=]*)*'  # path
            r'(\?[;&A-Za-z0-9%_.,=+-]*)?'  # query string
            r'(#[A-Za-z0-9_-]*)?$'  # fragment locator
        )
        if not url_regex.match(v):
            raise ValueError('Invalid URL')
    return v

async def check_duplicate_mobile_pan_aadhaar_for_gstin(pool, gstin: str, mobile: str = None, pan: str = None, aadhaar: str = None, exclude_id: str = None):
    conditions = ["gstin = $1"]
    values = [gstin]

    if mobile:
        conditions.append("mobile = ${}".format(len(values) + 1))
        values.append(mobile)
    if pan:
        conditions.append("pan = ${}".format(len(values) + 1))
        values.append(pan)
    if aadhaar:
        conditions.append("aadhaar = ${}".format(len(values) + 1))
        values.append(aadhaar)

    if exclude_id:
        conditions.append("id != ${}".format(len(values) + 1))
        values.append(exclude_id)

    where_clause = " AND ".join(conditions)

    sql = f"SELECT 1 FROM {DB_SCHEMA}.gst_registration WHERE {where_clause} LIMIT 1"

    exists = await pool.fetchval(sql, *values)
    return bool(exists)


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
