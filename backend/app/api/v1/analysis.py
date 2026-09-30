import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.rate_limit import limiter, user_or_ip_key
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


@router.post("/quick-check", response_model=QuickCheckResponse)
@limiter.limit(settings.DEFAULT_RATE_LIMIT, key_func=user_or_ip_key)
async def quick_check(
    request: Request,
    body: QuickCheckRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """선택한 약품 목록의 병용금기를 즉시 확인 (DB 직접 조회, AI 불필요).

    사용자 프로필에 알레르기·출생연도가 등록돼 있으면 알레르기 충돌·연령대
    규칙도 함께 확인한다(둘 다 선택 입력 — 없으면 해당 검사만 스킵)."""
    return await AnalysisService(db).quick_check(body.drug_ids, user_id=user_id)


@router.post("/guide", response_model=AnalysisGuideResponse)
@limiter.limit(settings.ANALYSIS_RATE_LIMIT, key_func=user_or_ip_key)
async def generate_analysis_guide(
    request: Request,
    body: AnalysisGuideRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """quick-check와 동일한 판정(규칙 기반, DB 직접 조회)에 로컬 LLM이 생성한
    설명·대응 가이드를 덧붙인다. 위험도 판정 자체는 AI가 바꾸지 않는다."""
    quick_check_result = await AnalysisService(db).quick_check(body.drug_ids, user_id=user_id)
    return await AiGuideService(db).generate_guide(
        user_id, body.drug_ids, quick_check_result.findings, quick_check_result.risk_level
    )
