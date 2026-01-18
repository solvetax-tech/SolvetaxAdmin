from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.utils import get_db_pool, DB_SCHEMA
import logging


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/gst-registration",
    tags=["GST Registration Config"]
)


class GSTRegistrationConfigOut(BaseModel):
    id: int
    config_type: str
    value: str
    display_name: str
    description: Optional[str] = None
    is_active: bool
    sort_order: int

@router.get("/config", response_model=List[GSTRegistrationConfigOut])
async def list_gst_registration_config(
    config_type: Optional[str] = Query(None, description="Filter by config type (e.g., 'registration_type', 'ownership_category', 'turnover_details')")
):
    """
    Fetches the GST registration configuration, which can be used to dynamically render UI elements for dropdowns.
    """
    pool = await get_db_pool()
    
    conditions = []
    values = []

    if config_type:
        conditions.append(f"config_type = ${len(values) + 1}")
        values.append(config_type)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
    sql = f"""
        SELECT id, config_type, value, display_name, description, is_active, sort_order
        FROM {DB_SCHEMA}.gst_registration_config
        {where_clause}
        ORDER BY sort_order
    """
    
    try:
        rows = await pool.fetch(sql, *values)
        if not rows:
            logger.warning(f"No GST registration config found for config_type: {config_type}")
        return [dict(row) for row in rows]
    except Exception as e:
        logger.exception("Exception during listing GST registration config: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch GST registration configuration")