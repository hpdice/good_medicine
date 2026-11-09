# 데이터 모델 — 테이블마다 담는 것과 쓰임

> 테이블 19개. 모든 테이블에 `id`(UUID, `drugs_master`는 `drug_id`)가 있고 `created_at`/`updated_at`은 생략했다.
> 행 수는 2026-11-09 DB 실측이다. "채우는 곳"은 `sync.py` 명령·서비스 함수, "읽는 곳"은 그 테이블을 읽는 서비스 함수다.
> 코드 구조·판정 흐름은 [CLAUDE.md](../CLAUDE.md)를 본다.

## 1. 한눈에: 데이터가 흐르는 길

```
공공데이터 (e약은요 · 허가정보 · DUR 품목정보 4종 · DUR 성분정보 7종 · 심평원 CSV 2개)
   │  sync.py (월간 자동 + 수동)
   ▼
원천 테이블   drugs · drug_ingredients · dur_ingredient_* · dur_item_pregnancy_taboo · hira_* · dur_ingredient_master
   │  build_* (API 미사용, 로컬 가공)
   ▼
가공 테이블   drug_ingredients(해소·함량) · drugs_master(통합) · residual_interactions(시드)
   │
   ▼  POST /analysis/quick-check  →  AnalysisService.quick_check
판정          복약함 약 → 성분코드 → 규칙 테이블 조회 → critical / caution / safe
   ▼  (사용자가 "AI 설명 보기"를 누를 때만)
AI 설명       판정 결과 + drugs 본문 → 로컬 LLM → analysis_results에 암호화 저장
```

판정에 AI는 관여하지 않는다. `drugs_master`도 판정이 읽지 않는다(성분 판정은 `drug_ingredients` 경로 그대로).

## 2. 약과 성분

### `drugs` — 약 1품목 1행 (35,869행, 가장 큰 테이블 226MB)

| 컬럼 | 담는 것 |
|---|---|
| `item_seq` | 품목기준코드(유일). 심평원·DUR과 잇는 키 |
| `item_name` · `simple_name` | 품목명 · 검색용 간략명(`fill_simple_names`) |
| `drug_key` | 출처가 다른 데이터를 맞추는 매칭 키(괄호 제거·단위 정규화·소문자) |
| `entp_name` · `class_name` · `etc_otc_name` | 업체 · 분류명 · 전문/일반 구분 |
| `main_item_ingr` | 허가정보 주성분 원문(`[M코드]이름/…` 또는 `\|` 구분) |
| `ingr_name` (JSONB) | 위 원문을 파싱한 성분 목록 |
| `efcy_qesitm` 외 6개 | e약은요 항목: 효능 · 사용법(`use_method_qesitm`) · 경고(`atpn_warn_qesitm`) · 주의사항(`atpn_qesitm`) · 상호작용(`intrc_qesitm`) · 부작용(`se_qesitm`) · 보관법(`deposit_method_qesitm`) |
| `detail_fetched_at` | 허가정보 상세를 받은 시각. NULL이면 적재 대상 |

- **채우는 곳**: `overview`(e약은요), `approval`(허가정보 목록), `permit_detail`·`box_detail`(상세로 빈 필드만 보강, 전문 저장), `fill_ingr`, `fill_simple_names`, DUR 적재 중 없는 약은 `_find_or_create_drug_from_dur`가 자동 생성.
- **읽는 곳**: 약 검색 4단계 매칭(`DrugService`), 복약함, `AnalysisService`(약 정보), 건강 상태 금기(`atpn_qesitm`의 "다음 환자에는 투여하지 말 것" 항목), AI 프롬프트(`ai_guide_service`), OCR 후보 매칭.

### `drug_ingredients` — 약 ↔ DUR 성분코드 (약 3만 행, 판정의 조인 브리지)

| 컬럼 | 담는 것 |
|---|---|
| `drug_id` → `drugs` | 약 (삭제 시 연쇄) |
| `ingr_code` · `ingr_kor` | DUR 성분코드 · 출처 행에 적힌 성분명(염·수화물 표기 포함) |
| `source` | `dur` · `jsonb_fallback` · `permit_detail` · `hira_eng` — 코드를 어떤 경로로 맺었나 |
| `amount_mg` | 정·캡슐 1개당 함량(용량주의용) |

- 유일: `(drug_id, ingr_code)`. 한 약에 성분이 여러 개(복합제)라 행으로 뺀다.
- **채우는 곳**: DUR 적재 때 응답의 `INGR_CODE` 캡처(`dur`), `build_drug_ingredients`(이름 매칭), `build_drug_ingredients_hira`(심평원), 허가정보 상세 적재(`permit_detail`), `repair_pipe_ingr`, 함량은 `build_drug_amounts`.
- **읽는 곳**: `get_ingredient_codes_for_drug_list`(복약함 약 → 성분코드, 판정 첫 단계), `get_ingredient_amounts_for_drug_list`(하루 용량), `get_ingredient_names_for_drug_list`·`get_ingredient_kor_for_codes`(화면 이름).

