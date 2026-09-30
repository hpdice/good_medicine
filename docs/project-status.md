# 프로젝트 전체 현황

> 기준일: 2026-09-17. **이 문서는 "지금 상태" 스냅샷만** — 날짜별 작업 서사(계획/문제/결론)는
> [개발일지.md](./개발일지.md).
>
> 배포 완료: 백엔드+Ollama는 국내 PC(`docker compose` + Tailscale Funnel), 프론트 웹은 Vercel,
> APK는 GitHub Releases.

---

## 전체 진행률

| 영역 | 진행률 | 상태 |
|---|---|---|
| 백엔드 코드 | 100% | ✅ 완료. 2026-09-12: `public_data_service.py`(1,114줄 단일 파일) → 책임별 9개 파일 패키지로 분할(믹스인 조합, `sync.py`/`drug_service.py` import 무변경) |
| 인프라 (Docker) | 100% | ✅ 완료 (postgres·backend·ollama, backend는 호스트 8001. 배포 overlay는 tailscale 컨테이너 추가) |
| DB 마이그레이션 | 100% | ✅ 완료 (0001~0009 + `ce94face11b4` + `0010` — 성분 단위 전환·품목 테이블 폐기·risk_tags·복약정보 필드암호화·출생연도·연령대 규칙 테이블·낱알식별 죽은 컬럼/인덱스 제거) |
| 데이터 적재 | 100% | ✅ 완료 + 품질 검증 통과 |
| Flutter 앱 프론트엔드 | 100% | ✅ 완료. OCR은 서버 처리로 전환(`image_picker`, 웹 포함 전 플랫폼). 2026-09-12: 복약 알림·내 정보(건강정보/알레르기/출생연도) 화면 추가 + `home_screen.dart`(865줄) → 177줄+위젯 9개 파일로 분할 |
| 백엔드 E2E 테스트 | 핵심 플로우 완료 | ✅ **68개** 테스트 통과 (2026-09-30: 탈퇴 처리·Rate Limit 키·헬스체크·동기화 누락 회귀 16개 추가, CI에서도 실행 / 성분 전환·서버 OCR·복약정보 암호화·알레르기 충돌·연령대 규칙·복약 알림 필드 커버) |
| AI 대응 가이드 (로컬 LLM) | 완료 | ✅ Ollama + Qwen2.5 14B. 배포도 로컬 PC(GPU)라 **풀 동작** — Funnel 경유 실측: `is_ai_generated=true`, 308자 실제 생성 |
| FCM 푸시 알림 | 완료 | ✅ Firebase 프로젝트(`good-medicine-app`) 연동, 디버그 APK 빌드 검증 완료 |
| 배포 | 백엔드 국내 PC · 프론트 Vercel | ✅ 백엔드(API): 로컬 `docker compose` + Tailscale Funnel 컨테이너(`goodmedicine.tail9f1768.ts.net/api/v1/`). 프론트(웹): `git push` → GitHub Actions → Vercel(`goodmedicine-hpdice.vercel.app`). **개인정보는 백엔드·DB(국내 PC)에만.** 아래 참고 |
| APK 배포 채널 | 완료 | ✅ GitHub Releases(`v0.1.0-test`)로 사이드로드 배포 중 — Play 미등록 상태라 설치 시 Play 프로텍트 경고는 정상 |

---

## 데이터 적재 현황

```
drugs 전체            :  35,505건
├─ 효능정보(efcy)     :   4,884건  ← e약은요
├─ 성분JSONB(ingr)    :   7,628건  ← main_item_ingr 파싱
└─ 허가정보           :  35,296건  ← 허가일자 기준

drug_ingredients                    : 24,822건  ← 성분 단위 판정 조인 브리지 (drugs의 61.5% 해소)
dur_ingredient_contraindications    :    357건  ← DUR 병용금기 (성분쌍, 정식 경로)
dur_ingredient_effect_groups        :    259건  ← DUR 효능군중복주의 (성분 단위)
dur_ingredient_age_caution          :    203건  ← 특정연령대금기(123)+노인주의(80), 2026-09-12 신규
residual_interactions               :    217건  ← 성분코드 미해소 약이 낀 잔여 폴백 (2026-09-01 시드로 고정 —
                                                   DUR 병용금기 API는 항상 성분코드를 채워줘서 라이브 갱신 불가함을 2026-09-17 실측 확인)
```

