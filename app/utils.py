import hashlib
import os
import uuid
import re
import asyncpg
import ssl
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
    if v is not None and (len(v) != 15 or not v.isalnum()):
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



async def get_user_permissions(emp_id, conn):
    """
    Fetch all permissions for a user based on their roles (direct and via groups).
    Returns a permissions dict suitable for JWT.
    """
    # DB_SCHEMA is now imported from module level
    # 1. Get all role_ids for the employee (direct and via groups)
    role_ids = set()
    # Direct employee-role assignments
    rows = await conn.fetch(f"""
        SELECT role_id FROM {DB_SCHEMA}.t_us_user_role WHERE emp_id = $1
    """, emp_id)
    for row in rows:
        role_ids.add(row["role_id"])
    # Roles via group membership
    rows = await conn.fetch(f"""
        SELECT ra.role_id
        FROM {DB_SCHEMA}.t_us_group_member gm
        JOIN {DB_SCHEMA}.t_rl_role_assignment ra ON gm.group_id = ra.group_id
        WHERE gm.emp_id = $1
    """, emp_id)
    for row in rows:
        role_ids.add(row["role_id"])
    if not role_ids:
        return {"platform": {}}
    # 2. Get all features/permissions for these roles
    rows = await conn.fetch(f"""
        SELECT f.feature_code, rf.permission_code
        FROM {DB_SCHEMA}.t_rl_role_feature rf
        JOIN {DB_SCHEMA}.t_ft_feature f ON rf.feature_id = f.id
        WHERE rf.role_id = ANY($1::int[])
    """, list(role_ids))
    # 3. Build permissions dict
    permissions = {"platform": {}}
    for row in rows:
        permissions["platform"][row["feature_code"]] = row["permission_code"]
    return permissions