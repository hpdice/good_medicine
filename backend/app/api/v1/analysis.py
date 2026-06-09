import uuid

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.dependencies import get_current_user_id
from app.schemas.analysis import QuickCheckRequest, QuickCheckResponse
from app.services.analysis_service import AnalysisService

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/quick-check", response_model=QuickCheckResponse)
@limiter.limit(settings.DEFAULT_RATE_LIMIT)
async def quick_check(
    request: Request,
    body: QuickCheckRequest,
    _: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """선택한 약품 목록의 병용금기를 즉시 확인 (DB 직접 조회, AI 불필요)."""
    return await AnalysisService(db).quick_check(body.drug_ids)
