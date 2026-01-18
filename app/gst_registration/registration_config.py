from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from app.utils import get_db_pool, DB_SCHEMA
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/registration-config",
    tags=["Registration Config"]
)

class RegistrationConfigOut(BaseModel):
    id: int
    ownership_category: str
    config_type: str
    value: str
    display_name: str
    description: Optional[str] = None
    is_active: bool
    sort_order: int

@router.get("", response_model=List[RegistrationConfigOut])
async def list_registration_config(
    ownership_category: Optional[str] = Query(None, description="Filter by ownership category (e.g., 'PROPRIETOR', 'PARTNERSHIP_FIRM', 'COMPANY')")
):
    """
    Fetches the registration configuration, which can be used to dynamically render UI elements.
    This includes required document types and roles for different ownership categories.
    """
    pool = await get_db_pool()
    
    conditions = []
    values = []

    if ownership_category:
        conditions.append(f"ownership_category = ${len(values) + 1}")
        values.append(ownership_category)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
    sql = f"""
        SELECT id, ownership_category, config_type, value, display_name, description, is_active, sort_order
        FROM {DB_SCHEMA}.registration_config
        {where_clause}
        ORDER BY sort_order
    """
    
    try:
        rows = await pool.fetch(sql, *values)
        if not rows:
            logger.warning(f"No registration config found for ownership_category: {ownership_category}")
        return [dict(row) for row in rows]
    except Exception as e:
        logger.exception("Exception during listing registration config: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch registration configuration")
