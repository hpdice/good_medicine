# 프로젝트 전체 현황

> 기준일: 2026-08-06 (21회차 반영)
> 상세 작업 서사(계획/문제/결론)는 [개발일지.md](./개발일지.md) 16~20회차 참고 — 이 문서는 "지금 상태" 스냅샷만 관리한다.

---

## 전체 진행률

| 영역 | 진행률 | 상태 |
|---|---|---|
| 백엔드 코드 | 100% | ✅ 완료 |
| 인프라 (Docker) | 100% | ✅ 완료 (postgres·backend·ollama 3개 컨테이너) |
| DB 마이그레이션 | 100% | ✅ 완료 (0001~0004) |
| 데이터 적재 | 100% | ✅ 완료 + 품질 검증 통과 |
| Flutter 앱 프론트엔드 | 100% | ✅ 완료 (Phase 1~4 + 버그 수정) |
| 백엔드 E2E 테스트 | 핵심 플로우 완료 | ✅ 27개 테스트 통과 (21회차에서 +5) |
| AI 대응 가이드 (로컬 LLM) | 완료 | ✅ Ollama + Qwen2.5 14B, 실제 GPU 추론 검증 완료 — 아래 참고 |
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
- Docker Compose: PostgreSQL 16 + FastAPI + Ollama (3개 컨테이너)
- 데이터 볼륨: `D:\drugTest\postgres_data` (bind mount), `ollama_data` (named volume, 모델 가중치)
- Swagger UI: `http://localhost:8000/api/docs` (DEBUG=true 환경에서만)

### API 엔드포인트 (16개)

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
| POST /analysis/guide | quick-check 판정 결과에 로컬 LLM 설명(AI 첨언) 추가 | Rate Limit 10회/분 |

### 보안
- JWT Access Token 30분 + Single-use Refresh Token 7일 (모든 토큰에 `jti` 고유값 포함)
- AES-256-GCM 필드 암호화 (건강정보, 알레르기, AI 가이드) — 복호화 실패 시 필드별 격리(계정 전체 500 방지)
- Rate Limiting (login, quick-check, analysis/guide)
- 보안 헤더 (X-Frame-Options, X-Content-Type-Options, HSTS)
- AuditLog (민감 작업 추적)
- 회원 탈퇴: email/hashed_password/name tombstone 처리 (개인정보 삭제 + 이메일 재사용 가능)

### 테스트
- `backend/tests/`: pytest + httpx(ASGITransport), 27개 E2E 테스트, 운영 DB와 분리된 `drugtest_test_db` 사용
- 커버리지: 인증(회원가입/로그인/리프레시 단일사용/72바이트 초과 비밀번호 거부/탈퇴 후 재가입), 약품검색, 약품명 매칭(성분명 폴백·정밀매칭 우선순위 회귀), 복약함(추가/중복거부/삭제), quick-check 3단계(critical/caution/safe), AI 가이드(생성·암호화저장·Ollama 다운 시 폴백, Ollama는 mock), 사용자 정보(건강정보 왕복/복호화 손상 격리)

### 실측 데이터 테스트 (2026-08-06)

실제 운영 DB(35,324건)로 quick-check·약품 매칭을 직접 실행해 검증.

- **위험도 분류 로직**: 정확 — DUR 데이터에 있는 병용금기/효능군중복은 critical/caution으로 정확히 분류됨을 실제 약품(아스피린+메토트렉세이트, 크레스토20/10mg, 타이레놀+펜잘 등 다른 브랜드의 동일성분 중복)으로 확인. 엣지케이스(중복 ID, 빈 목록, 존재하지 않는 UUID)도 정상 처리.
- **버그 발견 및 수정**: `match_names()`/`search()`가 "성분명+제형" 입력(예: '와파린정')에서 매칭 실패 — 브랜드명이 성분명을 괄호 안에 숨기는 경우(`쿠파린정2mg(와파린나트륨)`) 문자열이 끊겨 실패. 매칭 실패 시 `matched: null`을 반환할 뿐 에러가 없어 사용자 모르게 약이 등록에서 누락될 수 있었음(와파린처럼 상호작용이 중요한 약일수록 위험). `ingr_name` JSONB + `item_name` 성분 폴백 매칭(4순위, 최후수단)을 추가해 수정 — [drug_service.py](../backend/app/services/drug_service.py) 참고.
- **알려진 한계 재확인**: 제산제+시프로플록사신 등 병용주의(caution)급 상호작용은 여전히 미탐지 — 공공데이터 API 자체가 없어 코드로 해결 불가한 기존 한계(위 "시스템 커버리지 명세" 참고).

---

## AI 대응 가이드 — 로컬 LLM (완료, 2026-08-06)

