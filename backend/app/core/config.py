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

def to_sqlalchemy_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)
