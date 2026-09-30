# 굿메디슨 — AI 의약품 상호작용 분석 플랫폼

> 처방전·약봉투를 촬영하면 OCR로 약품명을 추출해 복약함에 등록하고,
> 공공데이터 기반 DUR(병용금기·효능군중복주의) + 사용자 알레르기·연령대 규칙으로
> 위험도를 판정한 뒤, 그 결과를 로컬 LLM이 사람이 읽을 설명으로 풀어주는 헬스케어 앱.

- **프론트**: Flutter (웹·Android, `ios/` 프로젝트는 미생성 — 실질적으로 웹+Android) — <https://goodmedicine-hpdice.vercel.app>
- **백엔드**: FastAPI + PostgreSQL 16 + Ollama(로컬 LLM), Docker Compose 3컨테이너
- **데이터**: 공공데이터포털 의약품개요정보(e약은요)·제품 허가정보·낱알식별·DUR 병용금기/효능군중복주의

---

## 문제의식

여러 병원·약국에서 받은 약을 함께 먹을 때 생기는 상호작용은 환자가 스스로 알기 어렵다.
식약처가 DUR(Drug Utilization Review) 데이터를 공개하지만, 원본은 품목·성분 코드가 뒤섞인
수십만 행의 raw 테이블이라 그대로는 쓸 수 없다. 이 프로젝트는

1. 흩어진 공공데이터 4종을 **성분 코드 단위로 정규화한 통합 DB**로 적재하고,
2. 사진 한 장에서 **약품명을 4단계로 매칭**해 복약함을 만들고,
3. **규칙 기반(SQL 조회)으로 위험도를 확정**한 뒤,
4. 그 판정을 **로컬 LLM이 자연어로 설명**한다 — 판정 자체는 AI가 건드리지 않는다.

건강정보·복약정보는 전량 AES-256-GCM으로 암호화하고, 백엔드는 국내(개발자 PC)에서만
운영해 개인정보가 국외로 나가지 않도록 했다.

---

## 아키텍처

```
[Flutter 앱]                     [FastAPI 백엔드]                [PostgreSQL]

사진 촬영/선택 (image_picker)                                    drugs
  │ 이미지 업로드                                                drug_ingredients (약품→성분코드)
  ▼                                                              dur_ingredient_contraindications
POST /drugs/ocr ─▶ 서버 OCR(Tesseract) ─▶ 후보 추출 ─▶ 매칭      dur_ingredient_effect_groups
  │                                                              residual_interactions (잔여 폴백 217건)
  ▼                                                              medicine_box_entries · users · analysis_results
사용자가 체크박스로 확인
  │ POST /medicine-box ───────────▶ MedicineBoxService
  ▼                                    └─ 병용금기면 FCM 발송
홈 화면 진입 시 자동으로
  │ POST /analysis/quick-check ───▶ AnalysisService.quick_check
  ▼                                    │  (DB 규칙 조회만, AI 없음)
위험 배너 표시           복약함 약품 ─▶ 성분코드 해소 ─┬─ 병용금기 / 알레르기 성분 충돌 /
(critical / caution / safe)                          │  특정연령대금기 있음 → critical
  │                                                  ├─ 효능군중복 / 노인주의 있음 → caution
  │                                                  └─ residual_interactions 폴백 항상 병합
  ▼ (사용자가 "AI 설명 보기" 탭)
  │ POST /analysis/guide ─────────▶ AiGuideService.generate_guide
  ▼                                    └─ Ollama(로컬 LLM)에 프롬프트 전달
자연어 설명 표시                          판정 자체는 바꾸지 않음
```

### 관통하는 설계 원칙

> **"판정은 규칙(SQL 조회), 설명은 AI."**
>
> `AnalysisService.quick_check()`가 critical/caution/safe를 규칙으로 확정하고,
> `AiGuideService`는 그 결과를 사람이 읽기 쉬운 문장으로 바꿔줄 뿐이다.
> Ollama가 죽어도 판정은 100% 동작하며, 안전한 폴백 문구로 대체된다.
> (ML 링크 예측 모델도 시도했으나 AUROC 0.48로 서빙에서 제외 — `archive/ml/`)

### 위험도 판정 경로 (성분 단위가 유일한 정식 경로)

복약함 약품을 `drug_ingredients`로 DUR 성분코드(`INGR_CODE`)에 해소한 뒤:

