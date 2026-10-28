# 백엔드 API 이미지 (단일 스테이지).
# 프론트(웹)는 Vercel 이 별도로 호스팅하므로 여기서는 API 만 빌드한다.
# 빌드 컨텍스트는 레포 루트지만(.dockerignore 로 대부분 제외) backend/ 만 필요.
FROM python:3.11-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser
WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-kor \
    && rm -rf /var/lib/apt/lists/*

# 고정밀 OCR 모델(tessdata_best, LSTM). apt의 tesseract-ocr-kor은 속도 우선 "fast" 모델이라
# 용량 '20mg'을 '2000'으로 읽는 등 정확도가 낮다. ocr_service.py가 이 경로가 있으면 쓰고 없으면
# fast 모델로 폴백한다.
ADD https://github.com/tesseract-ocr/tessdata_best/raw/4.1.0/kor.traineddata /usr/share/tessdata_best/kor.traineddata
ADD https://github.com/tesseract-ocr/tessdata_best/raw/4.1.0/eng.traineddata /usr/share/tessdata_best/eng.traineddata
RUN chmod -R a+rX /usr/share/tessdata_best

RUN pip install poetry==1.8.3
ENV POETRY_VIRTUALENVS_CREATE=false

COPY backend/pyproject.toml backend/poetry.lock* ./
# 자체 호스팅(내 PC)이라 이미지 크기 이점이 미미해 dev 그룹(pytest·ruff)도
# 함께 설치한다 — 컨테이너 안에서 바로 테스트/린트를 돌릴 수 있게.
RUN poetry install --no-interaction --no-ansi --no-root --with dev

COPY backend/ .

# 동기화 상태(체크포인트·마지막 성공 시각) 디렉터리 — compose 의 sync_state 볼륨이 여기 마운트된다.
# 이미지에 appuser 소유로 먼저 만들어 두면, 새 named volume 이 이 소유권을 이어받는다.
RUN mkdir -p /var/lib/goodmedicine && chown -R appuser:appuser /app /var/lib/goodmedicine
USER appuser

EXPOSE 8000
# PORT 환경변수가 있으면 그걸 쓰고, 없으면 8000 (compose가 127.0.0.1:8001:8000 으로 매핑)
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
