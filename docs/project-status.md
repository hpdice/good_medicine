# 프로젝트 현황

> 현재 상태 스냅샷. 운영 절차는 [operations.md](./operations.md).
>
> 백엔드(API)+Ollama는 `docker compose` + Tailscale Funnel, 프론트 웹은 Vercel, APK는 GitHub Releases로 배포한다.

---

## 구성 현황

| 영역 | 상태 |
|---|---|
| 백엔드 | FastAPI 17개 엔드포인트 + 헬스체크. 공공데이터 동기화(`public_data_service/`)는 책임별 파일로 분할 |
| 인프라 | Docker Compose: postgres · backend · ollama (배포 overlay는 tailscale 컨테이너 추가). backend 호스트 포트 8001 |
| DB | Alembic 마이그레이션 — 성분 단위 판정 테이블, 복약정보 필드 암호화, 출생연도·연령대 규칙, 임부금기, 약 상세 보강 시각 |
| 데이터 | 공공데이터 적재 + 품질 검증(`validate_db.py`) 통과 |
| Flutter 앱 | 웹·Android. 로그인·복약함·약 검색·사진 OCR·위험도 배너·AI 설명·복약 시간 알림·내 정보(건강정보·알레르기·출생연도·임신 여부) |
| 테스트 | pytest + httpx, 운영 DB와 분리된 테스트 DB, Ollama mock. push·PR 시 GitHub Actions에서 린트·타입 검사·pytest 실행 |
| AI 설명 | Ollama + Qwen2.5 14B (GPU, 외부 API 미사용) |
| FCM 푸시 | Firebase 연동. 알림에는 약 이름·ID를 싣지 않는다 |
| APK 배포 | GitHub Releases — `v*` 태그 push 시 CI가 빌드. 최신 v0.4.0(복용량 입력·하루 용량 초과 화면 포함) |

---

## 데이터 적재 현황

```
drugs 전체                          : 35,869건
├─ 효능정보(efcy)                   : 약 4,900건 ← e약은요 + 약 추가 시 허가정보로 보강
└─ 성분 JSONB(ingr_name)            : 약 7,600건 ← main_item_ingr 파싱

drug_ingredients                    : 29,240건  ← 성분 단위 판정 조인 브리지 (drugs의 65.6%인 23,538건 해소)
└─ amount_mg(정·캡슐 1개당 함량)    : 15,539개 약 ← 심평원 주성분 (용량주의용)
dur_ingredient_contraindications    :  1,251건  ← DUR 병용금기 (성분쌍, 품목정보 357 + 성분정보 894)
dur_ingredient_effect_groups        :    377건  ← DUR 효능군중복주의 (효능군 + 계열로 묶음)
dur_ingredient_age_caution          :    290건  ← 특정연령대금기 185 + 노인주의 105
dur_ingredient_dose_caution         :    619건  ← DUR 용량주의 (하루 최대 용량, 판정 사용 591)
dur_item_pregnancy_taboo            : 15,683행  ← 임부금기 (품목 단위)
residual_interactions               :    217건  ← 성분코드 미해소 약이 낀 잔여 폴백 (시드로 고정)
dur_ingredient_master               :  1,499개  ← DUR 성분코드 ↔ 한글·영문명 (판정 미사용)
hira_item_gen_codes / hira_gen_ingredients : 52,995 / 59,631행 ← 심평원 약가마스터
```

성분코드는 DUR 품목정보(`DURPrdlstInfoService03`)의 `INGR_CODE`/`MIXTURE_INGR_CODE`에서 가져온다. 해소율 보강은
`dur_age_caution` · `dur_pregnancy` · `build_drug_ingredients`(품목명 괄호·주성분 이름 매칭) ·
`build_drug_ingredients_hira`(심평원 영문 성분명 ↔ DUR 영문명 완전 일치 — 일부 성분만 이어진 복합제에는 빠진 성분을 보탠다)가 맡는다.
한글 이름 매칭은 완전 일치·접두 일치만 쓰고, 접두가 맞아도 남는 부분이 다른 성분 이름이면 맺지 않는다('포비돈' ≠ 포비돈요오드). 판정 규칙은 DUR 성분정보
(`DURIrdntInfoService03`)로 보강한다 — 품목정보는 성분 규칙의 일부만 품목 쌍으로 풀어 준다. 해소되지 않는 약은 대부분
DUR에 성분 자체가 없는 약(비타민·한약 엑스 등)이다.