> 구 품목 테이블 `drug_interactions`(331K행)·`drug_effect_groups`는 성분 경로가 그 탐지의 100%를
> 재현함을 전수검증 후 **0006 마이그레이션에서 폐기**(DB 311MB→85MB). 2026-09-17: 낱알식별
> 죽은 컬럼 5개(폐기된 사진 인식 기능의 잔재)·안 쓰는 인덱스 3개 추가 제거(**85MB→77MB**,
> 마이그레이션 `0010`).

### DB 품질 검증 결과 (`validate_db.py`)

| 항목 | 결과 |
|---|---|
| 자기 자신 상호작용 | ✅ 0건 |
| 깨진 참조(residual_interactions·drug_ingredients) | ✅ 0건 |
| DUR 비정상 item_seq | ✅ 0건 |
| drug_key 중복 | ✅ 허용 174그룹 (수출용·개량신약 variants — 정상) |
| item_name 3자 미만 | ✅ 허용 3건 (API 원본 자체가 짧은 이름) |
| 허가일자 누락 | ✅ 3건 (API 원본 없음) |
| 분류명 누락 | ✅ 49건 (API 원본 없음) |
| simple_name 누락 | ✅ 0건 |

---

## 백엔드 구현 현황

### 인프라
- Docker Compose: PostgreSQL 16 + FastAPI + Ollama (배포 overlay는 tailscale 컨테이너 추가)
- 데이터 볼륨: `D:\drugTest\postgres_data` (bind mount), `ollama_data`·`tailscale_state` (named volume)
- Swagger UI: `http://localhost:8001/api/docs` (DEBUG=true 환경에서만)

### API 엔드포인트 (17개)

| 엔드포인트 | 기능 | 보안 |
|---|---|---|
| POST /auth/register | 회원가입 | — |
| POST /auth/login | 로그인 | Rate Limit 5회/15분 |
| POST /auth/refresh | 토큰 갱신 | Single-use RT |
| POST /auth/logout | 로그아웃 | JWT |
| GET /users/me | 내 정보 조회 | JWT |
| PATCH /users/me | 내 정보 수정 | JWT |
| DELETE /users/me | 회원 탈퇴 | JWT |
| GET /drugs?q= | 약품 검색 (pg_trgm 퍼지) | JWT |
| GET /drugs/{id} | 약품 상세 조회 | JWT |
| POST /drugs/ocr | 처방전 사진 업로드 → 서버 OCR(Tesseract) → 후보 추출 → 매칭 (이미지 미저장) | JWT · Rate Limit 20회/분 |
| POST /drugs/match-names | 텍스트 약품명 후보 일괄 매칭 | JWT |
| GET /medicine-box | 복약 목록 조회 | JWT |
| POST /medicine-box | 복약 약품 추가 (중복 방지, 병용금기 시 FCM 발송) | JWT |
| PATCH /medicine-box/{id} | 복약 정보 수정 | JWT |
| DELETE /medicine-box/{id} | 복약 약품 삭제 | JWT |
| POST /analysis/quick-check | 병용금기·효능군중복·알레르기 충돌·연령대 규칙 즉시 확인 | JWT · Rate Limit 60회/분 |
| POST /analysis/guide | quick-check 판정 결과에 로컬 LLM 설명(AI 첨언) 추가 | Rate Limit 10회/분 |