| 조건 | 등급 |
|---|---|
| `dur_ingredient_contraindications`에 성분쌍 존재 | **critical** |
| 사용자 알레르기 성분과 겹침 (`users.allergy_info`, 2026-09-12) | **critical** |
| 특정연령대금기 해당 (`dur_ingredient_age_caution`, 출생연도 등록 시) | **critical** |
| 위 셋 없고 `dur_ingredient_effect_groups` 효능군중복 존재 | **caution** |
| 위 없고 노인주의 해당(만 65세 이상, 출생연도 등록 시) | **caution** |
| 아무것도 없음 | **safe** |

알레르기·연령대 판정은 `quick_check`가 `user_id`를 받았을 때만 동작하고(비로그인
경로 없음), 출생연도·알레르기를 등록 안 했으면 해당 검사만 조용히 스킵된다.

성분코드가 해소되지 않는 약이 낀 217쌍만 소형 `residual_interactions`에 폴백으로 두고
**항상 함께 조회·병합**한다. 구 품목쌍 테이블 `drug_interactions`(331K행·227MB)는
성분 경로가 그 탐지의 100%를 재현함이 DB 전수검증으로 확인되어 마이그레이션 `0006`에서
폐기됐다(DB 311MB → 85MB).

### 약품 매칭 4단계 (`DrugService`)

| 순위 | 방식 |
|---|---|
| 1 | `drug_key` prefix 검색 (정확 일치 우선 정렬) |
| 2 | 정규화 `drug_key` 완전 일치 |
| 3 | `item_name`/`simple_name` ILIKE 부분 문자열 |
| 4 (최후수단) | `ingr_name` JSONB 성분명 기반 재검색 — "와파린정"처럼 브랜드명이 성분명을 괄호에 숨긴 입력 대응 |

---

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 프론트 | Flutter 3.35 / Provider / go_router / dio / firebase_messaging / image_picker |
| 백엔드 | FastAPI / SQLAlchemy 2.0 async / Alembic / Pydantic v2 / Poetry |
| DB | PostgreSQL 16 (pg_trgm 퍼지검색, JSONB) |
| OCR | Tesseract (kor+eng), 이미지 미저장 — 메모리 처리 후 폐기 |
| LLM | Ollama + `qwen2.5:14b-instruct` (GPU passthrough, 외부 API 미사용) |
| 보안 | JWT(AT 30분 / 단일사용 RT 7일), bcrypt, AES-256-GCM 필드 암호화, Rate Limiting |
| 인프라 | Docker Compose / Tailscale Funnel(백엔드 외부 노출) / Vercel(웹) / GitHub Actions(APK·웹 CI) |
| 테스트 | pytest-asyncio + httpx(ASGITransport), 격리 테스트 DB, Ollama mock |

---

## 코드 둘러보기

가장 먼저 볼 파일 네 개:

| 파일 | 왜 중요한가 |
|---|---|
| [`backend/app/services/analysis_service.py`](backend/app/services/analysis_service.py) | `quick_check()` — 이 앱의 본체. 규칙 기반 위험도 판정(DUR+알레르기+연령대), AI 미관여 |
| [`backend/app/services/drug_service.py`](backend/app/services/drug_service.py) | OCR 텍스트 → DB 약품 4단계 매칭 알고리즘 |
| [`backend/app/services/ai_guide_service.py`](backend/app/services/ai_guide_service.py) | 판정을 바꾸지 않는 "첨언" 역할, 로컬 LLM 프롬프트 설계·폴백 |
| [`backend/app/core/encryption.py`](backend/app/core/encryption.py) | "누가 무슨 약을 먹는지"도 민감정보로 보고 통째 암호화 |
| [`backend/app/services/public_data_service/`](backend/app/services/public_data_service/) | 공공데이터 동기화(`sync.py`가 호출) — 책임별 믹스인 9개 파일로 분할 |

### 디렉토리

```
backend/
  app/
    api/v1/          auth · users · drugs · medicine-box · analysis (엔드포인트 17개)
    services/        비즈니스 로직 (위 표 참고) + public_data_service/(패키지)
    core/            encryption · config · security
    models/ schemas/ db/
  alembic/           마이그레이션 0001~0009 + ce94face11b4(출생연도·연령대 규칙)
  sync.py            공공데이터 동기화 CLI (overview · dur_contraindications · efcy_dplct ·
                     dur_age_caution · dur_extra_codes · identification · approval · …)
  tests/             pytest (68개)
front_app/
  lib/
    core/            api · models · notifications(fcm·복약알림 스케줄러) · storage · theme · widgets
    features/        auth · camera · home(+widgets/ 9개 파일) · profile(건강정보·알레르기·출생연도) · search
docs/
  project-status.md  전체 진행 현황 + 시스템 커버리지 명세
  개발일지.md         의사결정·문제 해결 기록 (포트폴리오용)
  deploy-tailscale.md · deploy-web-vercel.md
archive/ml/          서빙에서 제외한 링크 예측 모델 실험 (AUROC 0.48)
```