### DB 품질 검증 (`validate_db.py`)

| 항목 | 결과 |
|---|---|
| 자기 자신 상호작용 | 0건 |
| 깨진 참조(residual_interactions·drug_ingredients) | 0건 |
| DUR 비정상 item_seq | 0건 |
| drug_key 중복 | 허용 184그룹 (수출용·개량신약 variants) |
| item_name 3자 미만 | 허용 3건 (API 원본이 짧은 이름) |
| 허가일자·분류명 누락 | 허용 (API 원본에 없음) |

---

## 백엔드

### API 엔드포인트 (17개)

| 엔드포인트 | 기능 | 보안 |
|---|---|---|
| POST /auth/register | 회원가입 | — |
| POST /auth/login | 로그인 | IP 20회/15분 + 계정별 실패 5회/15분 |
| POST /auth/refresh | 토큰 갱신 | Single-use RT |
| POST /auth/logout | 로그아웃 | Refresh Token으로 식별 |
| GET /users/me | 내 정보 조회 | JWT |
| PATCH /users/me | 내 정보 수정 | JWT |
| DELETE /users/me | 회원 탈퇴 | JWT |
| GET /drugs?q= | 약품 검색 (pg_trgm 퍼지) | JWT |
| GET /drugs/{id} | 약품 상세 조회 (비어 있는 항목은 허가정보로 보강) | JWT |
| POST /drugs/ocr | 처방전 사진 업로드 → 서버 OCR(Tesseract) → 후보 추출 → 매칭 (이미지 미저장) | JWT · Rate Limit 20회/분 |
| POST /drugs/match-names | 텍스트 약품명 후보 일괄 매칭 | JWT |
| GET /medicine-box | 복약 목록 조회 | JWT |
| POST /medicine-box | 복약 약품 추가 (중복 방지, 병용금기 시 FCM 발송) | JWT |
| PATCH /medicine-box/{id} | 복약 정보 수정 | JWT |
| DELETE /medicine-box/{id} | 복약 약품 삭제 | JWT |
| POST /analysis/quick-check | 병용금기·중복·알레르기·연령대·임부금기 즉시 판정 | JWT · Rate Limit 60회/분 |
| POST /analysis/guide | 판정 결과에 로컬 LLM 설명 추가 | JWT · Rate Limit 10회/분 |

### 보안
- JWT Access Token 30분 + Single-use Refresh Token 7일 (모든 토큰에 `jti` 포함)
- AES-256-GCM 필드 암호화 — 건강정보·알레르기·출생연도·임신 여부, 복약함 전체 payload(약 ID·용량·복용시각·알림 설정·메모), 분석 이력. 복호화 실패는 필드별로 격리
- Rate Limiting — 로그인은 IP 단위(성공 포함)와 이메일별 실패 횟수 두 겹, quick-check·guide·OCR은 로그인 사용자 단위
- 보안 헤더(X-Frame-Options, X-Content-Type-Options, HSTS), AuditLog
- 회원 탈퇴: email/hashed_password/name tombstone 처리 (개인정보 삭제 + 이메일 재사용 가능)
- 처방전 이미지는 서버 메모리에서만 처리하고 응답 직후 폐기한다

---

## AI 설명 — 로컬 LLM

위험도 **판정**은 규칙 기반(`AnalysisService.quick_check`)이고, AI는 확정된 결과를 쉬운 말로 풀어 쓰는 설명만 한다.

- **모델·인프라**: Ollama + `qwen2.5:14b-instruct`, GPU passthrough. 외부 API를 쓰지 않아 건강정보가 서버 밖으로 나가지 않는다.
- **근거**: 임베딩 검색이 아니라 구조화 조회 — `quick_check`가 찾은 약의 분류·효능·주의사항, 판정 원문, 복호화된
  건강정보·알레르기, 출처 있는 용어 풀이(`glossary.py`)를 프롬프트에 넣는다.
- **구성**: 각 약 소개 → 식약처 기준의 위험 이유 → 대응. 말투는 앱 화면과 같은 해요체.
- **응답 처리**: 마크다운 제거 후 한자·등급 코드·복용 중단 권유·대체 약/다른 치료법 제안·근거 없는 연구 인용·출처 없는
  용어 풀이 문장을 제거한다. 남길 문장이 없을 때만 1회 재생성하고 그래도 안 되면 안내 문구로 대체한다.
