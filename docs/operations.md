# 운영 런북 — 백업·복원 · 키 보관 · 반영 절차

> 기준일 2026-09-30. 배포 구조 자체는 [deploy-tailscale.md](./deploy-tailscale.md)(백엔드),
> [deploy-web-vercel.md](./deploy-web-vercel.md)(웹). 이 문서는 **운영 중 해야 하는 일**만 다룬다.

---

## 1. DB 백업

**자동**: Windows 작업 스케줄러 `GoodMedicine-DB-Backup` — 매일 04:00, PC가 꺼져 있었으면 켜진 뒤 실행.
`scripts/backup-db.ps1 -Verify`를 돌린다.

| 항목 | 값 |
|---|---|
| 방식 | 컨테이너 안 `pg_dump -Fc`(압축) → `docker cp`로 호스트에 꺼냄 |
| 위치 | `D:\drugTest\backups\drugtest-YYYYMMDD-HHMMSS.dump` (2026-09-30 기준 약 6MB) |
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

> ⚠ **백업이 운영 데이터와 같은 PC(D:)에 있다.** 실수로 지운 데이터·잘못된 마이그레이션에서는 복구할 수 있지만,
> **디스크 고장·PC 분실에는 같이 사라진다.** 주 1회 정도 외부 매체로 사본을 옮길 것.
> 외부 사본은 **국내**(외장 디스크 등)에 두고, 클라우드에 올린다면 덤프를 먼저 암호화할 것 — 덤프에는 이메일·이름이
> 평문으로 들어 있어, 해외 클라우드에 그대로 올리면 이 프로젝트가 피하려던 개인정보 국외 이전이 된다.

## 2. 복원

**검증된 것**: 임시 DB로의 복원(매일 `-Verify`가 수행). **운영 DB에 덮어쓰는 복원은 아직 실제로 해 본 적 없다** —
필요해지기 전에 한 번 연습해 둘 것(예: 개발 PC의 별도 compose 프로젝트).

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

`.env`의 두 값은 **DB 백업과 별도로** 보관한다.

| 키 | 잃으면 | 유출되면 |
|---|---|---|
| `FIELD_ENCRYPTION_KEY` | 건강정보·알레르기·출생연도·**복약함 전체**·분석 이력이 **영구히 복호화 불가** (백업이 있어도 소용없음) | 덤프·DB가 함께 유출되면 건강정보 평문 노출 |
| `SECRET_KEY` | 모든 로그인 토큰 무효(재로그인하면 됨) | 누구든 임의 사용자의 토큰을 위조 가능 |

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
| 반영 전 확인 | `docker exec -e PYTHONPATH=/app -w /app drugtest-backend-1 python -m pytest tests/ -q` (CI에서 안 돈다) |

## 5. 운영 정책 (2026-09-30 변경)

### Rate Limit — 누구를 한 명으로 세나

| 엔드포인트 | 한도 | 기준 |
|---|---|---|
| `POST /auth/login` | 5회/15분 | 실제 클라이언트 IP |
| `POST /analysis/quick-check` | 60회/분 | 로그인 사용자 (토큰 없으면 IP) |
| `POST /analysis/guide` | 10회/분 | 로그인 사용자 |
| `POST /drugs/ocr` | 20회/분 | 로그인 사용자 |

- 이전엔 모든 요청이 Tailscale 컨테이너를 거쳐 들어와 **전 사용자가 IP 하나를 공유**했다(서비스 전체 로그인 5회/15분).
- 실제 IP: Tailscale Funnel은 출발지 주소를 `X-Forwarded-For`에 **덮어써서** 넘긴다. 백엔드는 직접 연결 상대가
  `TRUSTED_PROXY_CIDRS`(기본: 루프백·사설망)일 때만 이 헤더를, 그것도 **가장 오른쪽 값**만 믿는다
  (`app/core/rate_limit.py`). 감사 로그의 IP도 같은 함수를 쓴다(이전엔 위조 가능한 첫 번째 값을 그대로 기록).
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

> 감사 로그의 **보관 기간**은 아직 정하지 않았다. 개인정보 처리방침을 만들 때 기간을 정하고 그보다 오래된 행을
> 지우는 작업이 필요하다.

## 6. 남은 운영 과제

| 과제 | 우선순위 | 비고 |
|---|---|---|
| 백업 외부 사본 (국내 매체) | 높음 | 1절 경고 |
| 암호화 키 별도 보관 확인 | **높음** | 3절 — 사람이 해야 함 |
| 헬스체크에 DB 연결 확인 추가 + 외부에서 주기적으로 감시 | 중간 | 지금 `/health`는 항상 `ok`. PC가 꺼져도 알 수 없음 |
| CI에서 백엔드 테스트 실행 | 중간 | 현재 웹·APK 빌드만 |
| 버전 고정: `poetry.lock` 커밋, `ollama/ollama` 이미지 태그 | 중간 | 지금은 빌드할 때마다 의존성이 달라질 수 있음 |
| Docker 로그 용량 제한 (`logging.options.max-size`) | 낮음 | |
| 공공데이터 정기 갱신 + 마지막 동기화 시각 기록 | 중간 | 금기 규칙이 오래되면 안전 문제 |
| 계정 복구(비밀번호 재설정), 개인정보 처리방침, APK 정식 서명 | 출시 전 | [project-status.md](./project-status.md) "남은 작업" |
