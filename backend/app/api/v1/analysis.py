import uuid

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.dependencies import get_current_user_id
from app.schemas.analysis import (
    AnalysisGuideRequest,
    AnalysisGuideResponse,
    QuickCheckRequest,
    QuickCheckResponse,
)
from app.services.ai_guide_service import AiGuideService
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


@router.post("/guide", response_model=AnalysisGuideResponse)
@limiter.limit(settings.ANALYSIS_RATE_LIMIT)
async def generate_analysis_guide(
    request: Request,
    body: AnalysisGuideRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """quick-check와 동일한 판정(규칙 기반, DB 직접 조회)에 로컬 LLM이 생성한
    설명·대응 가이드를 덧붙인다. 위험도 판정 자체는 AI가 바꾸지 않는다."""
    quick_check_result = await AnalysisService(db).quick_check(body.drug_ids)
    return await AiGuideService(db).generate_guide(
        user_id, body.drug_ids, quick_check_result.findings, quick_check_result.risk_level
    )