### 보안
- JWT Access Token 30분 + Single-use Refresh Token 7일 (모든 토큰에 `jti` 고유값 포함)
- AES-256-GCM 필드 암호화 (건강정보·알레르기·출생연도, **복약함 전체 payload**(drug_id·용량·복용시각·알림설정·메모 등), 분석이력 drug_ids·findings·AI 가이드) — "누가 무슨 약을 먹는지"도 민감정보로 취급. 복호화 실패 시 필드별 격리(계정 전체 500 방지)
- Rate Limiting — 로그인은 실제 클라이언트 IP, quick-check·guide·OCR은 로그인 사용자 단위(2026-09-30: 전 사용자가 Tailscale 프록시 IP 하나를 공유하던 문제 수정). 상세 `docs/operations.md`
- 보안 헤더 (X-Frame-Options, X-Content-Type-Options, HSTS)
- AuditLog (민감 작업 추적)
- 회원 탈퇴: email/hashed_password/name tombstone 처리 (개인정보 삭제 + 이메일 재사용 가능)

### 테스트
- `backend/tests/`: pytest + httpx(ASGITransport), 68개 E2E 테스트(스키마 1회 생성 + 테스트별 TRUNCATE), 운영 DB와 분리된 `drugtest_test_db` 사용
- 커버리지: 인증(회원가입/로그인/리프레시 단일사용/72바이트 초과 비밀번호 거부/탈퇴 후 재가입), 약품검색, 약품명 매칭(성분명 폴백·정밀매칭 우선순위 회귀), 복약함(추가/중복거부/삭제/복약 알림 필드 왕복·형식 검증), quick-check 3단계(critical/caution/safe) + 알레르기 충돌(정확·부분일치·미등록 스킵) + 연령대 규칙(특정연령대금기 경계값·파싱 실패 스킵·노인주의·미등록 스킵), AI 가이드(생성·암호화저장·Ollama 다운 시 폴백, Ollama는 mock), 사용자 정보(건강정보 왕복/복호화 손상 격리)
- Flutter: `flutter test` — `MedicationReminderService.computeSchedule`/`stableReminderId` 순수 함수 단위 테스트 9개(만료 처리·id 안정성)

## AI 대응 가이드 — 로컬 LLM

위험도 **판정**은 규칙 기반(`AnalysisService.quick_check`, DUR 직접 조회)이고,
AI는 그 결과를 사람이 읽을 설명으로 풀어쓰는 **보조("첨언") 역할만** — AI가 판정을
바꾸지 않도록 구조적으로 분리.

- **모델**: Ollama + `qwen2.5:14b-instruct` (~9GB). 외부 API 미사용 — 건강정보가 PC 밖으로 안 나감.
- **인프라**: docker-compose `ollama` 서비스, GPU passthrough(nvidia, RTX 4070 12GB).
- **RAG**: 임베딩이 아니라 구조화 조회 — quick_check가 찾은 `drug_id`로 `get_drugs_by_ids()` 재사용,
  복호화된 건강정보/알레르기도 컨텍스트에 포함.
- 2026-09-12: `quick_check`가 `user_id`를 받아 알레르기 충돌·연령대 규칙까지 판정하도록
  확장됨에 따라 `/guide`도 동일하게 `user_id`를 전달 — AI 가이드가 참고하는 위험도 스냅샷에
  이 두 신규 판정 결과가 자동으로 포함된다(AI 자체가 이 판정을 만드는 게 아니라 여전히
  `quick_check`의 확정 결과를 설명만 함).
- **안전장치**: Ollama 무응답 시(`OllamaUnavailableError`) 판정은 그대로, 가이드만 안전한 폴백 문구.
- **성능**(실측): 콜드스타트 87초~2분30초, 이후 요청 ~10~15초. `keep_alive:"30m"`,
  `OLLAMA_TIMEOUT_SECONDS=200`(콜드스타트 커버), 클라이언트 타임아웃 220초.
- **한계**(실측): "제공된 정보에만 근거" 프롬프트에도 14B 모델이 가끔 일반 지식을 섞음 →
  UI에 "AI 참고용 설명(진단 아님)" disclaimer 필수.
