# 굿메디슨 — AI 의약품 상호작용 분석 플랫폼

> 처방전·약봉투를 촬영하면 OCR로 약품명을 추출해 복약함에 등록하고,
> 식약처 DUR(병용금기·효능군중복·특정연령대금기·노인주의·임부금기) 규칙과 사용자 알레르기로
> 위험도를 판정한 뒤, 그 결과를 로컬 LLM이 쉬운 말로 풀어 설명하는 헬스케어 앱.

- **프론트**: Flutter (웹·Android) — <https://goodmedicine-hpdice.vercel.app>
- **백엔드**: FastAPI + PostgreSQL 16 + Ollama(로컬 LLM), Docker Compose 3컨테이너
- **데이터**: 공공데이터포털 식약처 의약품개요정보(e약은요) · 의약품 제품 허가정보 · DUR 품목정보(병용금기·효능군중복주의·특정연령대금기·노인주의·임부금기)

---

## 문제의식

여러 약을 함께 먹을 때 생기는 상호작용은 환자가 스스로 알기 어렵다. 의사·약사는 처방·조제 때
DUR 점검을 받지만, 처방 없이 구하는 일반의약품이나 다른 기관에서 받은 약이 더해지면 그 점검에
잡히지 않을 수 있다. 식약처가 DUR 데이터를 공개하지만 원본은 품목·성분 코드가 뒤섞인 수십만 행의
raw 테이블이라 그대로는 쓸 수 없다. 이 프로젝트는

1. 공공데이터를 **성분 코드 단위로 정규화한 통합 DB**로 적재하고,
2. 사진 한 장에서 **약품명을 단계별로 매칭**해 복약함을 만들고,
3. **규칙 기반(SQL 조회)으로 위험도를 확정**한 뒤,
4. 그 판정을 **로컬 LLM이 자연어로 설명**한다 — 판정 자체는 AI가 건드리지 않는다.

건강정보·복약정보는 AES-256-GCM으로 암호화해 저장하고, 설명 생성에는 외부 AI API를 쓰지 않고
로컬 LLM만 사용한다.

---

## 아키텍처

```
[Flutter 앱]                     [FastAPI 백엔드]                [PostgreSQL]

사진 촬영/선택 (image_picker)                                    drugs
  │ 이미지 업로드                                                drug_ingredients (약품→성분코드)
  ▼                                                              dur_ingredient_contraindications
POST /drugs/ocr ─▶ 서버 OCR(Tesseract) ─▶ 후보 추출 ─▶ 매칭      dur_ingredient_effect_groups
  │                                                              dur_ingredient_age_caution
  ▼                                                              dur_item_pregnancy_taboo
사용자가 체크박스로 확인                                         residual_interactions (잔여 폴백)
  │ POST /medicine-box ───────────▶ MedicineBoxService           medicine_box_entries · users · analysis_results
  ▼                                    ├─ 약 상세(허가정보) 온디맨드 보강
홈 화면 진입 시 자동으로                └─ 병용금기면 FCM 발송
  │ POST /analysis/quick-check ───▶ AnalysisService.quick_check
  ▼                                    │  (DB 규칙 조회만, AI 없음)
위험 배너 표시           복약함 약품 ─▶ 성분코드 해소 ─┬─ 병용금기 / 알레르기 / 특정연령대금기 / 임부금기 → critical
(critical / caution / safe)                          ├─ 동일 성분·효능군 중복 / 노인주의 → caution
  │                                                  └─ residual_interactions 폴백 항상 병합
  ▼ (사용자가 "AI 설명 보기" 탭)
  │ POST /analysis/guide ─────────▶ AiGuideService.generate_guide
  ▼                                    └─ 판정 결과·약품 정보·용어 풀이를 근거로 Ollama가 설명 생성
쉬운 말 설명 표시                         판정 자체는 바꾸지 않음
```

### 관통하는 설계 원칙