- **대응 문장은 코드가 판정 종류별로 붙인다**(알레르기·임부·연령·병용). 일반의약품이 낀 병용은 처방 점검에 잡히지 않을 수
  있음을 알리는 별도 문장을 쓴다.
- **문제가 없는 경우**(`safe`)에는 모델을 부르지 않고, 약 개수와 "DUR 등록 규칙만 대상"임을 밝힌 정해진 문장을 낸다.
- **폴백**: Ollama가 응답하지 않아도(`OllamaUnavailableError`) 판정은 그대로이고 설명만 안내 문구로 대체된다.
- **성능**: 첫 요청은 모델 로드로 길게는 2분 반, 이후 요청은 10~15초 안팎. `keep_alive: 30m`, `OLLAMA_TIMEOUT_SECONDS=200`,
  클라이언트 타임아웃 220초.
- **한계**: 프롬프트로 근거 밖 내용을 제한해도 모델이 가끔 일반 지식을 섞는다 — 화면에 "AI 참고용 설명(진단 아님)"을 표시한다.
- **저장**: `analysis_results`에 판정 스냅샷과 설명을 AES-256-GCM으로 암호화해 저장한다.

---

## Flutter 앱

### 기술 스택
- Flutter + Dart, Provider(상태 관리), go_router(라우팅)
- image_picker(사진 촬영/선택, 웹 포함) — OCR은 서버(`POST /drugs/ocr`)에서 처리
- dio + flutter_secure_storage (HTTP 클라이언트, 토큰 저장)
- firebase_messaging(FCM) + flutter_local_notifications · timezone(복약 시각 예약 알림)

### 프로젝트 구조
```
front_app/lib/
├── core/
│   ├── api/             api_client.dart
│   ├── models/          auth · drug · medicine_box · analysis · user 모델
│   ├── notifications/   fcm_service, medication_reminder_service(복약 알림 스케줄링)
│   ├── storage/         token_storage
│   ├── theme/           app_theme (색·간격 토큰, 위험도 스타일)
│   └── widgets/         brand_mark 등 공용 위젯
└── features/
    ├── auth/            로그인·회원가입
    ├── camera/          촬영·OCR 결과 확인
    ├── home/            복약함·위험도 배너·AI 설명 (widgets/ 로 분할)
    ├── profile/         건강정보·알레르기·출생연도·임신 여부 입력
    └── search/          약 검색
```

### 약품 매칭 (`DrugService`)

| 순위 | 방식 | 설명 |
|---|---|---|
| 1 | prefix 검색 | `drug_key`에서 숫자 앞부분으로 prefix 조회, 완전 일치 우선, 수출 전용 품목은 뒤로 |
| 2 | ILIKE 폴백 | `item_name`/`simple_name` 부분 문자열 검색 |
| 3 | 성분명 기반 매칭 | 제형·용량을 뗀 성분명으로 `ingr_name` JSONB + `item_name` 재검색 ('와파린정'처럼 브랜드명이 성분명을 괄호에 숨긴 입력) |
| 4 | 유사도 후보 | 앞 단계가 모두 빈손일 때만. 자동 확정하지 않고 "유사 약품"으로만 제시 |

### 백엔드 연결
- 에뮬레이터: `http://10.0.2.2:8001/api/v1/`
- 실제 기기(같은 네트워크): `http://<PC IP>:8001/api/v1/`
- 릴리스 APK·웹: `https://goodmedicine.tail9f1768.ts.net/api/v1/` (Tailscale Funnel)
- `BASE_URL`은 `/api/v1/` 접두사와 끝 슬래시를 포함해야 한다.

### 약품 설명 표시
- 검색 결과 상세 시트: 효능만 표시 (빠르게 훑고 추가하는 단계)
- 복약함 카드 펼침: e약은요 7개 항목(효능·사용법·경고·주의사항·상호작용·부작용·보관법) 전체. 데이터 있는 항목만 표시하고,
  긴 허가사항은 4줄까지 보여 준 뒤 "더보기"로 펼친다.
