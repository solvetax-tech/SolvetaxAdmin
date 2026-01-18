from pydantic import BaseModel, EmailStr, validator,Field
from typing import Optional
from datetime import datetime




class CompanyRegistrationIn(BaseModel):
    customer_id: int

    cin: str = Field(..., max_length=21)
    company_name: Optional[str] = None

    username: str = Field(..., max_length=100)
    password: str

    pan: str = Field(..., max_length=10)

    company_type: str = Field(..., max_length=50)
    business_type: Optional[str] = Field(None, max_length=50)
    business_description: Optional[str] = None

    registered_email: EmailStr
    registered_mobile: str = Field(..., max_length=20)

    registered_office_address: str
    state: str = Field(..., max_length=100)
    city: str = Field(..., max_length=100)

    created_by: Optional[int] = None
    rm_id: Optional[int] = None

    is_filing_needed: Optional[bool] = True


class CompanyRegistrationEditIn(BaseModel):
    cin: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    pan: Optional[str] = None

    company_type: Optional[str] = None
    business_type: Optional[str] = None
    business_description: Optional[str] = None

    company_name: Optional[str] = None

    registered_email: Optional[EmailStr] = None
    registered_mobile: Optional[str] = None
    registered_office_address: Optional[str] = None

    state: Optional[str] = None
    city: Optional[str] = None

    registration_status: Optional[str] = None

    rm_id: Optional[int] = None
    is_filing_needed: Optional[bool] = None
    is_active: Optional[bool] = None


class CompanyRegistrationEditIn(BaseModel):
    cin: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    pan: Optional[str] = None

    company_type: Optional[str] = None
    business_type: Optional[str] = None
    business_description: Optional[str] = None

    company_name: Optional[str] = None

    registered_email: Optional[EmailStr] = None
    registered_mobile: Optional[str] = None
    registered_office_address: Optional[str] = None

    state: Optional[str] = None
    city: Optional[str] = None

    registration_status: Optional[str] = None

    rm_id: Optional[int] = None
    is_filing_needed: Optional[bool] = None
    is_active: Optional[bool] = None

class CompanyRegistrationOut(BaseModel):
    id: int
    customer_id: int

    cin: str
    username: str
    pan: str

    company_type: str
    business_type: Optional[str] = None
    business_description: Optional[str] = None

    company_name: Optional[str] = None

    registered_email: EmailStr
    registered_mobile: str
    registered_office_address: str

    state: str
    city: str

    registration_status: Optional[str] = None

    created_by: Optional[int] = None
    rm_id: Optional[int] = None

    is_filing_needed: Optional[bool] = None
    is_active: Optional[bool] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    message: Optional[str] = None


from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import date, datetime

# -------------------------------------------------------------------
# BASE SCHEMA (SHARED FIELDS)
# -------------------------------------------------------------------

class CompanyPersonBase(BaseModel):
    cin: str = Field(..., max_length=21)
    role: str = Field(..., max_length=50)
    full_name: str = Field(..., max_length=150)
    pan: str = Field(..., max_length=10)
    aadhaar: str = Field(..., max_length=20)

    voter_id: Optional[str] = Field(None, max_length=20)
    passport: Optional[str] = Field(None, max_length=20)
    driving_license: Optional[str] = Field(None, max_length=20)

    email: EmailStr
    mobile: str = Field(..., max_length=20)

    dsc_validity_date: Optional[date] = None
    dir_kyc_due_date: Optional[date] = None
    dir_kyc_done_date: Optional[date] = None

    din_status: Optional[str] = Field("active", max_length=50)

    occupation: str = Field(..., max_length=50)
    area_of_occupation: str = Field(..., max_length=100)
    education_qualification: str = Field(..., max_length=100)

    present_residential_address: str
    address_duration_years: int

    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = None

    is_primary_customer: Optional[bool] = False


# -------------------------------------------------------------------
# CREATE INPUT SCHEMA
# -------------------------------------------------------------------

class CompanyPersonIn(CompanyPersonBase):
    pass


# -------------------------------------------------------------------
# EDIT INPUT SCHEMA (ALL OPTIONAL)
# -------------------------------------------------------------------