위험도 **판정**은 그대로 규칙 기반(`AnalysisService.quick_check`, DUR 데이터 직접 조회)이고,
AI는 그 판정 결과를 사람이 읽을 설명으로 풀어쓰는 **보조("첨언") 역할만** 한다 — AI가
판정 자체를 바꾸지 않도록 구조적으로 분리했다.

- **모델**: Ollama + `qwen2.5:14b-instruct` (Q4 양자화, ~9GB) — 외부 API(Anthropic 등) 미사용,
  건강정보가 이 PC 밖으로 나가지 않음
- **인프라**: docker-compose `ollama` 서비스, GPU passthrough(`deploy.resources.reservations.devices`
  nvidia). `docker info`에 `nvidia` 런타임이 이미 등록돼 있었고 실측(`docker run --gpus all ... nvidia-smi`)으로
  RTX 4070(12GB) 인식 확인 후 컨테이너로 통합(네이티브 설치 대신)
- **검색(RAG) 설계**: 벡터 임베딩이 아니라 구조화 조회 — quick_check가 이미 찾아낸 `drug_id`로
  `DrugService.get_drugs_by_ids()`를 직접 재사용해 `efcy_qesitm`/`atpn_qesitm`/`se_qesitm` 텍스트를
  가져오고, 사용자의 복호화된 건강정보/알레르기도 컨텍스트에 포함. "이미 찾은 특정 finding을
  설명"하는 용도라 개방형 검색(임베딩·pgvector)이 불필요하다고 판단
- **안전장치**: Ollama가 응답하지 않아도(`OllamaUnavailableError`) 판정(risk_level)은 그대로
  반환되고 가이드만 안전한 폴백 문구로 대체 — 실제로 `docker compose stop ollama` 상태에서
  `/analysis/guide` 호출해 정상 폴백 확인
- **실측 성능** (RTX 4070 12GB, VRAM 12282MiB):
  | 상황 | 소요 시간 |
  |---|---|
  | 최초 로드(콜드스타트, 9GB를 GPU에 올림) | 87초~2분 30초 (편차 있음) |
  | 이후 요청(모델 로드된 상태) | ~10~15초 |

  `keep_alive: "30m"`로 매 요청마다 재로드되지 않게 함 (기본값 5분은 너무 짧음 — 실측으로
  드러난 문제라 코드에 반영).
  **실제로 겪은 버그**: 처음 `OLLAMA_TIMEOUT_SECONDS=90`으로 설정했는데, "전체 테스트
  진행" 지시로 실제 API를 다시 호출했을 때 콜드스타트가 91.8초 걸려 90초 타임아웃에
  걸리고 폴백으로 빠지는 걸 직접 목격함 — 초기 실측(2분 30초)보다 짧게 나온 경우라도
  87~91초대는 90초 경계에 걸릴 만큼 아슬아슬했다. `OLLAMA_TIMEOUT_SECONDS=200`으로
  올려 재현 확인(같은 조합으로 워밍 상태에서 10.8초 만에 정상 생성 확인).
- **실측으로 확인한 한계**: 시스템 프롬프트로 "제공된 정보에만 근거하라, 없는 사실을
  추측하지 마라"를 강하게 지시해도, 실제 critical 조합(아스피린+메토트렉세이트) 테스트에서
  모델이 DB에 없는 내용(메토트렉세이트의 류마티스 치료 용도 — `efcy_qesitm`이 비어있는
  약품이었음에도)을 일반 지식으로 채워 넣는 사례를 확인함. 내용 자체는 사실이었지만
  "이 데이터 안에서만" 원칙이 프롬프트만으로 100% 보장되지는 않는다는 뜻 — UI에서
  "AI 참고용 설명(진단 아님)"이라는 disclaimer를 반드시 노출해야 하는 이유
- **저장**: `analysis_results` 테이블(0004 마이그레이션)에 판정 스냅샷 + AES-256-GCM
  암호화된 가이드 텍스트 저장 — 이력 조회·월간 리포트 등 향후 기능 대비
- **Flutter 연동**: 홈 화면 상호작용 상세 바텀시트(`_showFindings`)에 "AI 설명 보기" 버튼
  추가 — 자동 호출이 아니라 탭했을 때만 호출(비용·지연 때문). 타임아웃은 백엔드
  `OLLAMA_TIMEOUT_SECONDS`(200초)보다 항상 여유있게 220초로 설정.
  **Android 에뮬레이터(Pixel 3a)에서 실제 회원가입→로그인→약품 추가→위험배너 탭→
  AI 설명 생성까지 전체 플로우 실기기 검증 완료** — 스크린샷으로 각 단계 확인함

### 실기기 검증 중 발견한 버그 3건 (2026-08-06)

