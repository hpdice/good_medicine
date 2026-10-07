import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User

security = HTTPBearer()


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """JWT Bearer 토큰에서 사용자 ID를 추출하고, 그 계정이 아직 활성인지 확인한다.

    토큰 서명·만료만 보면 탈퇴한 사용자가 탈퇴 전에 받은 Access Token(최대 30분)으로 계속
    요청할 수 있었다(2026-09-30 재현). PK 조회 한 번으로 막는다.
    """
    try:
        jwt_claims = decode_token(credentials.credentials)
        if jwt_claims.get("type") != "access":
            raise UnauthorizedError("Invalid token type")
        user_id = jwt_claims.get("sub")
        if not user_id:
            raise UnauthorizedError()
        uid = uuid.UUID(user_id)
    except (JWTError, ValueError) as e:
        raise UnauthorizedError() from e

    is_active = await db.scalar(select(User.is_active).where(User.id == uid))
    if not is_active:
        raise UnauthorizedError("비활성화된 계정입니다.")
    return uid
