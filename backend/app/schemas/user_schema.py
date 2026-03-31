import uuid
from typing import Annotated

from pydantic import BaseModel, EmailStr, StringConstraints, Field
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


class SetupPasswordRequest(BaseModel):
    token: str
    password: str

class UserUpdate(BaseModel):
    email: EmailStr
    username: str
    is_admin: bool
    is_active: bool

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: Annotated[str, StringConstraints(min_length=6)]
    confirm_password: str

    model_config = {"from_attributes": True}

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class MessageResponse(BaseModel):
    message: str