- 약 설명은 **우리 DB가 먼저**다. 허가정보 상세 API를 배치(`sync.py permit_detail`)로 DB에 적재해 비어 있는 효능·용법·주의사항·성분을 채우고
  (e약은요 값은 덮어쓰지 않음, 일일 호출 한도 약 10,000건이라 며칠에 걸쳐 받음), 앱은 DB에 상세가 없는 약만 약을 담을 때·상세를 열 때 4초 안에서
  보충해 저장한다. 약 1행으로 모은 통합 데이터셋 `drugs_master`가 성분·함량·제형·판정 가능 여부와 설명 텍스트 유무를 한눈에 보여 준다.

---

## 시스템 커버리지

### quick-check가 탐지하는 범위

판정은 **성분(ingredient) 단위**가 정식 경로다.

- 복약함 약품을 `drug_ingredients`로 DUR 성분코드에 해소한 뒤 `dur_ingredient_contraindications`·
  `dur_ingredient_effect_groups`(효능군 + 계열로 묶음)를 조회한다.
- `residual_interactions`는 성분 규칙으로 재현되지 않는 쌍만 담고 있어 **항상 함께 조회·병합**한다. finding에는
  `source`(`ingredient`|`residual`)가 붙는다.
- **알레르기 충돌**: `users.allergy_info`를 `drug_ingredients.ingr_kor`(+ 미해소 약은 `drugs.ingr_name`)와 대소문자·공백 무시
  양방향 부분일치로 대조한다. 사용자 프로필 기반이라 `quick_check`가 `user_id`를 받아야 동작한다.

| 구분 | 탐지 | 근거 |
|---|---|---|
| DUR 병용금기 (→ critical) | 탐지 | 성분쌍 `dur_ingredient_contraindications` (+ 미해소 약 residual 폴백) |
| 동일 성분 중복 (→ caution) | 탐지 | 서로 다른 약이 같은 성분코드를 가질 때 |
| DUR 효능군중복주의 (→ caution) | 탐지 | 성분 `dur_ingredient_effect_groups` (+ residual 폴백) |
| 알레르기 성분 충돌 (→ critical) | 탐지 | 프로필 `allergy_info` 대 성분명. 미등록이면 스킵 |
| 특정연령대금기 (→ critical) | 부분 탐지 | `dur_ingredient_age_caution`. DUR 성분정보의 나이 기준(`AGE_BASE`)이 하나로 정해진 규칙(185건 중 163건)만 판정에 쓴다. 출생연도 미등록이면 스킵 |
| 노인주의 (→ caution) | 탐지 | 고정 기준 만 65세 이상. 출생연도 미등록이면 스킵 |
| 임부금기 (→ critical) | 탐지 | **품목 단위** `dur_item_pregnancy_taboo`(전체 약의 43.4%). 제형·적응증 범위('경구'·'외용' 등) 때문에 성분으로 합치지 않는다. 프로필에서 "임신 중"을 켠 경우에만 판정 |
| DUR 용량주의 (→ caution) | 부분 탐지 | 복약함 복용량(1회 개수 × 하루 횟수) × 정·캡슐 1개당 함량을 하루 최대 용량과 비교. 같은 성분은 여러 약을 합산, 규칙과 약의 제형이 맞을 때만. 복용량을 안 적었거나 시럽·가루약이면 스킵 |
| DUR 병용주의(별도 등급)·투여기간주의 | 미탐지 | 병용주의는 품목 단위 공개 API가 없고, 투여기간주의는 원본에 판정할 기준이 없다 |
| DUR에 등록되지 않은 조합 | 판정 불가 | AI로 추정하지 않는다 |

> **주의:** 와파린의 국내 DUR 병용금기는 메나테트레논·이그라티모드와의 2건뿐이고 아세트아미노펜과의 규칙은 없다. 타이레놀(아세트아미노펜) ×
> 와파린은 탐지되지 않으며, 이는 코드가 아니라 공공데이터 범위의 한계다. `safe`는 "DUR에 등록된 규칙에 걸리지 않음"이라는
> 뜻이며 안전 보증이 아니다.

### DUR API 중 판정에 쓰지 않는 것 (`DURPrdlstInfoService03`)

| API | 건수 | 비고 |
|---|---|---|
| `getCpctyAtentInfoList03` (용량주의) | 6,622건 | 쓰지 않음 — 용량주의는 성분정보(`getCpctyAtentInfoList02`)의 `MAX_QTY`로 판정 |
| `getMdctnPdAtentInfoList03` (투여기간주의) | 633건 | 적재하지 않음(본문 0건) |

