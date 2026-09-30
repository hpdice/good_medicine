# secrets/

런타임 비밀 파일을 두는 곳. **이 README 말고는 Git에 올라가지 않는다**(`.gitignore`), 이미지에도 들어가지 않는다
(`.dockerignore`). `docker compose`가 이 폴더를 backend 컨테이너의 `/run/secrets`에 **읽기 전용**으로 연결한다.

| 파일 | 용도 | 없으면 |
|---|---|---|
| `firebase-service-account.json` | 병용금기 푸시 알림(FCM) 발송 | 푸시만 꺼지고 나머지는 정상 (로그: `FCM push notifications: disabled`) |

만드는 법: Firebase Console → 프로젝트 설정 → 서비스 계정 → **새 비공개 키 생성** → 이 폴더에 위 이름으로 저장.

> `.env`의 `SECRET_KEY`·`FIELD_ENCRYPTION_KEY`는 여기가 아니라 `.env`에 있다. 두 값의 **별도 보관** 방법은
> `docs/operations.md` 3절.