class CompanyPersonEditIn(BaseModel):
    role: Optional[str] = Field(None, max_length=50)
    full_name: Optional[str] = Field(None, max_length=150)
    pan: Optional[str] = Field(None, max_length=10)
    aadhaar: Optional[str] = Field(None, max_length=20)

    voter_id: Optional[str] = Field(None, max_length=20)
    passport: Optional[str] = Field(None, max_length=20)
    driving_license: Optional[str] = Field(None, max_length=20)

    email: Optional[EmailStr] = None
    mobile: Optional[str] = Field(None, max_length=20)

    dsc_validity_date: Optional[date] = None
    dir_kyc_due_date: Optional[date] = None
    dir_kyc_done_date: Optional[date] = None

    din_status: Optional[str] = Field(None, max_length=50)

    occupation: Optional[str] = Field(None, max_length=50)
    area_of_occupation: Optional[str] = Field(None, max_length=100)
    education_qualification: Optional[str] = Field(None, max_length=100)

    present_residential_address: Optional[str] = None
    address_duration_years: Optional[int] = None

    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = None

    is_active: Optional[bool] = None
    is_primary_customer: Optional[bool] = None


# -------------------------------------------------------------------
# RESPONSE / OUTPUT SCHEMA
# -------------------------------------------------------------------

class CompanyPersonOut(CompanyPersonBase):
    cin: str = Field(..., max_length=21)
    role: str = Field(..., max_length=50)
    full_name: str = Field(..., max_length=150)
    pan: str = Field(..., max_length=10)
    aadhaar: str = Field(..., max_length=20)

    voter_id: Optional[str] = Field(None, max_length=20)
    passport: Optional[str] = Field(None, max_length=20)
    driving_license: Optional[str] = Field(None, max_length=20)

    email: EmailStr
    mobile: str = Field(..., max_length=20)

    dsc_validity_date: Optional[date] = None
    dir_kyc_due_date: Optional[date] = None
    dir_kyc_done_date: Optional[date] = None

    din_status: Optional[str] = Field("active", max_length=50)

    occupation: str = Field(..., max_length=50)
    area_of_occupation: str = Field(..., max_length=100)
    education_qualification: str = Field(..., max_length=100)

    present_residential_address: str
    address_duration_years: int

    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = None

    is_primary_customer: Optional[bool] = False

    

class CompanyRegistrationIn(BaseModel):
    customer_id: int

    cin: str
    username: str
    password: str
    pan: str

    company_type: str
    business_type: Optional[str] = None
    business_description: Optional[str] = None

    company_name: Optional[str] = None

    registered_email: EmailStr
    registered_mobile: str
    registered_office_address: str

    state: str
    city: str

    created_by: Optional[int] = None
    rm_id: Optional[int] = None

    is_filing_needed: Optional[bool] = True
    is_active: Optional[bool] = True

    # ------------------------
    # Optional Validators
    # ------------------------
    @validator("cin")
    def validate_cin(cls, v):
        if len(v) != 21:
            raise ValueError("CIN must be 21 characters")
        return v.upper()

    @validator("pan")
    def validate_pan(cls, v):
        if len(v) != 10:
            raise ValueError("PAN must be 10 characters")
        return v.upper()

    @validator("registered_mobile")
    def validate_mobile(cls, v):
        if not v.isdigit() or len(v) < 10:
            raise ValueError("Invalid mobile number")
        return v

class CompanyRegistrationDocumentIn(BaseModel):
    cin: str = Field(..., max_length=21)
    person_id: Optional[int] = None
    document_type: str = Field(..., max_length=50)
    document_url: str


# -------------------------------------------------------------------
# EDIT INPUT SCHEMA (PARTIAL UPDATE)
# -------------------------------------------------------------------

class CompanyRegistrationDocumentEditIn(BaseModel):
    document_type: Optional[str] = Field(None, max_length=50)
    document_url: Optional[str] = None

    verified: Optional[bool] = None
    verified_by: Optional[int] = None
    verified_at: Optional[datetime] = None


# -------------------------------------------------------------------
# RESPONSE / OUTPUT SCHEMA
# -------------------------------------------------------------------

class CompanyRegistrationDocumentOut(BaseModel):
    document_id: int

    cin: str
    person_id: Optional[int] = None

    document_type: str
    document_url: str

    verified: bool
    verified_by: Optional[int] = None
    verified_at: Optional[datetime] = None

    uploaded_at: Optional[datetime] = None

    message: Optional[str] = None
