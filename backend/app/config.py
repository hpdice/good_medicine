from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=["../.env", ".env"], extra="ignore")

    # Database
    DATABASE_URL: str

    # 공공데이터포털 API (데이터 적재 전용)
    PUBLIC_DATA_API_KEY: str = ""
    DRUG_OVERVIEW_API_URL: str = "http://apis.data.go.kr/1471000/DrbEasyDrugInfoService"
    DRUG_IDENTIFY_API_URL: str = "http://apis.data.go.kr/1471000/MdcinGrnIdntfcInfoService03"
    DUR_PRODUCT_API_URL: str = "http://apis.data.go.kr/1471000/DURPrdlstInfoService03"
    DRUG_APPROVAL_API_URL: str = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07"

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # bcrypt 코스트 팩터. 운영 12 유지, 테스트는 conftest 에서 4 로 낮춰 속도 확보.
    BCRYPT_ROUNDS: int = 12

    # 필드 암호화 키 (AES-256-GCM) - 32바이트 hex
    FIELD_ENCRYPTION_KEY: str

    # App
    DEBUG: bool = False
    # 백엔드가 웹 번들을 같은 오리진에서 서빙하면 CORS 불필요. 프론트를 Vercel 등 별도
    # 호스트에 올리면 그 오리진을 CORS_ORIGINS(정확 목록, .env 에 JSON 배열)에 추가하고,
    # 매번 서브도메인이 바뀌는 프리뷰 배포는 CORS_ORIGIN_REGEX 로 허용한다
    # (예: CORS_ORIGIN_REGEX=https://.*\.vercel\.app).
    CORS_ORIGINS: list[str] = ["http://localhost:8081", "exp://localhost:8081"]
    CORS_ORIGIN_REGEX: str = ""

    # Rate Limiting
    # IP 단위 — 성공한 로그인도 센다. 자동화된 폭주 방어용이라 넉넉히 잡는다(같은 공유기·행사장
    # 와이파이 뒤의 여러 사용자가 한 IP로 묶인다). 비밀번호 무차별 대입 방어는 아래 계정별 실패 제한이 맡는다.
    LOGIN_RATE_LIMIT: str = "20/15minutes"
    # 계정(이메일) 단위 — 실패한 로그인만 센다(app/core/login_guard.py).
    LOGIN_FAILURE_LIMIT: int = 5
    LOGIN_FAILURE_WINDOW_SECONDS: int = 900
    DEFAULT_RATE_LIMIT: str = "60/minute"
    ANALYSIS_RATE_LIMIT: str = "10/minute"
    OCR_RATE_LIMIT: str = "20/minute"
    # X-Forwarded-For 를 믿어도 되는 직접 연결 상대(= 리버스 프록시)의 대역.
    # backend 포트는 호스트 127.0.0.1 에만 열려 있어, 여기 닿는 건 compose 네트워크 안의
    # tailscale 컨테이너와 호스트 로컬 프로세스(도커 게이트웨이 경유)뿐이다.
    TRUSTED_PROXY_CIDRS: list[str] = [
        "127.0.0.1/32", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    ]

    # 공공데이터 동기화 상태(체크포인트·마지막 성공 시각). compose 의 sync_state 볼륨에 마운트 —
    # 컨테이너를 재생성해도 유지된다.
    SYNC_STATE_DIR: str = "/var/lib/goodmedicine"
    # 공공 API 원본 응답(bronze) 보관 — SYNC_STATE_DIR/raw/<엔드포인트>/<YYYYMMDD>/page_NNNNNN.json.gz.
    # 파싱 로직을 고치거나 새 필드가 필요할 때 7시간짜리 재동기화 대신 `sync.py <소스> --replay`로 재파싱한다.
    RAW_RESPONSE_SAVE: bool = True
    RAW_KEEP_SNAPSHOTS: int = 3  # 엔드포인트별로 최근 N개 날짜 스냅샷만 유지

    # 처방전/약봉투 OCR — 이미지는 메모리에서만 처리하고 OCR 직후 폐기(디스크·DB 저장 없음).
    OCR_MAX_IMAGE_BYTES: int = 8 * 1024 * 1024  # 8MB 초과 업로드는 거부
    OCR_TESSERACT_LANG: str = "kor+eng"

    # FCM 푸시 알림 — Firebase 서비스 계정 키 JSON 경로 (미설정 시 푸시 기능 비활성화)
    FIREBASE_CREDENTIALS_JSON: str = ""

    # 로컬 LLM (Ollama) — AI 대응 가이드 생성용. 위험도 "판정"에는 관여하지 않음
    # False면 Ollama를 아예 부르지 않는다 — 워밍업 루프를 띄우지 않고, AI 설명 요청은 시도 없이
    # 곧바로 폴백 문구로 답한다. GPU가 없어 Ollama 컨테이너가 없는 환경(노트북)용.
    OLLAMA_ENABLED: bool = True
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "qwen2.5:14b-instruct"
    # 실측(RTX 4070): 콜드스타트(모델을 GPU에 새로 올림) 87~153초, 워밍 후 10~15초.
    # 90초로 뒀다가 콜드스타트 중 타임아웃으로 불필요한 폴백이 발생하는 걸 실측으로
    # 확인해 여유있게 조정 (Flutter 쪽 receiveTimeout도 이보다 커야 함).
    OLLAMA_TIMEOUT_SECONDS: float = 200.0
    # keep_alive(30분)보다 짧은 주기로 조용히 핑을 보내 모델이 GPU에서 내려가기 전에
    # 계속 갱신되게 한다 — 콜드스타트(87~153초)가 실제 사용자 요청에서 거의 발생하지
    # 않게 하려는 목적. 백엔드가 떠 있는 동안만 유효(재시작 직후엔 첫 워밍업 전까지
    # 여전히 콜드스타트가 발생할 수 있음).
    OLLAMA_KEEPALIVE_INTERVAL_SECONDS: float = 600.0
    # 백엔드 재시작 직후 첫 워밍업 호출 전용 타임아웃 — 이때는 Ollama 컨테이너도
    # 막 같이 뜬 완전 콜드 상태라 OLLAMA_TIMEOUT_SECONDS(200초)로도 부족한 경우가
    # 실측으로 확인됨 (백엔드 시작 후 3분20초경 반복적으로 abort → 클라이언트가
    # 연결을 끊으면 Ollama가 로딩 중이던 모델 메모리를 회수하지 못하고 컨테이너가
    # 재시작 전까지 계속 들고 있는 문제로 이어짐). 사용자 요청을 막는 게 아니라
    # 백그라운드 루프에서만 쓰이므로 여유있게 잡아도 비용이 없다.
    OLLAMA_WARMUP_TIMEOUT_SECONDS: float = 500.0
    # 생성 옵션 — Ollama 기본값(temperature 0.8)에서는 같은 입력으로 10번 중 5번꼴로
    # 마크다운·"복용 중단" 권유·중국어 섞임이 나왔다(2026-10-15 실측). 설명문은
    # 다양성보다 일관성이 중요하므로 낮게 둔다. num_predict는 장황한 답·폭주 방지 상한.
    OLLAMA_TEMPERATURE: float = 0.2
    OLLAMA_NUM_PREDICT: int = 600


# 필수 값은 환경변수/.env 에서 채워진다 — 검사기는 이를 알 수 없어 인자 누락으로 본다.
settings = Settings()  # pyright: ignore[reportCallIssue]