- **저장**: `analysis_results`에 판정 스냅샷 + AES-256-GCM 암호화 저장(`drug_ids`·`findings`·가이드 전부).
- **에뮬레이터 저장공간 부족**: 기본 AVD 데이터 파티션이 6GB로 이미 94% 차 있어
  APK 설치가 실패 — 이건 코드 문제가 아니라 이 PC의 에뮬레이터 설정 문제
  (`disk.dataPartition.size=8G`로 확장 + wipe-data로 해결, 다른 환경에서는
  발생하지 않을 수 있음)

---

## Flutter 앱

### 기술 스택
- Flutter + Dart
- image_picker (사진 촬영/선택, 웹 포함 전 플랫폼) — OCR은 서버(`POST /drugs/ocr`, Tesseract)에서 처리
- dio + flutter_secure_storage (HTTP 클라이언트, 토큰 저장)
- go_router (라우팅) · provider (상태 관리)
- firebase_core / firebase_messaging (FCM) + flutter_local_notifications (포그라운드 알림 표시 +
  2026-09-12부터 복약 시각 예약 알림) + timezone(`zonedSchedule`용, 직접 의존성으로 승격)

### 프로젝트 구조
```
front_app/lib/
├── core/
│   ├── api/            api_client.dart
│   ├── models/          auth_models, drug_models, medicine_box_models, analysis_models, user_models
│   ├── notifications/   fcm_service.dart, medication_reminder_service.dart(복약 알림 스케줄링)
│   └── storage/         token_storage.dart
└── features/
    ├── auth/            login_screen, register_screen, auth_provider
    ├── camera/          camera_screen, ocr_result_screen, camera_provider
    ├── home/            home_screen(177줄, 2026-09-12 865줄→분할)·home_provider
    │                    (배너: 병용금기·알레르기·연령금기=critical, 효능군중복·노인주의=caution)
    │                    widgets/(9개: strip_banner·floating_error·empty_state·medicine_card·
    │                    interaction_banner·finding_card·single_drug_risk_card·risk_badge·
    │                    ai_guide_section·reminder_edit_sheet)
    ├── profile/         profile_screen, profile_provider (건강정보·알레르기·출생연도 입력, 2026-09-12 신규)
    └── search/          search_screen, search_provider
```

### 약품 매칭 전략 (4단계)

| 순위 | 방식 | 설명 |
|---|---|---|
| 1순위 | prefix 검색 | `drug_key`에서 숫자 앞부분으로 prefix 조회, 정확 일치 우선 정렬 |
| 2순위 | 정확 drug_key 매칭 | 정규화 키 완전 일치 |
| 3순위 | ILIKE 폴백 | `item_name`/`simple_name` 부분 문자열 검색 (원본 검색어 그대로 — 정밀 매칭) |
| 4순위 (최후수단) | 성분명 기반 매칭 | 제형·용량을 제거한 성분명 후보로 `ingr_name` JSONB + `item_name` 재검색. 브랜드명이 성분명을 괄호 안에 숨겨 1~3순위가 실패하는 '성분명+제형' 입력(예: '와파린정') 대응 |

### 백엔드 연결
- 에뮬레이터: `http://10.0.2.2:8001/api/v1/`
- 실제 기기(같은 네트워크): `http://192.168.X.X:8001/api/v1/` (PC IP)
- 실제 기기(어디서든) / 릴리스 APK: `https://goodmedicine.tail9f1768.ts.net/api/v1/` (Tailscale Funnel, PC 켜져 있을 때)
- `BASE_URL`은 반드시 `/api/v1/` 접두사 + 끝 슬래시 포함해야 함 — 상세는 CLAUDE.md 참고 (실측으로 발견한 버그)

### 약품 설명 표시 (2026-09-17 확장)
- e약은요 7개 항목(효능·사용법·경고·주의사항·**상호작용**·부작용·보관법)이 이미 동기화돼
  있었는데 API 응답·화면 어디에도 노출되지 않고 있던 걸 발견 — 특히 상호작용
  (`intrc_qesitm`, 예: "복용 중 음주하지 마십시오")은 AI 가이드 프롬프트에만 흘러가고
  화면엔 한 번도 나온 적이 없었음