---

## FCM 푸시

- Firebase 프로젝트 `good-medicine-app`, Android 패키지명 `com.goodmedicine.good_medicine`.
- 서버 키 `secrets/firebase-service-account.json` — 이미지에 넣지 않고 compose가 `/run/secrets`로 읽기 전용 연결한다.
- 앱 설정 `front_app/android/app/google-services.json` — 클라이언트용 공개 설정이라 CI APK 빌드를 위해 커밋한다.
- 복약함에 병용금기 약을 추가하면 `fcm_service.py`가 발송한다. FCM은 Google을 거치므로 알림에는 약 이름·약 ID를 싣지 않고
  일반 문구와 `type`만 보낸다. `users.fcm_token`이 없으면 조용히 건너뛴다.

## 배포

- **백엔드(API 전용)**
  - 개발: `docker compose up -d` — `docker-compose.override.yml` 자동 로드(소스 바인드마운트, `--reload`가 없어 코드 변경 후
    `docker compose restart backend` 필요).
  - 배포: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` — override 배제 + `tailscale`
    컨테이너 추가.
  - 외부 노출: `tailscale` 컨테이너(노드명 `goodmedicine`, `infrastructure/tailscale/serve.json`으로 `/`→`backend:8000`
    프록시) → `https://goodmedicine.tail9f1768.ts.net/api/v1/` (고정 HTTPS).
- **프론트(웹)**: `front_app/**` push → GitHub Actions(`deploy-web.yml`) → `flutter build web` → `vercel deploy --prebuilt --prod`
  → `https://goodmedicine-hpdice.vercel.app`. 프론트와 API 오리진이 달라 백엔드 `.env`에 `CORS_ORIGINS` + `CORS_ORIGIN_REGEX`가 필요하다.
- **APK**: `flutter build apk --release --dart-define=BASE_URL=https://goodmedicine.tail9f1768.ts.net/api/v1/`

## 남은 작업

| 작업 | 비고 |
|---|---|
| 계정 복구(비밀번호 재설정)·개인정보 처리방침·APK 정식 서명 | 출시 전. 현재 CI APK는 디버그 키 서명 |
| 외부 감시 등록 (`/health`) | operations.md 참고 |
| 복약 알림 실기기 검증 | 단위 테스트·빌드는 통과, 실기기에서 알림 표시와 재부팅 후 유지 여부는 확인 필요 |
| 로그인 실패 카운터 영속화 | `login_guard`는 프로세스 메모리 — 재시작 시 초기화, 워커를 늘리면 워커별로 센다 |
| 폐기된 Refresh Token 재사용 로그 | 만료·위조·재사용이 같은 401이라 탈취 신호를 구분하지 못한다 |
| DUR 투여기간주의 판정 | 원본에 기간 기준이 없다 |
| 일반의약품 성분 연결 | 일반의약품은 약 30%만 DUR 성분코드에 이어져 있다(전문의약품 77%) — 심평원 약가 데이터에 적게 들어 있다 |
| 처방전 표 형식 복용량 | OCR 복용량 읽기 중 처방전 표 형식은 실사진으로 검증하지 못했다 |

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

# 테스트 (별도 drugtest_test_db 사용, 운영 DB 무관)
docker exec -e PYTHONPATH=/app -w /app drugtest-backend-1 python -m pytest tests/ -q

# 마이그레이션
docker exec -it drugtest-backend-1 alembic upgrade head

# 로컬 LLM — 최초 1회 모델 pull 필요, 이후엔 볼륨에 유지됨
docker compose up -d ollama
docker exec drugtest-ollama-1 ollama pull qwen2.5:14b-instruct
docker exec drugtest-ollama-1 ollama ps   # 로드 상태·GPU 사용률 확인

# 공공데이터 동기화
docker exec drugtest-backend-1 python sync.py overview
docker exec drugtest-backend-1 python sync.py dur_contraindications
docker exec drugtest-backend-1 python sync.py efcy_dplct
docker exec drugtest-backend-1 python sync.py fill_ingr
```

---

## GitHub

- 레포지토리: https://github.com/hpdice/good_medicine
- 브랜치: main
