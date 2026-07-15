# 프로젝트 전체 현황

> 기준일: 2026-06-09 (15회차 반영)

---

## 전체 진행률

| 영역 | 진행률 | 상태 |
|---|---|---|
| 백엔드 코드 | 100% | ✅ 완료 |
| 인프라 (Docker) | 100% | ✅ 완료 |
| DB 마이그레이션 | 100% | ✅ 완료 |
| 데이터 적재 | 100% | ✅ 완료 + 품질 검증 통과 |
| Flutter 앱 프론트엔드 | 100% | ✅ 완료 (Phase 1~4 + 버그 수정) |
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
| FCM 푸시 알림 설정 | 중 | 백엔드(firebase-admin, fcm_service, medicine_box 병용금기 발생 시 발송) + Flutter Dart 등록 코드 구현 완료. **미완료:** Firebase 프로젝트 생성 + `backend/firebase-service-account.json` + Android `google-services.json`/Gradle 플러그인 연동 (네이티브 설정은 의도적으로 보류 — 아래 참고) |
| 배포 환경 구성 | 낮음 | — |
| ~~drug_interactions 중복 쌍 정리~~ | 완료 | 2026-07-15 — 아래 참고 |
| ~~2차 분석 (효능군중복·ML 추정)~~ | 완료 | 2026-07-15 — 아래 참고 |

### drug_interactions 중복 쌍 정리 + 로직 리뷰 메모 (2026-07-15)

- **원인 확정**: `public_data_service.py`의 DUR 병용금기 적재 코드가 (A,B)·(B,A) 양방향을 모두 저장했지만, 모든 조회 쪽(`get_interactions_for_pair`의 OR, `get_interactions_for_drug_list`의 `in()` 교집합)이 이미 방향을 가리지 않아 완전히 불필요한 중복이었음. `648,642건 = 324,321쌍 × 2`로 정확히 일치해 확인됨.
- **데이터 정리**: `sync.py dedupe_interactions` 신규 명령으로 정리 → 324,321건. quick-check로 실제 재현(경동아스피린×유한메토트렉세이트)해서 `findings` 중복이 사라졌음을 확인.
- **재발 방지**: ①`_upsert_dur_contraindication`이 이제 한 쪽만 저장 + 존재 확인도 양방향 OR로 변경 ②알림 `0002_unordered_pair_unique` 마이그레이션으로 `LEAST/GREATEST(drug1_id,drug2_id)+interaction_type` 유니크 인덱스 추가 — DB 레벨에서 재발 원천 차단.
- **코드 리뷰로 발견한 버그**: FCM 알림 로직(`_notify_if_contraindicated`)에서 예외 발생 시 이미 성공한 약품 추가(`add_manual`) 자체가 500으로 실패 처리되는 문제 발견 → try/except로 격리해 알림 실패가 주 기능에 영향 없도록 수정. Flutter `FcmService`가 홈 탭 재진입마다 토큰을 중복 등록하는 비효율도 발견해 수정.

### ML 병용금기 예측 모델 + 효능군중복 + 하이브리드 quick-check (2026-07-15)

**1) ML 실험** — `backend/ml/train_ddi_model.py`: 그래프 임베딩(TruncatedSVD) + 계열/성분 특징 + HistGradientBoostingClassifier. 상세 방법론은 `backend/ml/README.md` 참고. **핵심 결론**: "이미 알려진 위험 계열의 새 제품 확장"은 AUROC 0.9995로 정확하지만, "DUR이 전혀 다루지 않은 새로운 계열 조합 발견"은 AUROC 0.4847(사실상 무작위)로 현재 DB 데이터만으로는 한계가 명확함.

**2) 진짜 음성(안전) 라벨 탐색** — 공공데이터에 "안전한 조합" 데이터셋은 없음을 재확인. 대신 복합제(성분 2개 이상 승인 제품, 2,409개)에서 co-formulated 성분쌍 343개를 추출 → DUR 위험쌍과 대조해 충돌 2건만 확인 → 341개는 검증된 안전 후보(규모가 작아 이번 학습에는 미반영, 향후 과제).

**3) 뜻밖의 발견 — 실제 DUR API 5개 추가 확인**: 14회차 조사에서 오퍼레이션 이름을 잘못 추측해 놓쳤던 것으로, 이미 승인된 `DURPrdlstInfoService03` 서비스 안에 포함되어 있었음(같은 serviceKey로 정상 응답 확인, 별도 활용신청 불필요).

| API | 건수 | 상태 |
|---|---|---|
| `getEfcyDplctInfoList03` (효능군중복주의) | 7,044건 | ✅ 적재 완료, quick-check 연동 완료 |
| `getSpcifyAgrdeTabooInfoList03` (특정연령대금기) | 2,659건 | ⬜ 미적재 (사용자 연령 데이터 필요) |
| `getCpctyAtentInfoList03` (용량주의) | 6,622건 | ⬜ 미적재 |
| `getMdctnPdAtentInfoList03` (투여기간주의) | 633건 | ⬜ 미적재 |
| `getOdsnAtentInfoList03` (노인주의) | 1,982건 | ⬜ 미적재 (사용자 연령 데이터 필요) |

