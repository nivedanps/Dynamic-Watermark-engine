from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, ConfigDict

class Role(str, Enum):
    ADMIN = "ADMIN"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[Role] = None

class User(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    username: str
    user_id: str
    school_name: str
    role: Role
    disabled: Optional[bool] = False

class UserInDB(User):
    hashed_password: str

class WatermarkRequest(BaseModel):
    pdf_filename: str

class DocumentInfo(BaseModel):
    id: str
    name: str
    type: str  # "pdf" or "scorm"
    filename: Optional[str] = None
    size: Optional[int] = None
    title: Optional[str] = None
    organization: Optional[str] = None
    entry_point: Optional[str] = None
    pdf_filename: Optional[str] = None
    has_pdf: Optional[bool] = False
    modified_at: Optional[float] = None

class DocumentListResponse(BaseModel):
    documents: List[DocumentInfo]