> **"판정은 규칙(SQL 조회), 설명은 AI."**
>
> `AnalysisService.quick_check()`가 critical/caution/safe를 규칙으로 확정하고,
> `AiGuideService`는 그 결과를 사람이 읽기 쉬운 문장으로 바꿔줄 뿐이다.
> Ollama가 응답하지 않아도 판정은 그대로 동작하고, 설명은 안전한 안내 문구로 대체된다.

### 위험도 판정 경로 (성분 단위가 정식 경로)

복약함 약품을 `drug_ingredients`로 DUR 성분코드(`INGR_CODE`)에 해소한 뒤:

| 조건 | 등급 |
|---|---|
| `dur_ingredient_contraindications`에 성분쌍 존재 | **critical** |
| 사용자 알레르기 성분과 겹침 (`users.allergy_info`) | **critical** |
| 특정연령대금기 해당 (`dur_ingredient_age_caution`, 출생연도 등록 시) | **critical** |
| 임부금기 해당 (`dur_item_pregnancy_taboo`, 프로필에서 "임신 중" 설정 시) | **critical** |
| 위 해당 없고 같은 성분 중복 또는 `dur_ingredient_effect_groups` 효능군 중복 존재 | **caution** |
| 위 없고 노인주의 해당(만 65세 이상, 출생연도 등록 시) | **caution** |
| 아무것도 없음 | **safe** |

알레르기·연령대·임부 판정은 `quick_check`가 `user_id`를 받았을 때만 동작하고(비로그인 경로 없음),
해당 정보를 등록하지 않았으면 그 검사만 건너뛴다. `safe`는 "DUR에 등록된 규칙에 걸리지 않음"이라는 뜻이며
안전 보증이 아니다.

성분코드를 해소하지 못한 약이 낀 쌍은 소형 `residual_interactions`에 폴백으로 두고 **항상 함께 조회·병합**한다.

### 약품 매칭 (`DrugService`)

| 순위 | 방식 |
|---|---|
| 1 | `drug_key` prefix 검색 (정확 일치 우선 정렬) |
| 2 | 정규화 `drug_key` 완전 일치 |
| 3 | `item_name`/`simple_name` ILIKE 부분 문자열 |
| 4 | `ingr_name` JSONB 성분명 기반 재검색 — "와파린정"처럼 브랜드명이 성분명을 괄호에 숨긴 입력 대응 |
| 5 | 앞 단계가 모두 빈손일 때만 유사도 기반 후보 — 자동 확정하지 않고 "유사 약품"으로만 제시 |

### AI 설명 (`AiGuideService`)

설명은 DB 근거 안에서만 쓰도록 제한한다.

- **근거**: DUR 판정 원문, 해당 약의 분류·효능·주의사항, 출처를 확인한 의학 용어 풀이(`glossary.py`).
  판정 문장에 풀이가 있는 용어가 나올 때만 `[용어 풀이]`로 넘기고, 없는 용어는 모델이 풀이하지 않는다.
- **구성**: 각 약 소개 → 식약처 기준으로 왜 위험한지 → 대응. 말투는 앱 화면과 같은 해요체.
- **응답 처리**: 마크다운 제거 → 한자·등급 코드·복용 중단 권유·대체 약/다른 치료법 제안·근거 없는 연구 인용·
  출처 없는 용어 풀이 문장 제거 → 남길 문장이 없을 때만 1회 재생성 후 폴백.
- **대응 문장은 AI가 아니라 코드가 판정 종류별로 붙인다**(알레르기·임부·연령·병용, 일반의약품이 낀 병용은 별도 문장).
- 문제가 없으면(`safe`) 모델을 부르지 않고 정해진 문장을 낸다.
- 생성 결과는 `analysis_results`에 암호화 저장한다.

