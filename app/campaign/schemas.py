"""
Marketing capture at submit time: POST /api/v1/event-logs (optional standalone).
Same optional fields may be sent on Customer / Income Tax create bodies.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CampaignSubmitIn(BaseModel):
    model_config = {"extra": "ignore", "str_strip_whitespace": True}

    mobile: str = Field(..., pattern=r"^\d{10}$")
    entity_type: Optional[str] = Field(None, max_length=40, description="CUSTOMER, INCOME_TAX, etc.")

    utm_source: Optional[str] = Field(None, max_length=120)
    utm_medium: Optional[str] = Field(None, max_length=120)
    utm_campaign: Optional[str] = Field(None, max_length=200)
    utm_content: Optional[str] = Field(None, max_length=200)

    capture_page_path: Optional[str] = Field(None, max_length=1024)
    capture_page_url: Optional[str] = None
    capture_page_query: Optional[str] = None
    capture_referrer_url: Optional[str] = None

    platform: Optional[str] = Field(None, max_length=20)
    device_type: Optional[str] = Field(None, max_length=20)
    device_model: Optional[str] = Field(None, max_length=200)
    os_name: Optional[str] = Field(None, max_length=64)
    os_version: Optional[str] = Field(None, max_length=32)
    browser_name: Optional[str] = Field(None, max_length=64)
    browser_version: Optional[str] = Field(None, max_length=32)
    app_version: Optional[str] = Field(None, max_length=64)
    environment: Optional[str] = Field(None, max_length=32)
    release_tag: Optional[str] = Field(None, max_length=64)
    user_agent: Optional[str] = None
    viewport_width: Optional[int] = None
    viewport_height: Optional[int] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    capture_language: Optional[str] = Field(None, max_length=32, description="Stored as language column.")
    timezone_offset_min: Optional[int] = None
    lead_source: Optional[str] = Field(None, max_length=120)
    ingestion_source: Optional[str] = Field(None, max_length=40)

    @field_validator("utm_source", "utm_medium", "utm_campaign", "utm_content", mode="before")
    @classmethod
    def upper_trim_utm(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s.upper()[:200] if s else None
        return v

    @field_validator("entity_type", mode="before")
    @classmethod
    def upper_trim_entity(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s.upper()[:40] if s else None
        return v

    @field_validator("mobile", mode="before")
    @classmethod
    def norm_mobile(cls, v):
        return str(v).strip() if v is not None else v

    @field_validator("lead_source", mode="before")
    @classmethod
    def trim_lead_source(cls, v):
        if isinstance(v, str):
            s = v.strip()
            return s.upper()[:120] if s else None
        return v


def campaign_capture_optional_field_names() -> tuple[str, ...]:
    """Field names replicated on CustomerIn / IncomeTaxIn for OpenAPI."""
    return tuple(
        k
        for k in CampaignSubmitIn.model_fields
        if k not in ("mobile", "entity_type")
    )