### `dur_ingredient_master` — 성분코드 ↔ 이름 조회표 (1,499개, 코드당 1행)

`ingr_code` · `ingr_kor`(기본 성분명, 예: 설트랄린) · `ingr_eng` · `ingr_eng_norm`(비교용 정규화) · `mix_type`(단일|복합).
- **채우는 곳**: `dur_ingredient`(성분정보). **읽는 곳**: `_ingredient_aliases`(같은 성분의 중복 코드를 대표 코드 하나로 묶음), `build_drug_ingredients_hira`·`build_drug_amounts`의 영문명 → 코드 해소. 판정이 이름을 직접 쓰지는 않는다.

## 3. 판정 규칙 (DUR) — 규칙 종류마다 키가 달라 테이블이 따로

| 테이블 | 담는 것 | 채우는 곳 | 읽는 곳 → 판정 |
|---|---|---|---|
| `dur_ingredient_contraindications` (1,251) | 성분쌍 병용금기. `ingr_code_a`<`ingr_code_b`(정규 순서, 유일), `ingr_kor_a/b`, `prohibit_content`(사유 원문), `remark`(조건), `risk_tags`(JSONB 위험 태그), `source` | `dur_contraindications`(품목정보, `product`) + `dur_ingredient`(성분정보, `ingredient`). `risk_tags`는 `extract_risk_tags`(로컬 LLM, 표시용) | `get_ingr_contraindications_for_codes` → `_contraindication_findings` → **critical** |
| `dur_ingredient_effect_groups` (377) | 효능군중복. `(ingr_code, dur_seq)` 유일, `effect_name`(효능군), `sers_name`(계열) | `efcy_dplct` + `dur_ingredient` | `get_ingr_effect_groups_for_codes` → `_effect_group_findings` → **caution** (효능군+계열이 같으면 한 묶음) |
| `dur_ingredient_age_caution` (290) | 특정연령대금기(185)·노인주의(105). `(ingr_code, rule_type)` 유일, `age_threshold`·`age_unit`(세\|개월\|주)·`age_direction`, `prohibit_content` | `dur_age_caution` + `dur_ingredient`(나이 기준은 `AGE_BASE`로 매번 다시 채움) | `get_ingr_age_caution_for_codes` → `_age_findings`(사용자 `birth_year`) → 연령금기 **critical** / 노인주의 **caution** |
| `dur_ingredient_dose_caution` (619) | 하루 최대 용량. `ingr_code`, `mix_codes`(복합제 나머지 성분), `form_name`(제형), `max_qty`(원문), `limits_mg`(JSONB 성분별 mg) | `dur_ingredient`(`getCpctyAtentInfoList02`, 매번 다시 만듦) | `get_ingr_dose_cautions_for_codes` → `_dose_findings` → **caution**. `drug_ingredients.amount_mg` × 복약함 복용량 × 제형(`get_hira_form_names`) |
| `dur_item_pregnancy_taboo` (약 1.6만) | 임부금기. **품목 단위** `(item_seq, ingr_code)`, `prohibit_content`, `remark`(적용 범위) | `dur_pregnancy` | `get_pregnancy_taboo_for_item_seqs` → `_pregnancy_findings`(사용자 `pregnancy` 켠 경우) → **critical** |
| `residual_interactions` (217) | 성분코드를 못 맺은 약이 낀 품목쌍 `(drug1_id, drug2_id)`, `interaction_type`, `mechanism` | `build_residual`(`seed/residual_interactions.json`) | `get_residual_for_drug_list` → `_residual_findings` — 항상 함께 조회해 병합 |

같은 성분코드를 가진 서로 다른 약은 규칙 표 없이 `drug_ingredients`만으로 `_same_ingredient_findings`가 **동일 성분 중복(caution)**으로 잡는다.

## 4. 심평원 약가마스터 — CSV 두 개에서 테이블 세 개

| 테이블 | 담는 것 | 쓰임 |
|---|---|---|
| `hira_item_gen_codes` (52,995) | 품목 → 일반명코드. `item_seq`, `gen_code`(9자리, 7번째 글자가 투여경로 A내복·B주사·C외용), `etc_otc`, `atc_code`, `cancelled_on` | 약 → 일반명코드 연결. `build_drug_ingredients_hira`·`build_drugs_master`·`get_hira_form_names` |
| `hira_gen_codes` (20,114) | **일반명코드 1행**. `gen_code`(PK), `form_code`, `form_name`(제형), `route`(내복\|주사\|외용\|기타), `class_no` | 제형·투여경로·분류는 성분이 아니라 일반명코드에만 종속(2NF)이라 분리. 하루 용량의 제형 맞추기(`get_hira_form_names`), 함량 계산, `drugs_master` |
| `hira_gen_ingredients` (59,631) | 일반명코드의 성분 구성. `gen_code`→`hira_gen_codes`, `seq`(복합제 성분 순번), `ingr_name`(대부분 영문), `strength`, `unit` | 영문명을 DUR 성분정보와 완전 일치로 맞춰 성분코드 해소(`hira_eng`), 함량(`build_drug_amounts`) |

