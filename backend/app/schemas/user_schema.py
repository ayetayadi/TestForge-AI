import uuid
from pydantic import BaseModel, EmailStr
from datetime import datetime

class UserCreate(BaseModel):
    email: EmailStr
    username: str
    is_admin: bool = False

class UserRead(BaseModel):
    id: str
    email: EmailStr
    username: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    jira_connected: bool = False

    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class SetupPasswordRequest(BaseModel):
    token: str
    password: str

class UserUpdate(BaseModel):
    email: EmailStr
    username: str
    is_admin: bool