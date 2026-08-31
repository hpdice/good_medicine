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
    DUR_INGREDIENT_API_URL: str = "http://apis.data.go.kr/1471000/DURIrdntInfoService"
    DRUG_APPROVAL_API_URL: str = "https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07"

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 필드 암호화 키 (AES-256-GCM) - 32바이트 hex
    FIELD_ENCRYPTION_KEY: str

    # App
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:8081", "exp://localhost:8081"]

    # Rate Limiting
    LOGIN_RATE_LIMIT: str = "5/15minutes"
    DEFAULT_RATE_LIMIT: str = "60/minute"
    ANALYSIS_RATE_LIMIT: str = "10/minute"

    # FCM 푸시 알림 — Firebase 서비스 계정 키 JSON 경로 (미설정 시 푸시 기능 비활성화)
    FIREBASE_CREDENTIALS_JSON: str = ""

    # 로컬 LLM (Ollama) — AI 대응 가이드 생성용. 위험도 "판정"에는 관여하지 않음
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


settings = Settings()
