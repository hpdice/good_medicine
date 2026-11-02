# 운영 런북 — 백업·복원 · 키 보관 · 반영 절차

> 배포 구조는 [project-status.md](./project-status.md)의 "배포"를 본다. 이 문서는 **운영 중 해야 하는 일**만 다룬다.

---

## 1. DB 백업

**자동**: Windows 작업 스케줄러 `GoodMedicine-DB-Backup` — 매일 04:00, PC가 꺼져 있었으면 켜진 뒤 실행.
`scripts/backup-db.ps1 -Verify`를 돌린다.

| 항목 | 값 |
|---|---|
| 방식 | 컨테이너 안 `pg_dump -Fc`(압축) → `docker cp`로 호스트에 꺼냄 |
| 위치 | `D:\drugTest\backups\drugtest-YYYYMMDD-HHMMSS.dump` |
| 검증 | `-Verify`: 임시 DB `drugtest_restore_check`에 **실제로 복원**해 핵심 테이블 5개 행 수를 운영과 비교 → 임시 DB 삭제 |
| 보관 | 14일 (`-KeepDays`로 변경) |
| 로그 | `D:\drugTest\backups\backup.log` |

```powershell
# 수동 실행
powershell -ExecutionPolicy Bypass -File C:\Dev\drugTest\scripts\backup-db.ps1 -Verify
# 스케줄 상태 / 마지막 결과(0 = 성공)
Get-ScheduledTaskInfo -TaskName GoodMedicine-DB-Backup
# 자동 백업 해제
Unregister-ScheduledTask -TaskName GoodMedicine-DB-Backup -Confirm:$false
```

> 백업은 운영 데이터와 같은 호스트(D:)에 저장되므로 디스크 장애에 대비해 주기적으로 외부 매체에 사본을 옮긴다.
> 외부 사본은 **국내**(외장 디스크 등)에 두고, 클라우드에 올린다면 덤프를 먼저 암호화한다 — 덤프에는 이메일·이름이
> 평문으로 들어 있어, 해외 클라우드에 그대로 올리면 개인정보 국외 이전이 된다.

## 2. 복원

임시 DB로의 복원은 매일 `-Verify`가 수행한다. 운영 DB에 덮어쓰는 복원은 필요해지기 전에 별도 compose 프로젝트에서
연습해 둔다.

```powershell
cd C:\Dev\drugTest
docker compose stop backend                                  # 쓰기 중단
docker cp D:\drugTest\backups\drugtest-YYYYMMDD-HHMMSS.dump drugtest-postgres-1:/tmp/restore.dump
docker exec drugtest-postgres-1 sh -c 'pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists --no-owner /tmp/restore.dump'
docker exec drugtest-postgres-1 rm -f /tmp/restore.dump
docker compose start backend
docker exec drugtest-backend-1 python validate_db.py          # 품질 검증
```

복원한 DB는 **백업 당시의 `FIELD_ENCRYPTION_KEY`로만** 암호화 필드를 읽을 수 있다(다음 절).

## 3. 암호화 키 보관 — 가장 중요

`.env`의 두 값은 **DB 백업과 별도로** 보관한다. 런타임 비밀 파일은 `secrets/`에 모여 있다(`secrets/README.md`).

| 키 | 잃으면 | 유출되면 |
|---|---|---|
| `FIELD_ENCRYPTION_KEY` | 건강정보·알레르기·출생연도·**복약함 전체**·분석 이력이 **영구히 복호화 불가** (백업이 있어도 소용없음) | 덤프·DB가 함께 유출되면 건강정보 평문 노출 |
| `SECRET_KEY` | 모든 로그인 토큰 무효(재로그인하면 됨) | 누구든 임의 사용자의 토큰을 위조 가능 |
| `secrets/firebase-service-account.json` | 푸시 알림만 중단 — Firebase 콘솔에서 새 키 발급으로 복구 가능 | 우리 앱 이름으로 푸시 발송 가능 → 콘솔에서 즉시 키 폐기 |

