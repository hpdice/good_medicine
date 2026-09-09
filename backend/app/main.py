import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import api_router
from app.config import settings
from app.core.logging import logger, setup_logging
from app.core.rate_limit import limiter
from app.db.session import engine
from app.services import fcm_service
from app.services.ollama_client import OllamaClient


async def _ollama_keepalive_loop() -> None:
    """AI 가이드용 로컬 LLM이 GPU에서 내려가지 않게 주기적으로 핑을 보낸다.

    콜드스타트(모델을 GPU에 새로 올림, 실측 87~153초)가 실제 사용자 요청에서
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(f"Starting drugtest backend (debug={settings.DEBUG})")
    fcm_state = "enabled" if fcm_service.is_configured() else "disabled"
    logger.info(f"FCM push notifications: {fcm_state}")
    keepalive_task = asyncio.create_task(_ollama_keepalive_loop())
    yield
    keepalive_task.cancel()
    await engine.dispose()
    logger.info("Backend shutdown complete")


app = FastAPI(
    title="AI 의약품 상호작용 분석 플랫폼",
    description="약물 상호작용 분석 및 AI 기반 안전 가이드",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# Rate Limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS (허용 origin 화이트리스트 + 선택적 정규식 — Vercel 프리뷰 배포용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


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
async def health_check():
    return {"status": "ok"}