- 검색 결과(약 추가 전) 상세 시트: **효능만** 표시 — 빠르게 훑고 추가하는 단계라 축소
- 복약함 카드(등록 후) 펼침: **7개 항목 전체** 표시 — 데이터 있는 항목만, 없으면 섹션 자체가 안 뜸
  (플레이스홀더 문구도 제거)
- 데이터 자체는 전체 35,505건 중 4,884건(13.8%)에만 있음 — e약은요가 전체 품목을
  다루지 않는 구조적 한계, 코드로 해결 불가

---

## 시스템 커버리지 명세

### quick-check가 탐지하는 범위

판정은 **성분(ingredient) 단위**가 유일한 정식 경로. 구 품목쌍 테이블은 폐기됨.

- 복약함 약품을 `drug_ingredients`로 DUR 성분코드(`INGR_CODE`)에 해소(역인덱스) →
  `dur_ingredient_contraindications`(357건) / `dur_ingredient_effect_groups`(259건) 조회.
- **품목 테이블 폐기**: `drug_interactions`(331K행·227MB) / `drug_effect_groups`를
  폐기 전 DB 전수검증(일회성 스크립트) — 성분 경로가 그 탐지의 **100.0%**를 재현
  (rule gap 0). 성분코드 미해소 약(주로 외용제·희귀 품목)이 낀 **217쌍**만
  `residual_interactions`로 이관하고 두 테이블 DROP (마이그레이션 `0006`).
  **DB 311MB → 85MB.**
- `residual_interactions`는 성분 규칙이 없는 쌍만 담으므로 quick_check가 **항상**
  함께 조회·병합한다(217행 인덱스 조회, 조건부 스킵은 미탐 위험이라 제거). finding에
  `source`(`ingredient`|`residual`), 잔여 경로 탐지 시 `logger.warning`.
- 성분코드는 별도 API가 아니라 `DURPrdlstInfoService03`
  (`getUsjntTabooInfoList03`·`getEfcyDplctInfoList03`) 응답의 `INGR_CODE`/
  `MIXTURE_INGR_CODE`에서 캡처(`DURIrdntInfoService`는 폐기 —
  `NO_OPENAPI_SERVICE_ERROR`). 이 sweep은 이제 성분 테이블만 채운다.
- 해소율 보강: `sync.py dur_extra_codes`(임부/용량/투여기간 엔드포인트의
  `(ITEM_SEQ, INGR_CODE)` 매핑, 판정 미관여) + `sync.py dur_age_caution`(특정연령대금기·
  노인주의, 판정 규칙까지 채움) + `sync.py build_drug_ingredients`
  (`item_name` 괄호·`main_item_ingr` 이름 매칭). 현재 해소율 **61.5%**
  (미해소 38.5%는 DUR 상호작용이 아예 없는 약이 대부분 — 2026-09-17 실측: 아목시실린·
  헤파린·포도당 등 흔한 성분도 국내 DUR 룰 자체에 없는 경우가 많음, 코드로 해결 불가).
- **2026-09-17 매칭 개선 시도 3건 전부 실측에서 막힘**(상세는 개발일지 6장 F3~F5):
  HIRA 주성분코드 크로스워크(97.2%가 영문이라 한글 DUR 성분명과 매칭 0건),
  성분명 부분문자열 매칭 확장(223건 추가 해소되나 실제 오매칭 발견돼 폐기 —
  "우레아→히드록시우레아" 등), DUR 품목쌍 residual 실시간 캡처(엔드포인트가
  항상 INGR_CODE를 채워줘서 무효, 코드 되돌림). 실제로 통한 건 한 번도
  실행 안 됐던 `dur_extra_codes` 실행뿐(21,796→21,818건).
- **DUR 동기화 파이프라인 최적화(2026-09-17)**: numOfRows 100→500(DUR 6개
  엔드포인트 실측 검증) + `_find_or_create_drug_from_dur` 인메모리 캐시 추가.
  실측 3.7배(215초→58초). 796,842건 병용금기 전체 재동기화는 이 최적화 전
  7시간 9분 소요.