**4) 효능군중복주의 구현**: `drug_effect_groups` 테이블 신설(마이그레이션 `0003_effect_groups`) — 약품이 속한 DUR 효능군(dur_seq) 멤버십을 저장. `sync.py efcy_dplct`로 적재. 병용금기와 달리 절대 금기가 아닌 **'주의'** 등급으로 명확히 분리.

**5) 하이브리드 quick-check 시도 → 철회, 규칙 기반 3단계로 확정**: 처음엔 병용금기(critical)/효능군중복(caution) 확정 판정 + 미커버 쌍만 ML 추정(estimated, 확률 0.85+)을 붙이는 하이브리드로 구현했으나, 실측 검증 결과 **ML이 실질 가치가 전혀 없음**을 확인하고 제거했다. 미커버 쌍 30만 개 샘플에서 0.85+ 신뢰도로 플래그된 194개(0.065%)는 **100%가 `class_pair_density > 0`인 쌍**(SQL 한 줄로 이미 알 수 있는 "이미 위험 계열로 알려진 조합의 새 제품")이었고, ML만 찾아낸 새로운 발견은 0개였다. 심지어 같은 단순 SQL 규칙 하나만으로는 44,593개를 잡아내는데 모델은 그 중 194개(0.4%)만 보수적으로 추렸을 뿐 — 딥러닝으로 바꿔도 동일한 한계(그래프에 완전히 고립된 두 계열 사이엔 애초에 학습할 구조적 신호가 없음, 화학구조 데이터가 없으면 근본적으로 불가)임을 확인. 결론: **`analysis_service.py`는 규칙 기반 3단계만 유지** — ①병용금기(확정, DB 직접조회) → `critical` ②효능군중복(확정, DB 직접조회) → `caution` ③그 외 → `safe`. `ddi_ml_service.py`/`app/ml/` 삭제, `scikit-learn`/`scipy`/`numpy`/`joblib`은 다시 연구 전용 `ml` poetry 그룹으로 분리(프로덕션 이미지에서 제외). ML 학습·평가 스크립트와 이 실험 기록은 `backend/ml/`에 연구 자료로 남겨둠(`ml/README.md` "왜 서빙에서 뺐는가" 참고).

**검증**: 크레스토정20mg×10mg(같은 성분, 다른 용량) → `duplicate_effect_group`/`caution` 정상 감지. `ddi_ml_service.is_available()` 컨테이너 재빌드 후 정상 로드 확인. OpenAPI 스키마 생성(`/openapi.json` 200) 및 `flutter analyze` 클린 확인.

### FCM 구현 메모 (2026-07-15)

- 작업 시작 전 `flutter analyze`에서 컴파일 에러 발견: 직전 커밋(2e8b4a7)이 `app.dart`의 `_MainShell`을 StatefulWidget→StatelessWidget으로 리팩터링하면서 이제 존재하지 않는 `_selectedIndex`/`setState`를 호출하는 코드가 남아 앱이 빌드되지 않는 상태였음. FCM 작업 전 우선 수정함 (죽은 `setState` 호출 2곳 제거).
- 백엔드: `app/services/fcm_service.py` (firebase-admin 6.x, `FIREBASE_CREDENTIALS_JSON` 미설정 시 전체 기능 무동작으로 안전하게 스킵) + `medicine_box_service.add_manual()`에서 신규 약품이 기존 복약함과 병용금기일 때 푸시 발송하도록 연동. `pyproject.toml`/`poetry.lock` 갱신 완료, `PYTHONPATH=.` 기반 로컬 import 확인 통과 (Docker Desktop 미실행으로 컨테이너 재빌드 검증은 못함 — 다음 `docker compose up -d --build` 시 확인 필요).
- Flutter: `firebase_core`/`firebase_messaging` 패키지 추가 + `lib/core/notifications/fcm_service.dart` (토큰 조회·갱신·백엔드 등록), `home_screen.dart`에서 로그인 후/앱 재시작 시 1회 호출. `flutter analyze` 통과.
- **의도적으로 보류한 부분:** Android `build.gradle`에 `com.google.gms.google-services` 플러그인 적용 안 함 — `google-services.json` 없이 적용하면 즉시 빌드 실패하므로, Firebase 프로젝트가 준비될 때까지 미룸. 지금 상태로는 Firebase 미설정이어도 앱이 정상 빌드·실행되며 푸시만 조용히 비활성화됨.
- **재개 시 필요한 것:** (1) Firebase 콘솔에서 프로젝트 생성 → 서비스 계정 키(JSON) 발급 → `backend/firebase-service-account.json`으로 저장 + `.env`에 `FIREBASE_CREDENTIALS_JSON=firebase-service-account.json` 설정, (2) Android 앱 등록 → `google-services.json`을 `flutter/android/app/`에 저장 → `flutter/android/build.gradle.kts`(classpath)와 `flutter/android/app/build.gradle.kts`(plugin apply)에 google-services 플러그인 추가.

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