---

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 프론트 | Flutter / Provider / go_router / dio / firebase_messaging / image_picker |
| 백엔드 | FastAPI / SQLAlchemy 2.0 async / Alembic / Pydantic v2 / Poetry |
| DB | PostgreSQL 16 (pg_trgm 퍼지검색, JSONB) |
| OCR | Tesseract (kor+eng), 이미지 미저장 — 메모리 처리 후 폐기 |
| LLM | Ollama + `qwen2.5:14b-instruct` (GPU passthrough, 외부 API 미사용) |
| 보안 | JWT(AT 30분 / 단일사용 RT 7일), bcrypt, AES-256-GCM 필드 암호화, Rate Limiting(로그인은 IP 단위 + 계정별 실패 횟수) |
| 인프라 | Docker Compose / Tailscale Funnel(백엔드 외부 노출) / Vercel(웹) / GitHub Actions(백엔드 테스트·APK·웹) |
| 테스트 | pytest-asyncio + httpx(ASGITransport), 격리 테스트 DB, Ollama mock — push 시 CI 실행(린트·타입 검사·pytest) |
| 운영 | 매일 DB 백업(복원 검증), 월간 공공데이터 갱신(품질 게이트), DB 확인 헬스체크 — [운영 런북](docs/operations.md) |

---

## 코드 둘러보기

| 파일 | 역할 |
|---|---|
| [`backend/app/services/analysis_service.py`](backend/app/services/analysis_service.py) | `quick_check()` — 규칙 기반 위험도 판정(DUR·알레르기·연령대·임부), AI 미관여 |
| [`backend/app/services/drug_service.py`](backend/app/services/drug_service.py) | OCR 텍스트 → DB 약품 단계별 매칭 |
| [`backend/app/services/ai_guide_service.py`](backend/app/services/ai_guide_service.py) | 판정을 바꾸지 않는 설명 생성 — 프롬프트·응답 처리·폴백 |
| [`backend/app/services/glossary.py`](backend/app/services/glossary.py) | 출처 있는 의학 용어 풀이 |
| [`backend/app/core/encryption.py`](backend/app/core/encryption.py) | 건강·복약정보 필드 암호화 |
| [`backend/app/services/public_data_service/`](backend/app/services/public_data_service/) | 공공데이터 동기화(`sync.py`가 호출) — 책임별 믹스인 파일로 분할 |

### 디렉토리

```
backend/                 FastAPI 백엔드 (Docker 이미지에는 이 폴더만 들어간다)
  app/
    api/v1/              auth · users · drugs · medicine-box · analysis
    services/            비즈니스 로직 + public_data_service/(공공데이터 동기화 패키지)
    core/                encryption · security · rate_limit · login_guard · logging
    models/ schemas/ db/
  alembic/               DB 마이그레이션
  sync.py                공공데이터 동기화 CLI (status · overview · approval · dur_contraindications ·
                         efcy_dplct · dur_age_caution · dur_pregnancy · build_drug_ingredients · …)
  validate_db.py         데이터 품질 게이트 (치명 문제 시 종료 코드 1)
  seed/                  DB 완전 초기화 시 복원하는 잔여 폴백 데이터
  tests/                 pytest
front_app/               Flutter 앱 (Android · Web)
  lib/core/              api · models · notifications(FCM·복약 알림) · storage · theme · widgets
  lib/features/          auth · camera · home · profile · search
docs/                    문서 (아래 "상세 문서")
scripts/                 운영 스크립트 (PowerShell, Windows 작업 스케줄러가 실행)
  backup-db.ps1          DB 백업 + 임시 DB 복원 검증 (매일)
  monthly-sync.ps1       백업 → 공공데이터 동기화 → 품질 게이트 (매월)
infrastructure/          postgres 초기화 SQL · Tailscale Funnel 설정
secrets/                 런타임 비밀 파일 (README만 커밋, 컨테이너에 읽기 전용 연결)
docker-compose.yml       postgres · backend · ollama   (+ .override.yml 개발 / .prod.yml 배포)
.github/workflows/       backend-tests · deploy-web(Vercel) · release-apk
```

