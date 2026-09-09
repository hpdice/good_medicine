# 빌드 컨텍스트 = 레포 루트 (docker-compose.yml 의 context: . — backend/ + front_app/ 둘 다 필요)
# ─────────────────────────────────────────────────────────────────────────────
# 1) Flutter 웹 번들 빌드 — 배포 이미지에서만 사용 (로컬 docker compose는 target: backend-base)
# ─────────────────────────────────────────────────────────────────────────────
FROM ghcr.io/cirruslabs/flutter:stable AS webbuild
WORKDIR /src
COPY front_app/pubspec.yaml front_app/pubspec.lock ./
RUN flutter pub get
COPY front_app/ ./
# 같은 주소(오리진)에서 API를 호출하므로 상대 경로. 모바일 APK는 별도로 절대 URL을 준다.
# --pwa-strategy=none: 서비스 워커 비활성화 — 재배포 때 브라우저 캐시가 옛 빌드를 붙들지 않게.
RUN flutter build web --release --pwa-strategy=none --dart-define=BASE_URL=/api/v1/

# ─────────────────────────────────────────────────────────────────────────────
# 2) 백엔드 베이스 — 로컬 docker compose는 여기까지만 빌드 (Flutter 스테이지 스킵 → 빠름)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS backend-base

RUN groupadd -r appuser && useradd -r -g appuser appuser
WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-kor \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry==1.8.3
ENV POETRY_VIRTUALENVS_CREATE=false

COPY backend/pyproject.toml backend/poetry.lock* ./
# backend-base 는 로컬 개발/테스트용 — dev 그룹(pytest·ruff·mypy)까지 넣는다.
# 배포 이미지(full)는 아래에서 --only main 으로 다시 잘라낸다.
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root --with dev

COPY backend/ .
RUN poetry install --no-interaction --no-ansi --no-root --with dev

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
# PORT 환경변수가 있으면 그걸 쓰고, 없으면 8000 (compose가 127.0.0.1:8001:8000 으로 매핑)
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

# ─────────────────────────────────────────────────────────────────────────────
# 3) 최종(배포) — 백엔드 + Flutter 웹 번들. 링크 1개로 웹 화면 + API 서빙.
# ─────────────────────────────────────────────────────────────────────────────
FROM backend-base AS full
USER root
# 배포 이미지에서 dev 의존성(pytest·ruff·mypy) 제거 — main 만 남긴다.
RUN poetry install --no-interaction --no-ansi --no-root --only main --sync
COPY --from=webbuild /src/build/web ./web
RUN chown -R appuser:appuser /app/web
USER appuser
