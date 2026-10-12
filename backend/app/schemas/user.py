import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    privacy_consent: bool = Field(description="개인정보 수집 동의 (필수)")
    health_data_consent: bool = Field(description="건강정보 수집 동의 (필수)")

    @field_validator("password")
    @classmethod
    def validate_password_byte_length(cls, v: str) -> str:
        # bcrypt는 UTF-8 72바이트 초과 시 ValueError를 던진다 (한글은 음절당 3바이트).
        if len(v.encode("utf-8")) > 72:
            raise ValueError("비밀번호는 72바이트(한글 약 24자)를 초과할 수 없습니다.")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone_number: str | None = Field(default=None, max_length=20)
    health_conditions: list[str] | None = None
    allergy_info: list[str] | None = None
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    is_pregnant: bool | None = None  # 임신 중이면 DUR 임부금기 판정 (None=변경 없음)
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
    birth_year: int | None = None
    is_pregnant: bool | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="초 단위 만료 시간")


class RefreshRequest(BaseModel):
    refresh_token: str