- **알레르기 충돌**(2026-09-12): `users.allergy_info`를 `drug_ingredients.ingr_kor`
  (+ 미해소 약은 `drugs.ingr_name` JSONB)와 대소문자·공백 무시 양방향 부분일치로 대조.
  DUR 데이터가 아니라 사용자 프로필 기반이라 `quick_check`가 `user_id`를 받아야 동작.

| 구분 | 탐지 여부 | 근거 |
|---|---|---|
| DUR 병용금기 (contraindicated → critical) | ✅ 탐지 | 성분쌍 `dur_ingredient_contraindications` (+ 미해소 약 residual 폴백) |
| DUR 효능군중복주의 (duplicate_effect_group → caution) | ✅ 탐지 | 성분 `dur_ingredient_effect_groups`(dur_seq 묶음) (+ residual 폴백) |
| 알레르기 성분 충돌 (allergy_conflict → critical) | ✅ 탐지 (2026-09-12) | 사용자 프로필 `allergy_info` 대 성분명 대조. 사용자가 알레르기 미등록이면 스킵 |
| 특정연령대금기 (age_taboo → critical) | ⚠️ 부분 탐지 (2026-09-12) | `dur_ingredient_age_caution`. 실측상 원본 API 응답의 나이 기준 중 숫자로 파싱되는 건 3.6%뿐이라, 나머지(범주어·언급없음)는 스킵됨. 사용자가 출생연도 미등록이면 전체 스킵 |
| 노인주의 (elderly_caution → caution) | ✅ 탐지 (2026-09-12) | `dur_ingredient_age_caution`, 고정 기준 만 65세 이상. 사용자가 출생연도 미등록이면 스킵 |
| DUR 병용주의(caution 등급)·용량주의·투여기간주의 | ❌ 미탐지 | 병용주의는 품목 단위 공개 API 미제공(`DURIrdntInfoService`도 폐기); 용량·투여기간주의는 API는 있으나 판정 규칙 미적재(성분코드 매핑만 수확 중) |
| DUR 미커버 조합의 AI 추정 위험 | ❌ 의도적 미제공 | ML 실험 결과 신뢰도 있는 예측 불가능함을 실측 확인, 서빙에서 제외 (`archive/ml/README.md`) |

> **주요 사실:** 와파린은 한국 DUR 병용금기 DB에 등록된 상호작용이 0건이다
> (성분 단위로 바꿔도 0건). 타이레놀(아세트아미노펜) × 와파린은 DUR 병용주의에도
> 없는 조합이며, 이는 시스템 오류가 아닌 공공데이터 커버리지의 한계다.

### 시연용 실제 탐지 조합

| 약품 A | 약품 B | 상호작용 | 등급 |
|---|---|---|---|
| 경동아스피린장용정 | 유한메토트렉세이트정 | 병용금기 (혈액학적 독성) | critical |
| 낙센에프정 (나프록센) | 케토롤락 계열 | 병용금기 (중증 위장관계 이상반응) | critical |
| 테라펜정 | 라사길린(MAO-B 억제제) | 병용금기 (세로토닌 증후군·고혈압위기) | critical |
| 크레스토정20mg | 크레스토정10mg | 효능군중복 (지질저하제) | caution |

### 발견했으나 아직 적재하지 않은 DUR API (`DURPrdlstInfoService03`, 별도 활용신청 불필요)

| API | 건수 | 비고 |
|---|---|---|
| `getCpctyAtentInfoList03` (용량주의) | 6,622건 | — |
| `getMdctnPdAtentInfoList03` (투여기간주의) | 633건 | — |

> `getSpcifyAgrdeTabooInfoList03`(특정연령대금기)·`getOdsnAtentInfoList03`(노인주의)는
> 2026-09-12 `sync.py dur_age_caution`으로 적재 완료 — 위 "quick-check가 탐지하는 범위" 참고.

---

## FCM 푸시

