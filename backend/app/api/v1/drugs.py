import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.dependencies import get_current_user_id
from app.schemas.drug import (
    DrugNameMatchRequest,
    DrugNameMatchResult,
    DrugResponse,
    DrugSearchResult,
    OcrMatchResponse,
)
from app.services.drug_service import DrugService
from app.services.ocr_service import (
    OcrError,
    UnreadableImageError,
    extract_candidates,
    run_ocr,
)

_NON_IMAGE_TYPES = ("text/", "application/pdf", "application/json", "video/", "audio/")

router = APIRouter()


@router.post("/match-names", response_model=list[DrugNameMatchResult])
async def match_drug_names(
    body: DrugNameMatchRequest,
    db: AsyncSession = Depends(get_db),
    _: uuid.UUID = Depends(get_current_user_id),
):
    """OCR이 추출한 약품명 리스트 → DB 매칭 (최대 후보 5개 반환)."""
    return await DrugService(db).match_names(body.names)


@router.post("/ocr", response_model=OcrMatchResponse)
@limiter.limit(settings.OCR_RATE_LIMIT)
async def ocr_match_drugs(
    request: Request,
    image: UploadFile = File(..., description="처방전·약봉투 사진 (jpg/png, 8MB 이하)"),
    db: AsyncSession = Depends(get_db),
    _: uuid.UUID = Depends(get_current_user_id),
):
    """처방전·약봉투 사진 → 서버 OCR → 약품명 후보 추출 → DB 매칭.

    이미지는 메모리에서만 처리하고 응답 직후 폐기한다 (애플리케이션이 디스크·DB에
    저장하지 않음). 원본 사진의 영구 사본은 사용자 기기에만 남는다.
    """
    ctype = (image.content_type or "").lower()
    if ctype.startswith(_NON_IMAGE_TYPES):
        raise HTTPException(status_code=415, detail="이미지 파일만 업로드할 수 있습니다.")

    data = await image.read()
    try:
        if not data:
            raise HTTPException(status_code=400, detail="빈 파일입니다.")
        if len(data) > settings.OCR_MAX_IMAGE_BYTES:
            limit_mb = settings.OCR_MAX_IMAGE_BYTES // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"이미지는 {limit_mb}MB 이하만 가능합니다.")
        try:
            text = await run_in_threadpool(run_ocr, data)
        except UnreadableImageError as e:
            raise HTTPException(status_code=415, detail=str(e)) from e
        except OcrError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        # 요청 처리가 끝나면 이미지 바이트가 남지 않도록 명시적으로 참조 해제 + 스풀 파일 닫기
        del data
        await image.close()

    candidates = extract_candidates(text)
    matches = await DrugService(db).match_names(candidates) if candidates else []
    return {"raw_text": text, "candidates": candidates, "matches": matches}


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
