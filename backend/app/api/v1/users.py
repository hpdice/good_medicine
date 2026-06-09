import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user_id
from app.schemas.user import UserUpdate, UserWithHealthResponse
from app.services.user_service import UserService

router = APIRouter()


@router.get("/me", response_model=UserWithHealthResponse)
async def get_me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await UserService(db).get_user(user_id)


@router.patch("/me", response_model=UserWithHealthResponse)
async def update_me(
    body: UserUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await UserService(db).update_user(user_id, body)


@router.delete("/me", status_code=204)
async def delete_me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """개인정보보호법: 탈퇴 시 개인정보 즉시 삭제"""
    await UserService(db).delete_user(user_id)
