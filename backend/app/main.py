import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    logger.info(f"FCM push notifications: {'enabled' if fcm_service.is_configured() else 'disabled'}")
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

# CORS (허용 origin 화이트리스트)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
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


# Flutter 웹 번들 서빙 (배포 이미지에만 /app/web 존재 — 로컬 docker compose엔 없음).
# 링크 1개로 웹 화면(`/`) + API(`/api/v1/`)를 같은 오리진에서 제공 → CORS·별도 프론트 호스팅 불필요.
_WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.isdir(_WEB_DIR):

    class _SpaStaticFiles(StaticFiles):
        """SPA 폴백: 없는 경로는 404 대신 index.html (go_router가 클라이언트에서 처리).

        현재 빌드는 해시 라우팅(`/#/...`)이라 사실상 `/` 만 서빙되지만, path URL 전략으로
        바꿔도 새로고침 시 404가 안 나도록 대비해 둔다. (신형 Starlette는 미존재 경로에
        404 응답 대신 HTTPException 을 던지므로 그것을 잡는다.)
        """

        # 매 배포마다 바뀌는 엔트리 파일은 브라우저가 재검증하게 한다
        # (Flutter 웹 재배포 후 옛 화면이 캐시로 남는 문제 방지). "." = 루트("/") 요청.
        _NO_STORE = {".", "", "index.html", "flutter_bootstrap.js", "flutter.js"}

        async def get_response(self, path: str, scope):
            no_store = path in self._NO_STORE
            try:
                response = await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                # API 404는 그대로 404 (HTML로 덮지 않음). 그 외 없는 경로만 SPA 폴백.
                if exc.status_code == 404 and not path.startswith(("api/", "health")):
                    response = await super().get_response("index.html", scope)
                    no_store = True  # 폴백으로 index.html 을 주는 경우도 캐시 금지
                else:
                    raise
            if no_store:
                response.headers["Cache-Control"] = "no-store, must-revalidate"
            return response

    app.mount("/", _SpaStaticFiles(directory=_WEB_DIR, html=True), name="web")
    logger.info(f"Serving Flutter web bundle from {_WEB_DIR}")
