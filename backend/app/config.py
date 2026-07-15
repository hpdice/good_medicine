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

    # FCM 푸시 알림 — Firebase 서비스 계정 키 JSON 경로 (미설정 시 푸시 기능 비활성화)
    FIREBASE_CREDENTIALS_JSON: str = ""


settings = Settings()
