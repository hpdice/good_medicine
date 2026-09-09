from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.schemas.user import RefreshRequest, TokenResponse, UserLogin, UserRegister, UserResponse
from app.services.auth_service import AuthService

router = APIRouter()


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(body: UserRegister, request: Request, db: AsyncSession = Depends(get_db)):
    return await AuthService(db).register(
        body, ip=_get_client_ip(request), user_agent=request.headers.get("user-agent")
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.LOGIN_RATE_LIMIT)
async def login(body: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    """Access Token + Refresh Token 반환"""
    return await AuthService(db).login(
        body, ip=_get_client_ip(request), user_agent=request.headers.get("user-agent")
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    return await AuthService(db).refresh(body.refresh_token)


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    await AuthService(db).logout(body.refresh_token)