- **보관 위치**: 비밀번호 관리자 또는 오프라인 매체(USB 등). 덤프 폴더·Git·메신저에 두지 않는다.
- **덤프와 키를 같은 곳에 두지 않는다** — 그러면 암호화가 무의미해진다. `backup-db.ps1`이 키를 백업하지 않는 이유.
- **점검**: 키를 보관한 곳에서 꺼낸 값이 현재 `.env`와 같은지 분기마다 한 번 확인.
- 현재 코드는 키 **교체(로테이션)**를 지원하지 않는다(단일 키). 교체가 필요해지면 "옛 키로 복호화 → 새 키로 재암호화"
  마이그레이션을 따로 만들어야 한다.

## 4. 코드 변경을 서버에 반영하기

| 상황 | 명령 |
|---|---|
| 개발 모드 (`docker compose up -d`) | 소스는 바인드마운트돼 있지만 **uvicorn `--reload`가 없다** → `docker compose restart backend` |
| 배포 모드 (Tailscale 포함) | `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` (소스가 이미지에 구워짐) |
| 마이그레이션이 추가됐을 때 | 반영 직후 `docker exec drugtest-backend-1 alembic upgrade head` — **자동으로 돌지 않는다** |
| 반영 전 확인 | `docker exec -e PYTHONPATH=/app -w /app drugtest-backend-1 python -m pytest tests/ -q` (push하면 CI에서도 돈다) |
| Dockerfile·compose 가 바뀌었을 때 | `docker compose build backend` 후 `up -d` (개발) / 배포는 `--build` |

## 5. 운영 정책

### Rate Limit — 누구를 한 명으로 세나

| 엔드포인트 | 한도 | 기준 |
|---|---|---|
| `POST /auth/login` | 20회/15분 (성공 포함) + **계정별 실패 5회/15분** | 실제 클라이언트 IP + 이메일 |
| `POST /analysis/quick-check` | 60회/분 | 로그인 사용자 (토큰 없으면 IP) |
| `POST /analysis/guide` | 10회/분 | 로그인 사용자 |
| `POST /drugs/ocr` | 20회/분 | 로그인 사용자 |

- 모든 요청이 Tailscale 컨테이너를 거쳐 들어오므로 출발지 IP를 그대로 쓰면 전 사용자가 IP 하나를 공유하게 된다.
  그래서 로그인은 IP 한도를 20회/15분으로 두고, 무차별 대입 방어는 **이메일별 실패 횟수**(`app/core/login_guard.py`,
  `LOGIN_FAILURE_LIMIT`·`LOGIN_FAILURE_WINDOW_SECONDS`)가 맡는다. 같은 와이파이처럼 IP를 공유하는 환경에서 정상
  사용자가 막히지 않게 하려는 것이다. 한도는 `.env`로 조정할 수 있다.
- 실제 IP: Tailscale Funnel은 출발지 주소를 `X-Forwarded-For`에 **덮어써서** 넘긴다. 백엔드는 직접 연결 상대가
  `TRUSTED_PROXY_CIDRS`(기본: 루프백·사설망)일 때만 이 헤더를, 그것도 **가장 오른쪽 값**만 믿는다
  (`app/core/rate_limit.py`). 감사 로그의 IP도 같은 함수를 쓴다.
- 한도 저장소는 **메모리**다 — 백엔드를 재시작하면 초기화되고, 워커를 여러 개로 늘리면 워커마다 따로 센다.
  워커를 늘릴 땐 Redis 같은 공유 저장소로 바꿔야 한다.

### 탈퇴 — 무엇을 지우고 무엇을 남기나

| 대상 | 처리 |
|---|---|
| 복약함 전체, 분석 이력(AI 설명 포함) | **삭제** |
| 건강상태·알레르기·출생연도·FCM 토큰·전화번호 | 삭제(NULL) |
| 이메일·이름·비밀번호 | 무작위 값으로 덮어씀(같은 이메일로 재가입 가능) |
| Refresh Token | 전부 폐기 |
| 이미 발급된 Access Token | 요청마다 계정 활성 여부를 확인하므로 **즉시 무효** |
| 감사 로그(`audit_logs`) | **보존** — 보안 추적용. 사용자 ID·IP·시각만 있고 건강정보는 없음. `delete_account` 기록 추가 |

> 감사 로그의 보관 기간은 개인정보 처리방침에서 정하고, 기간이 지난 행을 삭제한다.

## 6. 공공데이터 월간 갱신

