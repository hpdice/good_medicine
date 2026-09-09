# 프론트(Flutter 웹) → Vercel 배포

> **구조**: 프론트는 Vercel(정적 CDN), API 는 국내 PC 백엔드(`https://goodmedicine.tail9f1768.ts.net/api/v1/`).
> 개인정보는 프론트에 없으므로 Vercel(해외) 호스팅은 PIPA 무관 — 저장·처리는 전부 국내 백엔드/DB.
> 백엔드는 API 만 서빙한다(웹 번들 없음). 웹은 Vercel 이 유일한 호스트.

```
git push (front_app/** 변경)
  → GitHub Actions (.github/workflows/deploy-web.yml)
      flutter build web  --dart-define=BASE_URL=<WEB_API_BASE_URL>
      → vercel deploy --prebuilt --prod
  → https://goodmedicine-hpdice.vercel.app   (프론트)
        └─ fetch → https://goodmedicine.tail9f1768.ts.net/api/v1/  (백엔드, 국내 PC)
```

---

## 최초 1회 세팅

### 1. Vercel 프로젝트 생성

- vercel.com → **Add New → Project** → **"Import"가 아니라 빈 프로젝트**로 만들거나,
  레포를 연결하되 **Framework Preset = Other**, Build/Output 설정은 비워둔다
  (실제 빌드는 GitHub Actions 가 하고 `--prebuilt` 로 올린다).
- 도메인은 프로젝트 이름 + 짧은 접미사(이름이 전역에서 겹치면). 실제로 만들어진 주소:
  **`https://goodmedicine-hpdice.vercel.app`** (프로젝트 Settings → Domains 에서 PRODUCTION 확인)

### 2. 로컬에서 프로젝트 ID 얻기

```cmd
npm i -g vercel
cd C:\Dev\drugTest\front_app
vercel link          # 계정 로그인 → 위에서 만든 프로젝트 선택
type .vercel\project.json     # orgId, projectId 확인
```
(`front_app/.vercel/` 는 `.gitignore` 됨 — 커밋 안 됨)

### 3. Vercel 토큰 발급

vercel.com → **Settings → Tokens → Create** → 값 복사.

### 4. GitHub Secrets 등록

레포 → **Settings → Secrets and variables → Actions → New repository secret**:

| 이름 | 값 |
|---|---|
| `VERCEL_TOKEN` | 3번에서 발급한 토큰 |
| `VERCEL_ORG_ID` | `project.json` 의 `orgId` |
| `VERCEL_PROJECT_ID` | `project.json` 의 `projectId` |
| `WEB_API_BASE_URL` | `https://goodmedicine.tail9f1768.ts.net/api/v1/` (끝 슬래시 필수) |

### 5. 백엔드 CORS 열기

이제 프론트(`*.vercel.app`)와 API(`*.ts.net`)가 다른 오리진이라 CORS 설정 필요.
루트 `.env` 에 추가:

```
CORS_ORIGINS=["http://localhost:8081","exp://localhost:8081","https://goodmedicine-hpdice.vercel.app"]
CORS_ORIGIN_REGEX=https://goodmedicine-.*\.vercel\.app
```
(`CORS_ORIGINS` 는 JSON 배열 문자열. 프로덕션 도메인은 정확 목록에, 프리뷰 배포는 정규식으로.)

```cmd
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 6. 첫 배포

레포 **Actions → deploy web (Vercel) → Run workflow** (또는 `front_app/` 아무거나 고쳐 push).
끝나면 `https://goodmedicine-hpdice.vercel.app` 접속 → 로그인 → 약품검색 동작 확인.

---

## 운영

| 상황 | 대응 |
|---|---|
| 프론트 수정 | `git push` → Actions 자동 배포 (front_app/** 경로만 트리거) |
| 백엔드 수정 | 기존대로 PC 에서 `docker compose ... up -d --build` |
| API 주소 변경(터널 등) | `WEB_API_BASE_URL` 시크릿 수정 → 워크플로 재실행. 백엔드 `CORS_ORIGINS` 도 갱신 |
| Vercel 장애 | 웹 폴백 없음 — 급하면 로컬에서 `flutter build web` 후 `cd front_app/build/web && python -m http.server` 로 임시 서빙, 또는 APK 사용 |

## 향후

백엔드를 국내 상시 서버(Oracle Cloud Free 춘천 등)로 옮기면, 백엔드도 GitHub Actions 로
`docker compose pull && up -d` 자동배포 → 프론트·백엔드 모두 push 배포 완성.
