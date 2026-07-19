"""Pydantic schemas for `employee_tasks` (personal day calendar)."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.common.status_constants import TaskStatusLiteral


class TaskBaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


def _clean_slots(v):
    """Sort + de-duplicate the picked 15-min slot start-times (by instant)."""
    if v is None:
        return v
    uniq = sorted(set(v))
    if not uniq:
        raise ValueError("time_slots must contain at least one slot")
    return uniq


class TaskCreateIn(TaskBaseSchema):
    """Create a task. emp_id (owner) comes from the JWT, never the client.

    time_slots is the set of one or more 15-min slot start-times this task blocks.
    """

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    time_slots: List[datetime] = Field(..., min_length=1)
    status: Optional[TaskStatusLiteral] = None  # omit -> DB default PENDING
    followup_at: Optional[datetime] = None
    followup_note: Optional[str] = None

    @field_validator("time_slots")
    @classmethod
    def clean_slots(cls, v):
        return _clean_slots(v)

    @field_validator("status", mode="before")
    @classmethod
    def upper_status(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class TaskPatchIn(TaskBaseSchema):
    """Edit / reschedule. Any subset; at least one field required."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    time_slots: Optional[List[datetime]] = Field(None, min_length=1)
    status: Optional[TaskStatusLiteral] = None
    followup_at: Optional[datetime] = None
    followup_note: Optional[str] = None

    @field_validator("time_slots")
    @classmethod
    def clean_slots(cls, v):
        return _clean_slots(v)

    @field_validator("status", mode="before")
    @classmethod
    def upper_status(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class TaskOut(TaskBaseSchema):
    id: int
    emp_id: int
    title: str
    description: Optional[str] = None
    scheduled_at: datetime
    time_slots: List[datetime]
    status: str
    followup_at: Optional[datetime] = None
    followup_note: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class TaskListOut(TaskBaseSchema):
    data: List[TaskOut]
    count: int
    date: str


class TaskPageOut(TaskBaseSchema):
    """A page of the caller's tasks across all days (the 'All' view)."""

    data: List[TaskOut]
    count: int    # rows in this page
    total: int    # total rows matching the filter
    limit: int
    offset: int


class SlotOut(TaskBaseSchema):
    time: str            # "HH:MM" in IST, for display
    iso: str             # UTC ISO to send back inside time_slots
    available: bool
    conflict_title: Optional[str] = None  # what occupies it, when taken


class AvailableSlotsOut(TaskBaseSchema):
    date: str
    slot_minutes: int
    slots: List[SlotOut]
