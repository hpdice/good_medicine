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

데스크톱이 주 호스트다. 데스크톱을 못 쓸 때 노트북이 **같은 주소**(`goodmedicine.tail9f1768.ts.net`)로 대신 받는다.
Vercel 웹에 박힌 API 주소(`WEB_API_BASE_URL`)를 바꿀 필요가 없다. 핵심은 **Tailscale 노드 신원(`tailscale_state` 볼륨)을 노트북으로 옮겨 같은 노드로 로그인**하는 것이다.

> ⚠ **동시에 두 곳에서 켜지 않는다.** 같은 노드를 두 PC가 쓰면 Funnel 주소가 번갈아 끊긴다. 항상 "한쪽 끄기 → 다른 쪽 켜기" 순서.
> ⚠ `tailscale_state`에는 노드 키가 들어 있다(비밀). 옮긴 파일(`tailscale_state.tgz`)은 USB 등으로만 옮기고 git·메신저에 올리지 않으며, 다 쓰면 지운다.

**준비 (노트북에서 미리 1회)**
- 노트북 `.env`가 데스크톱과 **같은 비밀값**(JWT 서명 키, 암호화 키 등)을 쓰는지 확인한다. 다르면 데스크톱에서 만든 토큰·암호화 데이터를 노트북이 못 읽는다.
- 노트북 `.env`의 CORS 허용 목록에 `https://goodmedicine-hpdice.vercel.app`이 있는지 확인한다(`CORS_ORIGINS`).
- GPU가 없으면 `.env`에 `OLLAMA_ENABLED=false` (AI 설명은 폴백 문구로 나간다).

**데스크톱 → 노트북 (켜기)**
```powershell
# [데스크톱] 터널을 끄고 노드 상태를 파일로 꺼낸다
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop tailscale
docker run --rm -v drugtest_tailscale_state:/s -v ${PWD}:/out alpine tar czf /out/tailscale_state.tgz -C /s .
# → tailscale_state.tgz 를 노트북으로 복사

# [노트북] 상태를 볼륨에 넣고 운영 구성으로 띄운다
docker volume create drugtest_tailscale_state
docker run --rm -v drugtest_tailscale_state:/s -v ${PWD}:/in alpine tar xzf /in/tailscale_state.tgz -C /s
docker compose -f docker-compose.yml -f docker-compose.laptop.yml -f docker-compose.prod.yml up -d
curl.exe -s https://goodmedicine.tail9f1768.ts.net/health   # {"status":"ok","db":"ok"}
```
다시 인증(로그인 URL)을 묻지 않아야 정상이다. 물으면 상태 복사가 안 된 것이다.

**노트북 → 데스크톱 (되돌리기)**
```powershell
# [노트북] 터널부터 끈다
docker compose -f docker-compose.yml -f docker-compose.laptop.yml -f docker-compose.prod.yml stop tailscale
# [데스크톱]
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d tailscale
```
되돌릴 때는 파일을 다시 옮길 필요가 없다(데스크톱의 볼륨은 그대로). 노트북에 남은 `tailscale_state.tgz`와 볼륨은 삭제한다: `docker volume rm drugtest_tailscale_state`.

**데이터는 합쳐지지 않는다.** 노트북에서 가입한 사용자·복약함은 **노트북 DB**에만 있다. 데스크톱으로 돌아가면 보이지 않는다.
임시 운영 기간이 짧으면 그대로 두고, 이어서 써야 하면 `pg_dump`로 옮긴다(되돌리기 전에 노트북에서 덤프 → 데스크톱에서 복원).

---

## 개발용 임시 노출 (선택)

Tailscale 컨테이너 없이 잠깐 외부 공유가 필요하면 (`cloudflared` 설치돼 있음):
```
cloudflared tunnel --url http://localhost:8001
```
→ `https://랜덤.trycloudflare.com` (프로세스 재시작마다 주소 바뀜, 브라우저 경고 페이지 1회).
