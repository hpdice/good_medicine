# 백엔드(API) 배포 — 로컬 `docker compose` + Tailscale Funnel 컨테이너

> 프론트 웹은 Vercel 이 호스팅한다 — `docs/deploy-web-vercel.md`. 이 문서는 API 백엔드만 다룬다.

> **결정 배경**: 개인정보(회원 email/이름 + 암호화된 건강정보·복약정보)를 **국외에서 저장·처리하지
> 않으려고** 전부 국내(내 PC)로 운영한다 — PIPA상 건강·복약 정보는 민감정보라, 백엔드가 해외에
> 있으면 국외 이전/처리에 해당한다. 공공 의약품 데이터는 출처 표시 조건으로 자유 이용(공공누리
> 제1유형 가정 — 데이터셋별 확인).
>
> **향후 과제**: PC 상시 가동 부담을 덜려면 한국 리전 상시 서버(Oracle Cloud Free 춘천/서울, 국내 VPS)로
> 이전 검토. **조건: 개인정보 저장·처리가 국내에 머물 것.**

---

## 구성

```
내 PC (국내)
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
    ├─ backend   (FastAPI, API 전용)                     127.0.0.1:8001
    ├─ postgres  (약품 35,487 · DUR 규칙)               127.0.0.1:5432
    ├─ ollama    (AI 가이드, GPU)                        호스트 포트 없음 (내부망 ollama:11434)
    └─ tailscale (Funnel, userspace)  →  backend:8000  (compose 내부 네트워크)

  → https://goodmedicine.tail9f1768.ts.net/api/v1/   (고정 HTTPS, 재부팅해도 유지)
        · `/` 는 404 (API 엔드포인트만). 웹 화면은 Vercel(goodmedicine-hpdice.vercel.app)
```

- **터널이 컨테이너 안에 있다** — 호스트에서 `tailscale funnel` 을 수동 실행할 필요가 없다.
  Docker Desktop 자동시작 + `restart: unless-stopped` 만으로 재부팅 후 터널까지 자동 복구.
- tailnet 노드명은 `goodmedicine`(컨테이너). 호스트에 깔린 네이티브 Tailscale(`drugtest-pc`)은
  관리·SSH 용도로만 두고 **funnel 은 껐다**(`tailscale serve reset`).
- `TS_USERSPACE=true` — Docker Desktop(Windows)에서 `/dev/net/tun`·`NET_ADMIN` 없이 동작.
- backend 는 여전히 `127.0.0.1:8001` 에만 바인딩(LAN/외부 직접 노출 없음). 외부 유입은
  tailscale 컨테이너가 compose 네트워크로 `backend:8000` 에 프록시하는 경로 하나뿐.
- 개인정보: PC(국내)에만. 국외 이전 없음.
- 비용: $0. PC가 켜져 있을 때만 접속 가능(시연 영상 백업 권장).

---

## 최초 세팅 (1회)

### 1. Funnel 허용 (관리 콘솔, 1회)

`login.tailscale.com` → **Access controls (ACL)** 에 Funnel 속성:
```json
"nodeAttrs": [
  { "target": ["*"], "attr": ["funnel"] }
]
```
(이미 활성화돼 있음 — tailnet `hpdice.github` 에서 완료함.)

### 2. 스택 기동 (backend + tailscale)

```cmd
cd C:\Dev\drugTest
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
- 백엔드 단일 스테이지 이미지라 빌드 ~30초.
- 일반 개발은 `docker compose up -d` (override 자동 로드 → tailscale 미기동, 소스 바인드마운트 — 코드 변경 후 `docker compose restart backend`).

### 3. tailscale 노드 인증 (최초 1회만)

```cmd
docker logs -f drugtest-tailscale
```
출력되는 `https://login.tailscale.com/a/xxxxxxxx` 링크를 브라우저로 열어 `goodmedicine` 노드를 승인.
인증 상태는 `tailscale_state` 볼륨에 저장 → 이후 재기동·재부팅 시 자동 로그인(다시 물어보지 않음).
`docker compose down` 해도 볼륨은 남으므로 재인증 불필요. `down -v` 하면 볼륨이 지워져 재인증해야 함.

### 4. 확인

```cmd
curl https://goodmedicine.tail9f1768.ts.net/health              → {"status":"ok"}
curl https://goodmedicine.tail9f1768.ts.net/api/v1/drugs?q=x     → 403 (인증 필요 — API 정상)
```
`/` 는 404(웹은 Vercel). `/api/docs` 도 404(운영 `DEBUG=false`).
웹 화면은 `https://goodmedicine-hpdice.vercel.app` 에서 확인.

### 5. APK

```cmd
cd C:\Dev\drugTest\front_app
flutter build apk --release --dart-define=BASE_URL=https://goodmedicine.tail9f1768.ts.net/api/v1/
```

---

## 운영

| 상황 | 대응 |
|---|---|
| 백엔드 코드 수정 후 반영 | 개발: `docker compose up -d` (라이브). 배포판: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` |
| 프론트 수정 반영 | `front_app/` 커밋 후 `git push` → GitHub Actions 가 Vercel 로 배포 (`docs/deploy-web-vercel.md`) |
| PC 재부팅 | Docker Desktop 자동시작 + `restart: unless-stopped` → backend·tailscale·터널까지 전부 자동 복구. **수동 조작 없음** |
| Funnel 주소 | 노드명(`goodmedicine`)+tailnet 기준이라 **안 바뀜** |
| 터널만 재시작 | `docker compose -f docker-compose.yml -f docker-compose.prod.yml restart tailscale` |
| serve 설정 변경 | `infrastructure/tailscale/serve.json` 수정 후 tailscale 컨테이너 restart |
| 시연 | PC 절전 해제. 라이브 + 녹화 영상 백업 |

**파일**
- `docker-compose.prod.yml` — `tailscale` 서비스 정의(이미지 `tailscale/tailscale:v1.102.3`, userspace, `tailscale_state` 볼륨)
- `infrastructure/tailscale/serve.json` — Funnel + `/` → `http://backend:8000` 프록시 (`${TS_CERT_DOMAIN}` 은 노드 FQDN 으로 자동 치환)

