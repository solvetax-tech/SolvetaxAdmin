from typing import Dict, List, Optional

from pydantic import BaseModel


class ServiceDonePaymentPendingItem(BaseModel):
    entity_type: str
    entity_id: int
    customer_id: Optional[int] = None
    service_status: str
    display_name: Optional[str] = None
    business_name: Optional[str] = None
    mobile: Optional[str] = None
    rm_id: Optional[int] = None
    op_id: Optional[int] = None
    rm_username: Optional[str] = None
    op_username: Optional[str] = None
    entity_created_at: Optional[str] = None
    service_code: Optional[str] = None
    service_name: Optional[str] = None
    gstin: Optional[str] = None
    pan_number: Optional[str] = None
    financial_year: Optional[List[str]] = None
    pending_amount: Optional[float] = None


class ServiceDonePaymentPendingSummary(BaseModel):
    total: int = 0
    gst_registration: int = 0
    gst_filing: int = 0
    income_tax: int = 0
    customer_service: int = 0


class ServiceDonePaymentPendingListResponse(BaseModel):
    data: List[ServiceDonePaymentPendingItem]
    total: int
    limit: int
    offset: int
    summary: ServiceDonePaymentPendingSummary
    request_id: str


class GstFilingMatrixFormCell(BaseModel):
    status: Optional[str] = None
    due_date: Optional[str] = None
    tone: str = "none"


class GstFilingMatrixMonthCell(BaseModel):
    tone: str = "none"
    status: Optional[str] = None
    due_date: Optional[str] = None
    status_label: Optional[str] = None
    filing_id: Optional[int] = None
    return_detail_id: Optional[int] = None
    forms: Optional[Dict[str, GstFilingMatrixFormCell]] = None


class GstFilingMatrixRow(BaseModel):
    customer_id: int
    display_name: Optional[str] = None
    business_name: Optional[str] = None
    mobile: Optional[str] = None
    gstin: Optional[str] = None
    rm_username: Optional[str] = None
    op_username: Optional[str] = None
    months: Dict[str, GstFilingMatrixMonthCell]


class GstFilingMatrixListResponse(BaseModel):
    months: List[str]
    data: List[GstFilingMatrixRow]
    total: int
    limit: int
    offset: int
    request_id: str