- Firebase 프로젝트 `good-medicine-app`, Android 패키지명 `com.goodmedicine.good_medicine`.
- `backend/firebase-service-account.json`, `front_app/android/app/google-services.json` (둘 다 gitignore).
- 복약함에 병용금기 약 추가 시 `fcm_service.py`가 발송. 포그라운드는 `flutter_local_notifications`로 표시.
- `users.fcm_token` 없으면 조용히 스킵(에러 아님).

## 배포 — 백엔드(API) 국내 PC · 프론트(웹) Vercel

절차: `docs/deploy-tailscale.md`(백엔드), `docs/deploy-web-vercel.md`(프론트).

**개인정보(회원 email/이름 + 암호화된 건강정보·복약정보)를 국외에서 저장·처리하지 않으려고
백엔드·DB는 전부 국내(내 PC).** 프론트엔 개인정보가 없어 Vercel(해외) 무방.

- **백엔드(API 전용, 웹 서빙 안 함)**
  - 개발: `docker compose up -d` — `docker-compose.override.yml` 자동 로드(소스 바인드마운트 — 재빌드는 불필요하지만 uvicorn `--reload`가 없어 코드 변경 후 `docker compose restart backend` 필요. pytest는 매번 새 프로세스라 재시작 없이 새 코드로 돈다).
  - 배포: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
    → override 배제 + `tailscale` 컨테이너 추가. 단일 스테이지 이미지라 빌드 ~30초.
  - 외부 노출: **`tailscale` 컨테이너**(userspace, 노드명 `goodmedicine`,
    `infrastructure/tailscale/serve.json` 로 `/`→`backend:8000` 프록시) → `https://goodmedicine.tail9f1768.ts.net/api/v1/`
    (고정 HTTPS). Docker Desktop 자동시작 + `restart: unless-stopped` 로 재부팅 후 터널까지 자동 복구.
    최초 1회 `docker logs drugtest-tailscale` 의 로그인 URL 승인(`tailscale_state` 볼륨에 영속).
  - 병용금기 판정 + **AI 가이드 풀 동작**(PC의 GPU). 비용 $0. PC 켜져 있을 때만.
- **프론트(웹)** — `front_app/**` push → GitHub Actions(`.github/workflows/deploy-web.yml`) →
  `flutter build web` → `vercel deploy --prebuilt --prod` → `https://goodmedicine-hpdice.vercel.app`.
  프론트↔API 가 다른 오리진이라 백엔드 `.env` 에 `CORS_ORIGINS` + `CORS_ORIGIN_REGEX` 필요.
- **APK** — `flutter build apk --release --dart-define=BASE_URL=https://goodmedicine.tail9f1768.ts.net/api/v1/`.
- 공공 의약품 DB: 출처 표시 조건으로 이용(공공누리 제1유형 가정 — 데이터셋별 확인).

### 향후 과제 — 한국 리전 상시 서버

PC 상시 가동 부담을 덜려면 한국 리전 상시 서버(Oracle Cloud Always Free 춘천/서울, 국내 VPS)로 이전 검토.
**조건: 개인정보 저장·처리가 국내에 머물 것.**

## 남은 작업

> 2026-09-30 운영 점검: Rate Limit 전역 공유·탈퇴 후 데이터 잔존/토큰 유효·백업 부재·동기화 조용한 누락을 수정.
> 자동화: DB 백업(매일 04:00, 복원 검증) · 공공데이터 월간 갱신(매월 1일 02:00, 품질 게이트) · CI 백엔드 테스트.
> 운영 절차와 남은 운영 과제는 **[operations.md](./operations.md)**.

