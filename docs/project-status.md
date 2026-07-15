# 프로젝트 전체 현황

> 기준일: 2026-07-15 (19회차 반영)
> 상세 작업 서사(계획/문제/결론)는 [개발일지.md](./개발일지.md) 16~19회차 참고 — 이 문서는 "지금 상태" 스냅샷만 관리한다.

---

## 전체 진행률

| 영역 | 진행률 | 상태 |
|---|---|---|
| 백엔드 코드 | 100% | ✅ 완료 |
| 인프라 (Docker) | 100% | ✅ 완료 |
| DB 마이그레이션 | 100% | ✅ 완료 (0001~0003) |
| 데이터 적재 | 100% | ✅ 완료 + 품질 검증 통과 |
| Flutter 앱 프론트엔드 | 100% | ✅ 완료 (Phase 1~4 + 버그 수정) |
| 백엔드 E2E 테스트 | 핵심 플로우 완료 | ✅ 18개 테스트 통과 |
| FCM 푸시 알림 | 완료 | ✅ Firebase 프로젝트(`good-medicine-app`) 연동, 디버그 APK 빌드 검증 완료 |
| 배포 | 완료 (임시) | ✅ Cloudflare Tunnel로 로컬 PC 노출 — 아래 참고 |

---

## 데이터 적재 현황

```
drugs 전체            :  35,324건
├─ 효능정보(efcy)     :   4,725건  ← e약은요
├─ 성분JSONB(ingr)    :   7,628건  ← main_item_ingr 파싱
├─ 낱알식별(shape)    :   8,807건  ← 낱알식별 API
└─ 허가정보           :  35,296건  ← 허가일자 기준

drug_interactions     : 324,321건  ← DUR 병용금기 (양방향 중복 정리 완료)
drug_effect_groups    :   7,040건  ← DUR 효능군중복주의 (신규)
```

### DB 품질 검증 결과 (`validate_db.py`)

| 항목 | 결과 |
|---|---|
| 자기 자신 상호작용 | ✅ 0건 |
| 깨진 참조(drug_interactions) | ✅ 0건 |
| DUR 비정상 item_seq | ✅ 0건 |
| drug_key 중복 | ✅ 허용 174그룹 (수출용·개량신약 variants — 정상) |
| item_name 3자 미만 | ✅ 허용 3건 (API 원본 자체가 짧은 이름) |
| 허가일자 누락 | ✅ 3건 (API 원본 없음) |
| 분류명 누락 | ✅ 49건 (API 원본 없음) |
| simple_name 누락 | ✅ 0건 |

---

## 백엔드 구현 현황

### 인프라
- Docker Compose: PostgreSQL 16 + FastAPI (2개 컨테이너)
- 데이터 볼륨: `D:\drugTest\postgres_data` (bind mount)
- Swagger UI: `http://localhost:8000/api/docs` (DEBUG=true 환경에서만)

### API 엔드포인트 (15개)

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
| POST /drugs/match-names | OCR 결과 일괄 매칭 | JWT |
| GET /medicine-box | 복약 목록 조회 | JWT |
| POST /medicine-box | 복약 약품 추가 (중복 방지, 병용금기 시 FCM 발송) | JWT |
| PATCH /medicine-box/{id} | 복약 정보 수정 | JWT |
| DELETE /medicine-box/{id} | 복약 약품 삭제 | JWT |
| POST /analysis/quick-check | 병용금기·효능군중복 즉시 확인 | Rate Limit 60회/분 |

### 보안
- JWT Access Token 30분 + Single-use Refresh Token 7일 (모든 토큰에 `jti` 고유값 포함)
- AES-256-GCM 필드 암호화 (건강정보, 알레르기)
- Rate Limiting (login, quick-check)
- 보안 헤더 (X-Frame-Options, X-Content-Type-Options, HSTS)
- AuditLog (민감 작업 추적)

