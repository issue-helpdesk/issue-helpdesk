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

class AuthSettings:
    """로그인 토큰 설정. JWT_SECRET 은 서버 .env 에만 둔다."""

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
