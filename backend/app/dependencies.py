import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db

security = HTTPBearer()


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> uuid.UUID:
    """JWT Bearer 토큰에서 사용자 ID를 추출한다."""
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise UnauthorizedError("Invalid token type")
        user_id = payload.get("sub")
        if not user_id:
            raise UnauthorizedError()
        return uuid.UUID(user_id)
    except (JWTError, ValueError) as e:
        raise UnauthorizedError() from e


# 공통 의존성 타입 별칭
CurrentUserId = Depends(get_current_user_id)
DB = Depends(get_db)