### 테스트
- `backend/tests/`: pytest + httpx(ASGITransport), 18개 E2E 테스트, 운영 DB와 분리된 `drugtest_test_db` 사용
- 커버리지: 인증(회원가입/로그인/리프레시 단일사용), 약품검색, 복약함(추가/중복거부/삭제), quick-check 3단계(critical/caution/safe)

---

## Flutter 앱

### 기술 스택
- Flutter + Dart
- camera + google_mlkit_text_recognition (온디바이스 OCR)
- dio + flutter_secure_storage (HTTP 클라이언트, 토큰 저장)
- go_router (라우팅) · provider (상태 관리)
- firebase_core / firebase_messaging (FCM, 네이티브 미연동 상태)

### 프로젝트 구조
```
flutter/lib/
├── core/
│   ├── api/            api_client.dart
│   ├── models/          auth_models, drug_models, medicine_box_models, analysis_models
│   ├── notifications/   fcm_service.dart
│   └── storage/         token_storage.dart
└── features/
    ├── auth/            login_screen, register_screen, auth_provider
    ├── camera/          camera_screen, ocr_result_screen, camera_provider
    ├── home/            home_screen, home_provider (3단계 위험 배너: critical/caution/safe)
    └── search/          search_screen, search_provider
```

### 약품 매칭 전략 (3단계)

| 순위 | 방식 | 설명 |
|---|---|---|
| 1순위 | prefix 검색 | `drug_key`에서 숫자 앞부분으로 prefix 조회, 정확 일치 우선 정렬 |
| 2순위 | 정확 drug_key 매칭 | 정규화 키 완전 일치 |
| 3순위 | ILIKE 폴백 | `item_name` 부분 문자열 검색 |

### 백엔드 연결
- 에뮬레이터: `http://10.0.2.2:8000`
- 실제 기기: `http://192.168.X.X:8000` (PC IP)

---

## 시스템 커버리지 명세

### quick-check가 탐지하는 범위

| 구분 | 탐지 여부 | 근거 |
|---|---|---|
| DUR 병용금기 (contraindicated → critical) | ✅ 탐지 | drug_interactions 324,321건, DB 직접조회 100% 정확 |
| DUR 효능군중복주의 (duplicate_effect_group → caution) | ✅ 탐지 | drug_effect_groups 7,040건, DB 직접조회 100% 정확 |
| DUR 병용주의(caution 등급의 별도 API) | ❌ 미탐지 | 공공데이터 API 미제공 |
| 특정연령대금기·노인주의·용량주의·투여기간주의 | ❌ 미탐지 | API는 존재 확인(아래 참고)했으나 미적재 — 사용자 연령 데이터 스키마 설계 필요 |
| DUR 미커버 조합의 AI 추정 위험 | ❌ 의도적 미제공 | ML 실험 결과 신뢰도 있는 예측 불가능함을 실측 확인, 서빙에서 제외 (`backend/ml/README.md`) |

> **주요 사실:** 와파린은 한국 DUR 병용금기 DB에 등록된 상호작용이 0건이다.
> 타이레놀(아세트아미노펜) × 와파린은 DUR 병용주의에도 없는 조합이며,
> 이는 시스템 오류가 아닌 공공데이터 커버리지의 한계다.

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
| `getSpcifyAgrdeTabooInfoList03` (특정연령대금기) | 2,659건 | 사용자 연령 데이터 필요 |
| `getCpctyAtentInfoList03` (용량주의) | 6,622건 | — |
| `getMdctnPdAtentInfoList03` (투여기간주의) | 633건 | — |
| `getOdsnAtentInfoList03` (노인주의) | 1,982건 | 사용자 연령 데이터 필요 |

---

## FCM (완료, 2026-07-15)