### 상세 문서

| 문서 | 내용 |
|---|---|
| **[docs/project-status.md](docs/project-status.md)** | 현재 상태 — 진행 현황, 시스템 커버리지 명세 |
| **[docs/operations.md](docs/operations.md)** | 운영 런북 — 백업·복원, 암호화 키 보관, 월간 갱신, 감시 |

---

## 로컬 실행

```cmd
:: 처음 한 번 — 설정 파일 준비
copy .env.example .env                  :: 값 채우기 (SECRET_KEY, FIELD_ENCRYPTION_KEY 등)
:: (선택) FCM 푸시: secrets\firebase-service-account.json 배치 — secrets\README.md

:: 전체 서비스 (PostgreSQL + FastAPI + Ollama) — 개발 모드
docker compose up -d
:: 코드 변경 후 반영 (--reload 없음)
docker compose restart backend

:: 마이그레이션 + 공공데이터 동기화 (완전 초기화 시)
docker exec -it drugtest-backend-1 alembic upgrade head
docker exec -it drugtest-backend-1 python sync.py status

:: 로컬 LLM 모델 최초 1회 pull (GPU 필요)
docker exec drugtest-ollama-1 ollama pull qwen2.5:14b-instruct

:: 테스트
docker exec -e PYTHONPATH=/app -w /app drugtest-backend-1 python -m pytest tests/ -v
```

**편집기(VS Code) 환경** — 백엔드 코드는 컨테이너에서 돌지만, 편집기의 타입 검사(Pylance)가 import를 찾으려면
로컬 가상환경이 필요하다. 한 번만:

```cmd
cd backend
poetry install --no-root --with dev      :: poetry.lock 그대로 설치 (lock 을 다시 만들지 말 것 — 이미지는 Poetry 1.8.3)
```

그다음 VS Code에서 `Python: Select Interpreter` → 방금 만든 `drugtest-backend-…` 환경 선택. 검사 기준은 루트의
`pyrightconfig.json`(`backend/`를 import 기준으로, basic 모드) — CI도 같은 설정으로 검사한다.

- Swagger UI: `http://localhost:8001/api/docs` (DEBUG=true 환경에서만)
- 백엔드 호스트 포트는 **8001**
- Flutter: `flutter run --dart-define=BASE_URL=http://10.0.2.2:8001/api/v1/` (끝 슬래시 필수)

GPU가 없는 환경에서는 `/analysis/guide`가 안내 문구로만 응답한다 — **판정 자체는 영향 없음.**

---

## 커버리지 한계

판정은 DUR에 등록된 규칙만 대상으로 하므로, 등록되지 않은 조합은 탐지하지 못한다. 예: 와파린은 국내 DUR
병용금기에 등록된 상호작용이 없어 타이레놀×와파린은 탐지되지 않는다. 특정연령대금기는 원본 응답에 나이 기준을
담은 구조화 필드가 없어, 자유 텍스트에서 나이 기준을 뽑을 수 있는 규칙만 판정에 쓰인다. 병용주의(별도 등급)·
용량주의·투여기간주의는 아직 판정에 쓰지 않는다. 상세는 [docs/project-status.md](docs/project-status.md)
"시스템 커버리지 명세" 참고.

---

## 배포

| 구성 | 위치 |
|---|---|
| 백엔드 API + LLM | `docker compose` + Tailscale Funnel (`goodmedicine.tail9f1768.ts.net`) |
| 프론트 웹 | Vercel (`goodmedicine-hpdice.vercel.app`) |
| 모바일 APK | GitHub Actions 빌드 (`--dart-define=BASE_URL=…tail9f1768.ts.net/api/v1/`) |

배포 모드 실행: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` —
운영 절차는 [docs/operations.md](docs/operations.md).
