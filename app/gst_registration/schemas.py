from pydantic import BaseModel, EmailStr, validator
from typing import Optional
from datetime import datetime, date
from app.utils import validate_pan, validate_aadhaar , validate_mobile, validate_gstin


class GSTRegistrationIn(BaseModel):
    customer_id: int
    username: str
    password: str
    pan: str
    registration_type: Optional[str] = None   # NORMAL / COMPOSITION
    ownership_category: Optional[str] = None  # PROPRIETARY / PARTNERSHIP_FIRM / COMPANY
    business_type: Optional[str] = None
    state: Optional[str] = None
    turnover_details: Optional[str] = None  # LESS_THAN_2CR / LESS_THAN_5CR / MORE_THAN_5CR
    created_by: Optional[int] = None
    gstin: Optional[str] = None
    is_filing_needed: Optional[bool] = True
    mobile: Optional[str] = None
    is_active: Optional[bool] = True

    @validator('gstin')
    def gstin_validator(cls, v):
        return validate_gstin(v)

    @validator('mobile')
    def mobile_validator(cls, v):
        return validate_mobile(v)

    @validator('pan')
    def pan_validator(cls, v):
        return validate_pan(v)   


class GSTRegistrationEditIn(BaseModel):
    gstin: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    pan: Optional[str] = None
    registration_type: Optional[str] = None
    ownership_category: Optional[str] = None
    business_type: Optional[str] = None
    state: Optional[str] = None
    turnover_details: Optional[str] = None
    registration_status: Optional[str] = None
    suspension_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None
    approved_at: Optional[datetime] = None
    is_rcm_applicable: Optional[bool] = None
    is_filing_needed: Optional[bool] = True
    mobile: Optional[str] = None
    is_active: Optional[bool] = None

    @validator('gstin')
    def gstin_validator(cls, v):
        return validate_gstin(v)

    @validator('mobile')
    def mobile_validator(cls, v):
        return validate_mobile(v)
     
    @validator('pan')
    def pan_validator(cls, v):
        return validate_pan(v)


class GSTRegistrationOut(BaseModel):
    id: int
    customer_id: int
    gstin: Optional[str]
    username: str
    is_active: bool
    pan: str
    registration_type: Optional[str]
    ownership_category: Optional[str]
    business_type: Optional[str]
    state: Optional[str]
    turnover_details: Optional[str]
    registration_status: Optional[str]
    suspension_reason: Optional[str]
    cancellation_reason: Optional[str]
    approved_at: Optional[datetime]
    is_rcm_applicable: bool
    created_by: Optional[int]
    is_filing_needed: bool
    created_at: datetime
    updated_at: datetime
    message: Optional[str] = None

# Pydantic Models for RegistrationPerson
class RegistrationPersonIn(BaseModel):
    customer_id: Optional[int] = None
    gstin: str
    full_name: str
    role: str
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile: Optional[str] = None
    is_primary_customer: Optional[bool] = False

    @validator('gstin')
    def gstin_validator(cls, v):
        if v is not None:
            return validate_gstin(v)
        
    
    @validator('mobile')
    def mobile_validator(cls, v):
        if v is not None:
            return validate_mobile(v)
        return v

    @validator('pan')
    def pan_validator(cls, v):
        from app.utils import validate_pan
        if v is not None:
            return validate_pan(v)
        return v

    @validator('aadhaar')
    def aadhaar_validator(cls, v):
        # Basic Aadhaar validation: 12 digit numeric string
        if v is not None:
            if not (v.isdigit() and len(v) == 12):
                raise ValueError('Aadhaar must be exactly 12 digits')
        return v

class RegistrationPersonEditIn(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile: Optional[str] = None
    is_primary_customer: Optional[bool] = None

    @validator('mobile')
    def mobile_validator(cls, v):
        if v is not None:
            return validate_mobile(v)
        return v

    @validator('pan')
    def pan_validator(cls, v):
        from app.gst_registration.validators import validate_pan
        if v is not None:
            return validate_pan(v)
        return v

    @validator('aadhaar')
    def aadhaar_validator(cls, v):
        from app.gst_registration.validators import validate_aadhaar
        if v is not None:
            return validate_aadhaar(v)
        return v

class RegistrationPersonOut(BaseModel):
    person_id: int
    customer_id: Optional[int] = None
    gstin: str
    full_name: str
    role: str
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile: Optional[str] = None
    is_primary_customer: Optional[bool] = False
    message: Optional[str] = None

# Pydantic Models for RegistrationDocument
class RegistrationDocumentIn(BaseModel):
    gstin: str
    person_id: Optional[int] = None
    document_type: str
    document_url: str
    ownership_category: Optional[str] = None
    mobile: Optional[str] = None

    @validator('gstin')
    def gstin_validator(cls, v):
        return validate_gstin(v)
    
    @validator('mobile')
    def mobile_validator(cls, v):
        if v is not None:
            return validate_mobile(v)
        return v

class RegistrationDocumentEditIn(BaseModel):
    document_type: Optional[str] = None
    document_url: Optional[str] = None
    ownership_category: Optional[str] = None
    verified: Optional[bool] = None
    verified_by: Optional[int] = None
    verified_at: Optional[datetime] = None
    mobile: Optional[str] = None

    @validator('mobile')
    def mobile_validator(cls, v):
        if v is not None:
            return validate_mobile(v)
        return v

class RegistrationDocumentOut(BaseModel):
    document_id: int
    gstin: str
    person_id: Optional[int] = None
    document_type: str
    document_url: str
    ownership_category: Optional[str] = None
    verified: Optional[bool] = None
    verified_by: Optional[int] = None
    verified_at: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None
    mobile: Optional[str] = None

    @validator('gstin')
    def gstin_validator(cls, v):
        return validate_gstin(v)

    @validator('mobile')
    def mobile_validator(cls, v):
        if v is not None:
            return validate_mobile(v)
        return v
