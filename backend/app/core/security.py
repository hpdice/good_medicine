import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt

from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    encoded = plain.encode("utf-8")
    if len(encoded) > 72:
        # bcrypt는 72바이트 초과 입력에 ValueError를 던진다 — 로그인 스키마는
        # 길이 제한이 없으므로 여기서도 방어해 500 대신 인증 실패로 처리한다.
        return False
    return bcrypt.checkpw(encoded, hashed.encode("utf-8"))


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "type": "access", "jti": str(uuid.uuid4())}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """jti(랜덤 UUID)가 없으면 같은 사용자가 같은 초(second)에 로그인/갱신을
    두 번 하는 경우 exp까지 완전히 동일한 토큰이 발급되어(HS256은 결정적
    서명이라 입력이 같으면 출력도 같음) token_hash UNIQUE 제약을 위반해
    500 에러가 난다 — jti로 토큰마다 고유성을 보장한다.
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "exp": expire, "type": "refresh", "jti": str(uuid.uuid4())}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """토큰 검증 및 페이로드 반환. 유효하지 않으면 JWTError 발생."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def get_token_expiry(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)