- Firebase 프로젝트: `good-medicine-app`
- Android 패키지명: `com.goodmedicine.good_medicine` (기존 `com.example.drugtest`에서 변경 — Play Store 등록 불가한 이름이라 Firebase 등록값에 맞춰 통일)
- `backend/firebase-service-account.json`, `flutter/android/app/google-services.json` 배치 완료 (둘 다 gitignore 대상)
- `flutter/android/`에 누락되어 있던 네이티브 파일(AndroidManifest.xml, MainActivity, 루트 Gradle 설정)을 `flutter create --platforms=android .`로 복구 — 카메라/인터넷 권한 재설정 포함
- `flutter build apk --debug` 빌드 성공 확인

## 배포 (임시, 2026-07-15)

**로컬 PC를 Cloudflare Tunnel로 외부에 노출하는 방식.** 별도 서버/클라우드 계정 없이 지금 떠 있는 `docker compose` 그대로 인터넷에 연결한다.

```
공개 주소: cloudflared 실행 시 콘솔에 출력되는 https://xxxx.trycloudflare.com
```

**중요한 제약:**
- 이 PC가 꺼지거나 절전모드로 들어가면 서비스가 중단된다
- Quick Tunnel(무료, 계정 불필요) 방식이라 `cloudflared` 프로세스를 재시작하면 주소가 바뀐다 — 프로세스를 계속 띄워두는 동안에만 주소가 유지됨
- `DEBUG=false`로 전환 완료 — `/api/docs` Swagger 문서는 공개되지 않음

**재시작 방법:**
```cmd
docker compose up -d
cloudflared tunnel --url http://localhost:8000
```
콘솔에 뜨는 새 `https://xxxx.trycloudflare.com` 주소를 Flutter `--dart-define=BASE_URL=`에 반영해야 한다 (주소가 바뀌므로).

**향후 안정적인 배포로 전환하려면**: Cloudflare 무료 계정 + Named Tunnel(주소 고정) 또는 Oracle Cloud 영구 무료 VM으로 이전 검토.

## 남은 작업

| 작업 | 우선순위 | 비고 |
|---|---|---|
| 배포 안정화 (고정 주소) | 중 | 현재 Quick Tunnel은 주소가 바뀜 — Named Tunnel/도메인 또는 VM 이전 검토 |
| Windows 시작 시 자동 실행 설정 | 낮음 | PC 재부팅 시 docker compose + cloudflared 수동 재시작 필요 |
| 특정연령대금기·노인주의 등 4개 API 적재 | 낮음 | 사용자 연령 수집 스키마·동의 흐름 설계 선행 필요 |
| 복합제 기반 안전 성분쌍(341개) 활용 | 낮음 | 규모가 작아 실질 효과 낮음, 향후 검토 |

---

## 주요 명령어

```cmd
# 서비스 시작/중지
docker compose up -d
docker compose down

# DB 현황 / 품질 검증
docker exec drugtest-backend-1 python sync.py status
docker exec drugtest-backend-1 python validate_db.py

# 중복 쌍 정리 (재실행 안전 — 이미 정리된 상태면 0건)
docker exec drugtest-backend-1 python sync.py dedupe_interactions

# E2E 테스트 (별도 drugtest_test_db 사용, 운영 DB 무관)
docker exec -u root drugtest-backend-1 pip install pytest pytest-asyncio pytest-cov httpx
docker exec -e PYTHONPATH=/app -w /app drugtest-backend-1 python -m pytest tests/ -v

# 마이그레이션
docker exec -it drugtest-backend-1 alembic upgrade head

# 공공데이터 동기화
docker exec drugtest-backend-1 python sync.py overview
docker exec drugtest-backend-1 python sync.py dur_contraindications
docker exec drugtest-backend-1 python sync.py efcy_dplct
docker exec drugtest-backend-1 python sync.py identification
docker exec drugtest-backend-1 python sync.py fill_ingr

# ML 실험 재현 (연구용, 서빙에는 미포함)
poetry install --with ml
poetry run python ml/train_ddi_model.py
```

---

## GitHub

- 레포지토리: https://github.com/hpdice/good_medicine
- 브랜치: main
- 제외 항목: `.env`, `CLAUDE.md`, `.claude/`, `backend/ml/artifacts/`, `poetry.lock`
