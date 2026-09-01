import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user_id
from app.schemas.drug import (
    DrugNameMatchRequest,
    DrugNameMatchResult,
    DrugResponse,
    DrugSearchResult,
)
from app.services.drug_service import DrugService

router = APIRouter()


@router.post("/match-names", response_model=list[DrugNameMatchResult])
async def match_drug_names(
    body: DrugNameMatchRequest,
    db: AsyncSession = Depends(get_db),
    _: uuid.UUID = Depends(get_current_user_id),
):
    """OCR이 추출한 약품명 리스트 → DB 매칭 (최대 후보 5개 반환)."""
    return await DrugService(db).match_names(body.names)


@router.get("", response_model=list[DrugSearchResult])
async def search_drugs(
    q: str = Query(min_length=1, max_length=100, description="약품명 검색어"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: uuid.UUID = Depends(get_current_user_id),
):
    return await DrugService(db).search(q, page=page, limit=limit)


@router.get("/{drug_id}", response_model=DrugResponse)
async def get_drug(
    drug_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: uuid.UUID = Depends(get_current_user_id),
):
    return await DrugService(db).get_by_id(drug_id)