- **Android 빌드 실패**: `flutter_local_notifications`가 core library desugaring을
  요구하는데 `android/app/build.gradle.kts`에 설정이 없어 `assembleDebug` 자체가
  실패했음 — `isCoreLibraryDesugaringEnabled = true` + `desugar_jdk_libs:2.1.4`
  의존성 추가로 수정. (이 버그는 이번 세션 이전부터 있었을 것 — 실제로 emulator에서
  빌드해본 적이 없었다는 뜻)
- **Cleartext HTTP 차단**: `AndroidManifest.xml`에 `usesCleartextTraffic` 설정이
  없어 Android 기본 정책상 `http://10.0.2.2:8000`(에뮬레이터용 개발 서버) 접속이
  전부 막혀 있었음 — CLAUDE.md에 문서화된 에뮬레이터 개발 흐름 자체가 실제로는
  한 번도 성공한 적 없었다는 뜻. `android:usesCleartextTraffic="true"` 추가로 해결
  (HTTPS인 운영 배포에는 영향 없음)
- **에뮬레이터 저장공간 부족**: 기본 AVD 데이터 파티션이 6GB로 이미 94% 차 있어
  APK 설치가 실패 — 이건 코드 문제가 아니라 이 PC의 에뮬레이터 설정 문제
  (`disk.dataPartition.size=8G`로 확장 + wipe-data로 해결, 다른 환경에서는
  발생하지 않을 수 있음)

---

## Flutter 앱

### 기술 스택
- Flutter + Dart
- camera + google_mlkit_text_recognition (온디바이스 OCR)
- dio + flutter_secure_storage (HTTP 클라이언트, 토큰 저장)
- go_router (라우팅) · provider (상태 관리)
- firebase_core / firebase_messaging (FCM) + flutter_local_notifications (포그라운드 알림 표시)

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

### 약품 매칭 전략 (4단계, 2026-08-06 성분명 폴백 추가)

| 순위 | 방식 | 설명 |
|---|---|---|
| 1순위 | prefix 검색 | `drug_key`에서 숫자 앞부분으로 prefix 조회, 정확 일치 우선 정렬 |
| 2순위 | 정확 drug_key 매칭 | 정규화 키 완전 일치 |
| 3순위 | ILIKE 폴백 | `item_name`/`simple_name` 부분 문자열 검색 (원본 검색어 그대로 — 정밀 매칭) |
| 4순위 (최후수단) | 성분명 기반 매칭 | 제형·용량을 제거한 성분명 후보로 `ingr_name` JSONB + `item_name` 재검색. 브랜드명이 성분명을 괄호 안에 숨겨 1~3순위가 실패하는 '성분명+제형' 입력(예: '와파린정') 대응 |

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
| DUR 미커버 조합의 AI 추정 위험 | ❌ 의도적 미제공 | ML 실험 결과 신뢰도 있는 예측 불가능함을 실측 확인, 서빙에서 제외 (`archive/ml/README.md`) |

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
- (2026-08-03) 포그라운드 알림 미표시 버그 수정: `flutter_local_notifications` 추가, `onMessage`/`onBackgroundMessage` 핸들러 연결, `POST_NOTIFICATIONS`(Android 13+) 권한 추가 — 상세는 [개발일지.md](./개발일지.md) 20회차 참고

## 알려진 이슈

| 이슈 | 영향 | 비고 |
|---|---|---|
| 로컬 Docker 호스트 포트 8000 충돌 | `docker compose up -d`로 drugtest-backend 정식 기동 불가 | 이 PC에 떠 있는 다른 프로젝트 컨테이너(`health-api`)가 8000을 선점 중. `drugtest-backend-1`이 이 때문에 계속 `Exited` 상태. 정식 기동하려면 `health-api`를 내릴지 결정 필요 — 코드 검증만 필요하면 `docker compose run --rm -d --name <임시이름> backend ...`로 호스트 포트 노출 없이 우회 가능 |

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
| 배포 안정화 (고정 주소) | 높음 | 현재 Quick Tunnel은 주소가 바뀜 — Named Tunnel/도메인 검토. **AI 대응 가이드가 이 PC의 GPU(RTX 4070)에 의존적이라, GPU 없는 VM(예: Oracle Cloud 무료 티어)으로 이전하면 AI 가이드 기능과 충돌함 — 배포 아키텍처를 먼저 결정해야 함** (계속 이 PC에서 서빙 / GPU 클라우드로 이전 / AI 가이드만 분리) |
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

# 로컬 LLM (AI 가이드) — 최초 1회 모델 pull 필요, 이후엔 볼륨에 유지됨
docker compose up -d ollama
docker exec drugtest-ollama-1 ollama pull qwen2.5:14b-instruct
docker exec drugtest-ollama-1 ollama ps   # 로드 상태·GPU 사용률 확인

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
- 제외 항목: `.env`, `CLAUDE.md`, `.claude/`, `archive/ml/artifacts/`, `poetry.lock`
