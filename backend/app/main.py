import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.config import settings
from app.core.logging import logger, setup_logging
from app.core.rate_limit import limiter
from app.db.session import engine, get_db
from app.services import fcm_service
from app.services.ollama_client import OllamaClient


async def _ollama_keepalive_loop() -> None:
    """AI 가이드용 로컬 LLM이 GPU에서 내려가지 않게 주기적으로 핑을 보낸다.

    콜드스타트(모델을 GPU에 새로 올림, 87~153초)가 실제 사용자 요청에서
    발생하는 걸 최소화하기 위함 — 위험도 판정에는 영향 없음(그쪽은 로컬 LLM과
    무관하게 규칙 기반으로 동작).
    """
    client = OllamaClient()
    while True:
        try:
            await client.keep_warm()
        except Exception:
            logger.warning("Ollama 워밍업 루프 중 예외 (다음 주기에 재시도)", exc_info=True)
        await asyncio.sleep(settings.OLLAMA_KEEPALIVE_INTERVAL_SECONDS)


@asynccontextmanager # with 구문에서 FastAPI lifespan 이벤트로 사용

async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(f"Starting drugtest backend (debug={settings.DEBUG})")
    fcm_state = "enabled" if fcm_service.is_configured() else "disabled"
    logger.info(f"FCM push notifications: {fcm_state}")
    keepalive_task = None
    if settings.OLLAMA_ENABLED:
        keepalive_task = asyncio.create_task(_ollama_keepalive_loop())
    else:
        logger.info("Ollama disabled — 워밍업 루프를 띄우지 않는다 (AI 설명은 폴백 문구)")

    yield # 여기서 FastAPI 앱이 실행됨
    if keepalive_task is not None:
        keepalive_task.cancel()
    await engine.dispose()
    logger.info("Backend shutdown complete")


app = FastAPI(
    title="AI 의약품 상호작용 분석 플랫폼",
    description="약물 상호작용 분석 및 AI 기반 안전 가이드",
    version="0.1.0",
    lifespan=lifespan, #생명주기
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# Rate Limiting
app.state.limiter = limiter
# slowapi 핸들러는 RateLimitExceeded 전용 시그니처라 Starlette 의 일반 핸들러 타입과 맞지 않는다(동작은 정상).
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]

# CORS (허용 origin 화이트리스트 + 선택적 정규식 — Vercel 프리뷰 배포용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# 허가정보 상세 보강으로 약 한 건의 주의사항이 최대 ~3만 자가 되어(복약함 13종 합 198KB) 응답이 커졌다.
# 한국어 텍스트는 gzip으로 약 1/4(52KB)까지 줄어든다. 작은 응답은 압축 이득이 없어 건너뛴다.
app.add_middleware(GZipMiddleware, minimum_size=1000)


# 보안 헤더
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if not settings.DEBUG:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
async def health_check(db: AsyncSession = Depends(get_db)):
    """외부 감시용. DB에 실제로 질의해 보고 실패하면 503.

    DB가 죽으면 감시 도구가 알 수 있도록 항상 ok를 반환하지 않는다. 로컬 LLM(AI 설명)은
    판정과 무관한 보조 기능이라 여기서 확인하지 않는다 — Ollama가 없어도 서비스는 정상이다.
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("헬스체크: DB 질의 실패")
        return JSONResponse(status_code=503, content={"status": "unavailable", "db": "down"})
    return {"status": "ok", "db": "ok"}