**자동**: 작업 스케줄러 `GoodMedicine-Monthly-Sync` — 매월 1일 02:00(놓치면 부팅 후), 최대 12시간.
`scripts/monthly-sync.ps1`: 헬스체크 → **백업(복원 검증)** → 동기화 11단계(e약은요 · 허가정보 · DUR 병용금기 · 효능군 · 연령 · 임부 · DUR 성분정보 · 이름 매칭 · 심평원 CSV · 심평원 성분 연결 · 1정당 함량) → 위험 태그 → **품질 게이트**.
한 단계라도 실패하면 멈추고 종료 코드 1. 로그: `D:\drugTest\sync-logs\sync-*.log`(최근 24개).

```powershell
# 수동 실행 (전체 / 일부)
powershell -ExecutionPolicy Bypass -File C:\Dev\drugTest\scripts\monthly-sync.ps1
powershell -ExecutionPolicy Bypass -File C:\Dev\drugTest\scripts\monthly-sync.ps1 -Only dur_age_caution
# 이번 달 자동 실행 건너뛰기 / 해제
Disable-ScheduledTask -TaskName GoodMedicine-Monthly-Sync     # 다시 켤 땐 Enable-ScheduledTask
Unregister-ScheduledTask -TaskName GoodMedicine-Monthly-Sync -Confirm:$false
# 데이터가 얼마나 최신인가 — 소스별 마지막 성공 시각
docker exec drugtest-backend-1 python sync.py status
```

- **실패한 페이지는 건너뛰지 않는다.** DUR 병용금기는 실패 페이지를
  체크포인트(`sync_state` 볼륨 `/var/lib/goodmedicine/`)로 남겨, 재실행하면 거기서 이어받는다. 월간 스크립트는
  할당량 초과로 멈추면 60분 뒤 최대 3번 이어서 재시도한다.
- **품질 게이트**(`validate_db.py`): 자기참조·정규순서 위반·중복 쌍·고아 행·규칙 수 하한(약품 30,000 · 병용금기 300 ·
  효능군 200)·알려진 금기 쌍 3개 탐지 여부. 하나라도 걸리면 실패 → 직전 백업으로 복원 검토(2절).
- **원본 응답 보관·재생**: 동기화가 받은 API 응답을 `/var/lib/goodmedicine/raw/`(`sync_state` 볼륨)에 엔드포인트·날짜별 gz 파일로 남기고 최근 3개 날짜만 유지한다. 파싱 로직을 고친 뒤엔 `docker exec drugtest-backend-1 python sync.py <소스> --replay`로 API 호출 없이 재적재한다(날짜 지정은 `--replay=YYYYMMDD`). DB 백업에는 포함되지 않는다(API에서 재수집 가능한 캐시). 용량이 부담되면 `.env`의 `RAW_RESPONSE_SAVE=false` 또는 `RAW_KEEP_SNAPSHOTS`를 줄인다.
- 원천이 금기 사유 문장을 고치면 반영되고, 그 규칙의 `risk_tags`는 비워져 다음 `extract_risk_tags`에서 다시 뽑힌다.
- 동기화 중에도 서비스는 계속 동작한다(판정은 읽기만). 다만 공공 API 일일 할당량을 쓰므로 같은 날 수동 동기화는 피한다.

## 7. 외부 감시

`/health`는 이제 DB까지 확인해 장애 시 **503**을 준다. 하지만 PC가 꺼지면 PC 안의 무엇도 알릴 수 없으므로,
**PC 밖의 무료 감시 서비스**(예: UptimeRobot, Better Stack 등)에 아래 주소를 5분 간격으로 등록하고 알림(메일·앱)을 켠다.

```
https://goodmedicine.tail9f1768.ts.net/health      → 200 {"status":"ok","db":"ok"} 이 정상
```

> 감시 서비스에는 URL만 알려주며 개인정보는 오가지 않는다.

## 8. 운영 점검 항목

| 항목 | 참고 |
|---|---|
| 암호화 키 별도 보관 확인 | 3절 — 분기마다 보관본과 현재 `.env` 대조 |
| 백업 외부 사본(국내 매체) | 1절 |
| 외부 감시 등록 | 7절 |
| 운영 DB 복원 연습 | 2절 |
| 계정 복구(비밀번호 재설정), 개인정보 처리방침, APK 정식 서명 | 출시 전 — [project-status.md](./project-status.md) "남은 작업" |
