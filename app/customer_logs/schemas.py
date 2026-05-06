from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class BaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


class CustomerEventLogIn(BaseSchema):
    session_id: UUID
    anonymous_customer_id: str = Field(..., min_length=4, max_length=64)
    customer_id: Optional[int] = Field(None, gt=0)
    journey_id: Optional[UUID] = None
    client_event_id: Optional[UUID] = None

    event_name: str = Field(..., min_length=2, max_length=80)
    event_category: Optional[str] = Field(None, max_length=80)
    event_action: Optional[str] = Field(None, max_length=80)
    event_status: Optional[str] = Field(None, max_length=40)
    event_label: Optional[str] = Field(None, max_length=255)
    severity: Optional[str] = Field(None, max_length=20)

    page_path: Optional[str] = Field(None, max_length=512)
    page_url: Optional[str] = None
    referrer_path: Optional[str] = Field(None, max_length=512)
    route_name: Optional[str] = Field(None, max_length=120)

    cta_name: Optional[str] = Field(None, max_length=120)
    form_name: Optional[str] = Field(None, max_length=120)
    funnel_name: Optional[str] = Field(None, max_length=80)
    funnel_step_number: Optional[int] = Field(None, ge=0, le=999)
    funnel_step_name: Optional[str] = Field(None, max_length=120)
    service_code: Optional[str] = Field(None, max_length=80)
    phone_number: Optional[str] = Field(None, max_length=15)

    event_timestamp: Optional[datetime] = None
    dwell_time_seconds: Optional[int] = Field(None, ge=0)
    active_time_seconds: Optional[int] = Field(None, ge=0)

    api_name: Optional[str] = Field(None, max_length=120)
    api_status_code: Optional[int] = None
    api_response_time_ms: Optional[int] = Field(None, ge=0)

    error_code: Optional[str] = Field(None, max_length=80)
    error_message: Optional[str] = None

    ingestion_source: Optional[str] = Field(None, max_length=40)
    environment: Optional[str] = Field(None, max_length=20)
    release_tag: Optional[str] = Field(None, max_length=60)
    platform: Optional[str] = Field(None, max_length=20)
    device_type: Optional[str] = Field(None, max_length=20)
    os_name: Optional[str] = Field(None, max_length=40)
    os_version: Optional[str] = Field(None, max_length=40)
    browser_name: Optional[str] = Field(None, max_length=40)
    browser_version: Optional[str] = Field(None, max_length=40)
    app_version: Optional[str] = Field(None, max_length=40)
    user_agent: Optional[str] = None

    @field_validator("event_status", mode="before")
    @classmethod
    def normalize_status(cls, value):
        return value.lower() if isinstance(value, str) and value.strip() else None

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value):
        return value.lower() if isinstance(value, str) and value.strip() else None

    @field_validator("event_timestamp", mode="before")
    @classmethod
    def default_event_time(cls, value):
        if value is None:
            return datetime.now(timezone.utc)
        return value
