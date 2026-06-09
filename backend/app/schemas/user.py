import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    privacy_consent: bool = Field(description="개인정보 수집 동의 (필수)")
    health_data_consent: bool = Field(description="건강정보 수집 동의 (필수)")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone_number: str | None = Field(default=None, max_length=20)
    health_conditions: list[str] | None = None
    allergy_info: list[str] | None = None
    fcm_token: str | None = Field(default=None, max_length=512)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    phone_number: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserWithHealthResponse(UserResponse):
    health_conditions: list[str] | None = None
    allergy_info: list[str] | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="초 단위 만료 시간")


class RefreshRequest(BaseModel):
    refresh_token: str