### 상세 문서

- **[docs/project-status.md](docs/project-status.md)** — 진행 현황, 배포, 시스템 커버리지 명세
- **[docs/개발일지.md](docs/개발일지.md)** — 개발 일지
- **[archive/ml/README.md](archive/ml/README.md)** — ML 링크 예측을 왜 서빙에서 뺐는가

---

## 로컬 실행

```cmd
:: 전체 서비스 (PostgreSQL + FastAPI + Ollama)
cd C:\Dev\drugTest
docker compose up -d

:: 마이그레이션 + 공공데이터 동기화 (완전 초기화 시)
docker exec -it drugtest-backend-1 alembic upgrade head
docker exec -it drugtest-backend-1 python sync.py status

:: 로컬 LLM 모델 최초 1회 pull (GPU 필요)
docker exec drugtest-ollama-1 ollama pull qwen2.5:14b-instruct

:: 테스트
docker exec -e PYTHONPATH=/app -w /app drugtest-backend-1 python -m pytest tests/ -v
```

- Swagger UI: `http://localhost:8001/api/docs` (DEBUG=true 환경에서만)
- 백엔드 호스트 포트는 **8001** (8000은 다른 프로젝트가 점유)
- Flutter: `flutter run --dart-define=BASE_URL=http://10.0.2.2:8001/api/v1/` (끝 슬래시 필수)

GPU가 없는 환경에서는 `/analysis/guide`가 안전한 폴백 문구로만 응답한다 — **판정 자체는 영향 없음.**

---

## 시스템 커버리지 한계 (의도적으로 명시)

`quick_check`는 DUR **병용금기·효능군중복주의**에 더해(2026-09-12부터) 로그인
사용자의 **알레르기 성분 충돌**·**특정연령대금기·노인주의**까지 탐지한다. 다만
특정연령대금기는 실측상 한계가 있다 — 원본 API(`getSpcifyAgrdeTabooInfoList03`)
응답에 나이 기준을 담은 구조화 필드가 없고, 자유 텍스트에서 숫자 패턴("OO세 미만")이
파싱되는 행은 **3.6%뿐**이라 나머지는 판정에서 조용히 스킵된다. 병용주의(별도 등급),
용량주의·투여기간주의는 API에 엔드포인트와 `INGR_CODE`가 존재하지만 아직 미적재다 —
**데이터 커버리지의 한계이지 코드 버그가 아니다.** 예: 와파린은 국내 DUR 병용금기
DB에 등록된 상호작용이 0건이라 타이레놀×와파린은 탐지되지 않는다. 상세는
[docs/project-status.md](docs/project-status.md) "시스템 커버리지 명세" 참고.

미구현(초기 기획엔 있었으나 코드엔 없음): AI 월간 리포트, 가족 공유, 응급 모드,
대체약 추천, DUR 병용주의·용량주의·투여기간주의. **낱알 이미지 인식은 필터
(모양·색상·각인) 방식으로 판별력까지 검증했으나(각인 입력 시 90.4%가 후보 1건으로
좁혀짐) "사진 찍으면 자동 인식"이라는 기대와 맞지 않아 폐기 결정**(CLAUDE.md 참고).
복약 알림(복용 시간)·규칙 기반 알레르기 충돌 검사는 2026-09-12 구현 완료.

---

## 배포

| 구성 | 위치 | 이유 |
|---|---|---|
| 백엔드 API + LLM | 로컬 `docker compose` + Tailscale Funnel (`goodmedicine.tail9f1768.ts.net`) | 개인정보(암호화 건강·복약정보)를 국내에서만 저장·처리 |
| 프론트 웹 | Vercel (`goodmedicine-hpdice.vercel.app`) | 프론트엔 개인정보 없음 → 해외 호스팅 무방 |
| 모바일 APK | GitHub Actions 빌드 (`--dart-define=BASE_URL=…tail9f1768.ts.net/api/v1/`) | |

PC가 켜져 있을 때만 백엔드 접속 가능(시연 영상 백업 보유).
