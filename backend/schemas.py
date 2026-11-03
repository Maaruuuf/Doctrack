from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["staff", "manager", "admin"]
Category = Literal["Licence", "Certificate", "Contract", "Official Document", "Policy", "Other"]
Confidentiality = Literal["Public", "Confidential", "Restricted"]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    full_name: str
    role: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    full_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    role: Role = "staff"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    full_name: str
    role: str
    is_active: bool


class DocumentBase(BaseModel):
    doc_code: str = Field(min_length=2, max_length=50)
    title: str = Field(min_length=2, max_length=200)
    category: Category = "Other"
    confidentiality: Confidentiality = "Public"
    issuing_authority: Optional[str] = Field(None, max_length=200)
    owner: Optional[str] = Field(None, max_length=200)
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    renewal_lead_days: int = Field(30, ge=0, le=365)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def check_dates(self):
        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            raise ValueError("expiry_date cannot be before issue_date")
        return self


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(BaseModel):
    doc_code: Optional[str] = Field(None, min_length=2, max_length=50)
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    category: Optional[Category] = None
    confidentiality: Optional[Confidentiality] = None
    issuing_authority: Optional[str] = Field(None, max_length=200)
    owner: Optional[str] = Field(None, max_length=200)
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    renewal_lead_days: Optional[int] = Field(None, ge=0, le=365)
    notes: Optional[str] = None


class DocumentOut(DocumentBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    days_left: Optional[int]
    file_name: Optional[str]
    is_archived: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class RenewRequest(BaseModel):
    new_expiry_date: date
    note: Optional[str] = Field(None, max_length=300)


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    action: str
    changed_by: str
    changed_at: datetime
    details: Optional[str]


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    document_id: int
    doc_code: str
    doc_title: str
    level: str
    message: str
    expiry_on: date
    created_at: datetime
    is_acknowledged: bool
    acknowledged_by: Optional[str]