**채우는 곳**: `hira_master`(CSV는 `sync_state` 볼륨 `hira/`, SHA-256이 같으면 건너뜀). 주성분 파일은 일반명코드 속성을 먼저, 성분 행을 나중에 넣는다.

## 5. 통합 데이터셋

### `drugs_master` — 약 1행으로 합친 파생 테이블 (35,869행)

`drug_id`(PK→`drugs`) · `item_seq`(유일) · 이름·업체·분류·`etc_otc_name`·`atc_code` · `hira_components`(JSONB 심평원 성분·함량·제형·경로) · `dur_ingredients`(JSONB) · `dur_ingr_codes`(배열, 검색용 GIN) · `dosage_form` · `route` · `ingredient_status`(`dur_resolved`\|`hira_only`\|`none`) · `judgeable` · `has_efficacy`/`has_use_method`/`has_precautions`/`has_interaction_text` · `built_at`.
- **채우는 곳**: `build_drugs_master`(매번 전부 다시, 취소된 심평원 품목 제외), 허가정보 상세를 받을 때 그 약의 행만 `refresh_drugs_master_row`.
- **읽는 곳**: 판정·API는 **아직 읽지 않는다**. 정제된 통합 DB로서 직접 조회·분석용이다(주 목적이 통합 DB).

## 6. 사용자

| 테이블 | 담는 것 | 채우는 곳 → 읽는 곳 |
|---|---|---|
| `users` | `email`·`hashed_password`(bcrypt)·`name`, `is_active`, `privacy_consent_at`·`health_data_consent_at`(가입 시각), `fcm_token`, 암호화 컬럼 `health_conditions_encrypted`·`birth_year_encrypted`·`pregnancy_encrypted`(·`allergy_info_encrypted`는 판정에 안 쓰며 값은 비움) | 가입 `auth_service` · 프로필 `user_service`(`PATCH /users/me`). 읽는 곳: 로그인, 현재 사용자(`dependencies`), 건강 상태·연령·임부 판정(`_user_findings`), FCM 발송(`medicine_box_service`) |
| `medicine_box_entries` | 평문: `user_id`·`is_current`·`added_method`. `payload_encrypted` 하나에 약 ID·처방일·복용 기간·1회 개수·1일 횟수·복용 시각·알림 on/off·메모 | `medicine_box_service`(CRUD, 중복 방지). 읽는 곳: 복약함 목록, 판정(`_daily_units`가 하루 복용량 계산), 탈퇴 시 삭제 |
| `analysis_results` | `risk_level`·`model_name` 평문 + `drug_ids_encrypted`·`findings_snapshot_encrypted`·`action_guide_encrypted` | AI 설명을 만들 때 `ai_guide_service`가 저장. **앱이 읽는 곳은 아직 없다**(이력용, 탈퇴 시 삭제) |
| `refresh_tokens` | `token_hash`(유일)·`is_revoked`·`expires_at` | 로그인 때 발급, 갱신 때 기존 폐기(1회용), 로그아웃·탈퇴 때 폐기(`auth_service`). 사용자 삭제 시 연쇄 삭제 |
| `audit_logs` | `user_id`(FK 없음)·`action`(`register`\|`login`\|`delete_account`)·`ip_address`·`user_agent` | `auth_service`·`user_service`가 기록. **읽는 곳은 없다**(운영자 조회용) |
| `alembic_version` | 적용된 마이그레이션 버전 | `alembic upgrade`가 갱신. 현재 `0020_hira_gen_codes` |

건강정보(건강 상태·출생연도·임신 여부·복약 내용·AI 설명 이력)는 모두 AES-256-GCM으로 암호화해 저장한다. 요청 시점에 그 사용자 한 명만 복호화한다.

## 7. 알려진 정규화 한계

- 성분 목록이 `drugs.main_item_ingr`(원문)·`drugs.ingr_name`(JSONB)·`drug_ingredients`(행) 세 곳에 있고 서로 어긋난 약이 있다(원문만 230개, `ingr_name`만 27개).
- 규칙 표의 성분코드에 `dur_ingredient_master` 외래 키가 없다(현재 고아 0건).
- 규칙 표의 `ingr_kor`는 중복이 아니다 — 출처 행의 염·수화물 표기이고 master는 기본 성분명이라 둘이 다르다(병용금기 175/1,251행, 연령 74/290행).
- 건강정보 암호화 블롭은 한 칸에 여러 값이 들어가지만 보안상의 선택이다.
