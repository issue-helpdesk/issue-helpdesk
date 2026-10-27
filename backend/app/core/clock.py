"""현재 시각. 테스트에서 시간을 옮길 수 있도록 datetime.now 를 직접 부르지 않고 여기를 쓴다."""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """시간대 없는 값(SQLite 테스트 DB)은 UTC 로 본다."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def to_kst(value: datetime) -> datetime:
    return as_utc(value).astimezone(KST)
