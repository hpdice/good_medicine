# 프로젝트 전체 현황

> 기준일: 2026-06-09 (14회차 반영)

---

## 전체 진행률

| 영역 | 진행률 | 상태 |
|---|---|---|
| 백엔드 코드 | 100% | ✅ 완료 |
| 인프라 (Docker) | 100% | ✅ 완료 |
| DB 마이그레이션 | 100% | ✅ 완료 |
| 데이터 적재 | 100% | ✅ 완료 + 품질 검증 통과 |
| Flutter 앱 프론트엔드 | 100% | ✅ 완료 (Phase 1~4) |
| 백엔드 E2E 테스트 | 0% | ⬜ 미시작 |
| 배포 | 0% | ⬜ 미시작 |

---

## 데이터 적재 현황 (완료)

```
drugs 전체          :  35,299건
├─ 효능정보(efcy)   :   4,725건  ← e약은요
├─ 성분JSONB(ingr)  :   7,628건  ← main_item_ingr 파싱
├─ 낱알식별(shape)  :   8,807건  ← 낱알식별 API
└─ 허가정보         :  35,296건  ← 허가일자 기준

drug_interactions   : 648,642건  ← DUR 병용금기
고유 약품 쌍        : 324,321개
```

### DB 품질 검증 결과

| 항목 | 결과 |
|---|---|
| 자기 자신 상호작용 | ✅ 0건 |
| 깨진 참조(drug_interactions) | ✅ 0건 |
| DUR 비정상 item_seq | ✅ 0건 |
| drug_key 중복 | ✅ 허용 166그룹 (수출용·개량신약 variants — 정상) |
| item_name 3자 미만 | ✅ 허용 3건 (API 원본 자체가 짧은 이름) |
| 허가일자 누락 | ✅ 3건 (API 원본 없음) |
| 분류명 누락 | ✅ 49건 (API 원본 없음) |
| simple_name 누락 | ✅ 0건 |

---

## 백엔드 구현 현황 (완료)

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
| POST /medicine-box | 복약 약품 추가 (중복 방지) | JWT |
| PATCH /medicine-box/{id} | 복약 정보 수정 | JWT |
| DELETE /medicine-box/{id} | 복약 약품 삭제 | JWT |
| POST /analysis/quick-check | 병용금기 즉시 확인 | Rate Limit 60회/분 |

### 보안
- JWT Access Token 30분 + Single-use Refresh Token 7일
- AES-256-GCM 필드 암호화 (건강정보, 알레르기)
- Rate Limiting (login, quick-check)
- 보안 헤더 (X-Frame-Options, X-Content-Type-Options, HSTS)
- AuditLog (민감 작업 추적)

---

## Flutter 앱 (완료)

### 기술 스택
- Flutter + Dart
- camera + google_mlkit_text_recognition (온디바이스 OCR)
- dio + flutter_secure_storage (HTTP 클라이언트, 토큰 저장)
- go_router (라우팅)
- provider (상태 관리)

### 프로젝트 구조
```
flutter/lib/
├── core/
│   ├── api/          api_client.dart
│   ├── models/       auth_models, drug_models, medicine_box_models, analysis_models
│   └── storage/      token_storage.dart
└── features/
    ├── auth/         login_screen, register_screen, auth_provider
    ├── camera/       camera_screen, ocr_result_screen, camera_provider
    ├── home/         home_screen, home_provider
    └── search/       search_screen, search_provider
```

### 완료 현황

| Phase | 내용 | 상태 |
|---|---|---|
| Phase 1 | 로그인·회원가입 + TokenStorage + dio Interceptor | ✅ 완료 |
| Phase 2 | 약품 검색 + Medicine Box + 병용금기 확인 (quick-check) | ✅ 완료 |
| Phase 3 | Camera 촬영 + ML Kit OCR + /drugs/match-names 매칭 | ✅ 완료 |
| Phase 4 | OCR 정확도·UX 개선, 약품명 정규화 강화, 홈 화면 추가중 배너 | ✅ 완료 |

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
| DUR 병용금기 (contraindicated) | ✅ 탐지 | drug_interactions 648,642건 |
| DUR 병용주의 (caution) | ❌ 미탐지 | 공공데이터 API 미제공 — 품목 단위 병용주의 엔드포인트 없음 |
| 같은 계열 중복 복용 (트립탄×트립탄 등) | ❌ 미탐지 | 2차 분석 미구현 |
| 성분 기반 위험 추론 | ❌ 미탐지 | 2차 분석 미구현 |

> **주요 사실:** 와파린은 한국 DUR 병용금기 DB에 등록된 상호작용이 0건이다.
> 타이레놀(아세트아미노펜) × 와파린은 DUR 병용주의에도 없는 조합이며,
> 이는 시스템 오류가 아닌 공공데이터 커버리지의 한계다.

### 시연용 실제 탐지 조합

| 약품 A | 약품 B | 상호작용 | 기전 |
|---|---|---|---|
| 경동아스피린장용정 | 유한메토트렉세이트정 | ✅ 병용금기 | 혈액학적 독성 |
| 낙센에프정 (나프록센) | 케토롤락 계열 | ✅ 병용금기 | 중증 위장관계 이상반응 |
| 테라펜정 | 라사길린(MAO-B 억제제) | ✅ 병용금기 | 세로토닌 증후군·고혈압위기 |

---

## 남은 작업

| 작업 | 우선순위 | 비고 |
|---|---|---|
| FCM 푸시 알림 설정 | 중 | fcm_token 컬럼 이미 존재 |
| 배포 환경 구성 | 낮음 | — |
| drug_interactions 중복 쌍 정리 | 낮음 | 동일 약품 쌍 2건씩 존재, quick-check 결과에 영향 없음 |
| 2차 분석 (성분 기반 위험 추론) | 낮음 | 트립탄×트립탄 등 같은 계열 중복 탐지 |

---

## 주요 명령어

```cmd
# 서비스 시작/중지
docker compose up -d
docker compose down

# DB 현황
docker exec drugtest-backend-1 python sync.py status

# DB 품질 검증
docker exec drugtest-backend-1 python validate_db.py

# 마이그레이션
docker exec -it drugtest-backend-1 alembic upgrade head

# 공공데이터 동기화
docker exec drugtest-backend-1 python sync.py overview
docker exec drugtest-backend-1 python sync.py dur_contraindications
docker exec drugtest-backend-1 python sync.py identification
docker exec drugtest-backend-1 python sync.py fill_ingr
```

---

## GitHub

- 레포지토리: https://github.com/hpdice/good_medicine
- 브랜치: main
- 제외 항목: .env, CLAUDE.md, docs/, .claude/