| 작업 | 우선순위 | 비고 |
|---|---|---|
| 암호화 키 별도 보관 확인 | **높음** | `FIELD_ENCRYPTION_KEY`를 잃으면 백업이 있어도 건강정보 복구 불가. operations.md 3절 |
| 백업 외부 사본 (국내 매체) | 높음 | 지금 백업은 운영 데이터와 같은 D: 드라이브 |
| 용량 매칭 결함(P11)·동시 추가 중복(P12)·앱 부분 실패 무통지(O11) | 높음 | 2026-09-30 실측 발견. 학습 목적으로 직접 수정 예정(docs/study) — 시연 영상 전 반영 |
| 외부 감시 등록 (UptimeRobot 등에 `/health`) | 중간 | 헬스체크·CI·버전 고정·로그 상한·월간 갱신은 2026-09-30 완료. operations.md 7·8절 |
| 계정 복구(비밀번호 재설정)·개인정보 처리방침·APK 정식 서명 | 출시 전 | 현재 CI APK는 디버그 키 서명 |
| 한국 리전 상시 서버 탐색 | 낮음 | Oracle Cloud Free 서울/춘천, 국내 VPS. 향후 과제 |
| 시연 영상 녹화 | 중간 | 라이브 시연 백업. 사진 선택→OCR→복약함→quick-check→AI 가이드 전체 흐름. 2026-09-12 추가 기능(복약 알림·알레르기·연령대 규칙) 반영해 갱신 필요 |
| `gh` CLI 인증 | 낮음 | GitHub Release로 APK 배포 중인데 `gh auth login` 미완료 — 매번 웹에서 수동 업로드 중. 인증하면 자동화 가능 |
| 낱알 이미지 인식 | 폐기 (코드도 제거 완료) | 2026-09-12 검증: 필터(모양·색상·각인) 자체는 판별력 있음(각인 입력 시 90.4%가 후보 1건) 확인했으나, 이건 "사진 찍으면 인식"이 아니라 "약을 보고 직접 입력"하는 흐름이라 원래 기대한 사용성과 안 맞아 폐기 결정. 2026-09-17: 폐기 결정 후에도 DB 컬럼·동기화 코드가 남아있던 걸 발견해 마이그레이션 `0010`으로 완전히 제거 |
| 복약 알림 실기기 검증 | 낮음 | 백엔드·Flutter 단위 테스트·`flutter build apk --debug` 빌드는 통과했으나, 실기기/에뮬레이터에서 알림이 실제로 뜨는지·재부팅 후 유지되는지는 미검증 |
| DUR 용량주의·투여기간주의 적재 | 낮음 | 성분코드 매핑만 `sync.py dur_extra_codes`로 수확 중, 판정 규칙 미적재 |

---

## 주요 명령어

```cmd
# 서비스 시작/중지
docker compose up -d
docker compose down

# DB 현황 / 품질 검증
docker exec drugtest-backend-1 python sync.py status
docker exec drugtest-backend-1 python validate_db.py

# DB 완전 초기화 후 재구축 시: 잔여 폴백 복원 + 증상 태그 추출
docker exec drugtest-backend-1 python sync.py build_residual
docker exec drugtest-backend-1 python sync.py extract_risk_tags

# E2E 테스트 (별도 drugtest_test_db 사용, 운영 DB 무관. pytest는 이미지에 포함됨)
docker exec -e PYTHONPATH=/app -w /app drugtest-backend-1 python -m pytest tests/ -q

# 마이그레이션
docker exec -it drugtest-backend-1 alembic upgrade head

# 로컬 LLM (AI 가이드) — 최초 1회 모델 pull 필요, 이후엔 볼륨에 유지됨
docker compose up -d ollama
docker exec drugtest-ollama-1 ollama pull qwen2.5:14b-instruct
docker exec drugtest-ollama-1 ollama ps   # 로드 상태·GPU 사용률 확인

# 공공데이터 동기화
docker exec drugtest-backend-1 python sync.py overview
docker exec drugtest-backend-1 python sync.py dur_contraindications
docker exec drugtest-backend-1 python sync.py efcy_dplct
docker exec drugtest-backend-1 python sync.py fill_ingr

# ML 실험 재현 (연구용, 서빙에는 미포함)
poetry install --with ml
poetry run python ml/train_ddi_model.py
```

---

## GitHub

- 레포지토리: https://github.com/hpdice/good_medicine
- 브랜치: main
- 제외 항목: `.env`, `CLAUDE.md`, `.claude/`, `archive/ml/artifacts/`, `poetry.lock`
