import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

class Settings:
    def __init__(self) -> None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL 이 없습니다. 루트 .env 를 확인하세요.")
        self.database_url = to_sqlalchemy_url(url)
        self.dsn = url                      # psycopg 로 바로 붙는 곳(문서 적재)이 쓴다
        # Supabase Session 모드는 쉬는 연결도 한도를 차지한다. 개발 PC 는 .env 에서 더 작게 준다
        self.db_pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
        self.db_max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "5"))

@lru_cache
def get_settings() -> Settings:
    return Settings()

class JiraSettings:
    """Jira(ITHD) 연동 설정. 값은 서버 .env 에만 둔다."""

    def __init__(self) -> None:
        names = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")
        missing = [n for n in names if not os.environ.get(n)]
        if missing:
            raise RuntimeError(f"{', '.join(missing)} 이 없습니다. 루트 .env 를 확인하세요.")
        self.base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
        self.email = os.environ["JIRA_EMAIL"]
        self.api_token = os.environ["JIRA_API_TOKEN"]

@lru_cache
def get_jira_settings() -> JiraSettings:
    return JiraSettings()

def get_jira_webhook_secret() -> str | None:
    """Jira 웹훅 서명 비밀값. 없으면 모든 웹훅을 거절한다."""
    return os.environ.get("JIRA_WEBHOOK_SECRET") or None

class AuthSettings:

    def __init__(self) -> None:
        secret = os.environ.get("JWT_SECRET")
        if not secret or len(secret) < 32:
            raise RuntimeError("JWT_SECRET 이 없거나 32자 미만입니다. 루트 .env 를 확인하세요.")
        self.jwt_secret = secret
        self.access_token_minutes = int(os.environ.get("ACCESS_TOKEN_MINUTES", "30"))
        self.refresh_token_days = int(os.environ.get("REFRESH_TOKEN_DAYS", "7"))
        # 로컬 http 개발에서만 false. 배포 환경은 https 이므로 true 를 유지한다
        self.refresh_cookie_secure = os.environ.get("REFRESH_COOKIE_SECURE", "true").lower() != "false"

@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()

def to_sqlalchemy_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)