---

## 노트북에서 임시로 켜기 (같은 주소 그대로)

데스크톱이 주 호스트다. 데스크톱을 못 쓸 때 노트북이 **같은 주소**(`goodmedicine.tail9f1768.ts.net`)로 대신 받는다. Vercel 웹에 박힌 API 주소(`WEB_API_BASE_URL`)를 바꿀 필요가 없다.
핵심은 **Tailscale 노드 이름 `goodmedicine`을 노트북이 이어받게** 하는 것이다. 주소는 노드 이름으로 만들어지므로, 기존(데스크톱) 항목의 이름만 비켜 주면 노트북이 새로 들어와 `goodmedicine`을 받는다.

> ⚠ **한쪽만 켠다.** 데스크톱·노트북이 동시에 같은 이름의 터널을 켜지 않는다. 항상 "한쪽 끄기 → 다른 쪽 켜기".
> ⚠ 노트북에서는 **항상 `docker-compose.laptop.yml`을 같이** 쓴다(없으면 GPU 없는 노트북에서 Ollama까지 켜려고 한다).
> ⚠ **DB는 합쳐지지 않는다.** 노트북에서 가입한 사용자·복약함은 노트북 DB에만 있다.

**준비 (노트북, 미리 1회)**
- `.env`에 `OLLAMA_ENABLED=false` (AI 설명은 폴백 문구로 나간다. Ollama에 연결을 시도하지 않는다).
- `.env`의 `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`가 데스크톱과 **같은지** 확인한다. 다르면 데스크톱에서 만든 토큰·암호화 데이터를 노트북이 못 읽는다.
- `CORS_ORIGINS`에 `https://goodmedicine-hpdice.vercel.app`이 있는지 확인한다.

**켜기 (데스크톱 → 노트북)**
1. Tailscale 관리 페이지(`https://login.tailscale.com/admin/machines`)에서 **Linux** `goodmedicine`(데스크톱 Docker 컨테이너, Windows `drugtest-pc`가 아님)의 `⋯` → **Edit machine name** → `goodmedicine-desktop`으로 변경한다. 이름만 바꾸는 것이고 삭제가 아니다. "Auto-generate from OS hostname"은 꺼 둔다.
2. 노트북에서 터널을 띄운다(`--build`: 노트북 백엔드를 현재 코드로 다시 빌드).
   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.laptop.yml -f docker-compose.prod.yml up -d --build tailscale
   docker logs drugtest-tailscale   # "To authenticate, visit: https://login.tailscale.com/a/…" 가 나온다
   ```
3. 그 로그인 URL을 브라우저에서 승인한다(Tailscale 계정). 관리 페이지에 `goodmedicine`이 **Connected**로 새로 생긴다(`goodmedicine-1`이 되면 1번에서 이름이 안 비켜진 것).
4. 공개 주소가 퍼질 때까지 **몇 분** 걸린다(처음엔 이름만 있고 IP가 없어 응답이 없다). 확인한다.
   ```powershell
   curl.exe -s https://goodmedicine.tail9f1768.ts.net/health   # {"status":"ok","db":"ok"}
   ```

**되돌리기 (노트북 → 데스크톱)**
1. 노트북 터널을 먼저 끈다.
   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.laptop.yml -f docker-compose.prod.yml stop tailscale
   ```
2. 관리 페이지에서 노트북의 `goodmedicine` 항목을 **삭제**하고, `goodmedicine-desktop`의 이름을 `goodmedicine`으로 **되돌린다**.
3. 데스크톱에서 컨테이너를 켠다(데스크톱에서만 실행).
   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```
4. 노트북에 쌓인 가입자를 데스크톱에서도 써야 하면, 1번 전에 노트북에서 `pg_dump`로 덤프해 데스크톱 DB에 복원한다. 짧은 임시 운영이면 버려도 된다.

**노트북 DB를 직접 보고 싶을 때**: `docker-compose.laptop.yml`이 postgres를 이 PC의 `127.0.0.1:5433`에만 연다(밖에서는 접근 불가). DBeaver 등에서 Host `127.0.0.1`, Port `5433`, DB·사용자·비밀번호는 `.env`의 `POSTGRES_*` 값으로 접속한다. 비밀번호는 bcrypt 해시라 DB에서 원문이 보이지 않는 것이 정상이다.

**노트북에서 이 구성이 켜진 동안은** 소스 바인드마운트가 없다(`prod.yml`). 코드를 고치면 `up -d --build`로 다시 빌드해야 반영된다.

---

## 개발용 임시 노출 (선택)

Tailscale 컨테이너 없이 잠깐 외부 공유가 필요하면 (`cloudflared` 설치돼 있음):
```
cloudflared tunnel --url http://localhost:8001
```
→ `https://랜덤.trycloudflare.com` (프로세스 재시작마다 주소 바뀜, 브라우저 경고 페이지 1회).
