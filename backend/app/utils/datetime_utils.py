from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """시간대 없는 값(SQLite 테스트 DB)은 UTC 로 본다."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def to_kst(value: datetime) -> datetime:
    return as_utc(value).astimezone(KST)


def kst_start(day: date) -> datetime:
    return datetime.combine(day, time.min, KST).astimezone(timezone.utc)
