"""Pydantic schemas for `issue_reports` (in-app bug/issue reporting)."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.common.status_constants import IssuePriorityLiteral, IssueStatusLiteral


class IssueReportBaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


class IssueReportCreateIn(IssueReportBaseSchema):
    """Raise an issue. reporter_emp_id is taken from the JWT, never sent here."""

    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=1)
    # Omitted -> DB default MEDIUM.
    priority: Optional[IssuePriorityLiteral] = None
    # Blob URLs already uploaded via POST /photo/upload. Cap keeps the row small.
    photo_urls: List[str] = Field(default_factory=list, max_length=10)

    @field_validator("priority", mode="before")
    @classmethod
    def upper_priority(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("photo_urls", mode="before")
    @classmethod
    def clean_photo_urls(cls, v):
        if isinstance(v, list):
            return [u.strip() for u in v if isinstance(u, str) and u.strip()]
        return v


class IssueReportPatchIn(IssueReportBaseSchema):
    """Update status / priority / resolution note. At least one field required."""

    status: Optional[IssueStatusLiteral] = None
    priority: Optional[IssuePriorityLiteral] = None
    resolution_note: Optional[str] = None

    @field_validator("status", "priority", mode="before")
    @classmethod
    def upper_vals(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v


class IssueReportOut(IssueReportBaseSchema):
    id: int
    reporter_emp_id: int
    title: str
    description: str
    priority: str
    status: str
    photo_urls: List[str] = Field(default_factory=list)
    resolved_by_emp_id: Optional[int] = None
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class IssueReportListItemOut(IssueReportOut):
    """List row + joined labels for display."""

    reporter_name: Optional[str] = None
    reporter_username: Optional[str] = None
    resolved_by_name: Optional[str] = None


class IssueReportPhotoUploadOut(IssueReportBaseSchema):
    blob_url: str
    filename: Optional[str] = None
