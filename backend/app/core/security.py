import hashlib
import hmac
import secrets
import string
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_auth_settings
from app.core.error_codes import ErrorCode
from app.core.errors import AppError

ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"

hasher = PasswordHasher()   # argon2-cffi 기본값(RFC 9106 권장 프로파일, Argon2id)

# 없는 사번으로 로그인해도 비밀번호 검증 시간을 똑같이 써서 사번 존재 여부가 드러나지 않게 한다
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """맞으면 True. Argon2 가 아닌 옛 해시(시드의 임시 sha256 등)는 항상 False."""
    try:
        return hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return hasher.check_needs_rehash(password_hash)


def burn_verify_time(password: str) -> None:
    verify_password(DUMMY_HASH, password)


# 비밀번호 규칙 (docs/api/01.인증_사용자.md 1.5)
PASSWORD_MIN, PASSWORD_MAX = 8, 64
SPECIALS = string.punctuation
CHAR_CLASSES = (string.ascii_uppercase, string.ascii_lowercase, string.digits, SPECIALS)
POLICY_MESSAGES = {
    "TOO_SHORT": "8자 이상 입력해 주세요.",
    "TOO_LONG": "64자 이하로 입력해 주세요.",
    "INVALID_VALUE": "영문 대·소문자, 숫자, 특수문자 중 3종류 이상을 섞어 주세요.",
    "DUPLICATE": "현재 비밀번호나 사번과 다른 값을 입력해 주세요.",
}


def password_policy_details(new_password: str, employee_no: str, current_password: str) -> list[dict]:
    """규칙 위반 목록 (AUTH_PASSWORD_POLICY_VIOLATION 의 details). 위반이 없으면 []."""
    reasons = []
    if len(new_password) < PASSWORD_MIN:
        reasons.append("TOO_SHORT")
    if len(new_password) > PASSWORD_MAX:
        reasons.append("TOO_LONG")
    if sum(any(c in chars for c in new_password) for chars in CHAR_CLASSES) < 3:
        reasons.append("INVALID_VALUE")
    if new_password in (employee_no, current_password):
        reasons.append("DUPLICATE")
    return [{"field": "newPassword", "reason": r, "message": POLICY_MESSAGES[r]} for r in reasons]


def generate_temporary_password(length: int = 12) -> str:
    """대·소문자·숫자·특수문자를 하나 이상씩 넣은 무작위 임시 비밀번호."""
    chars = [secrets.choice(c) for c in CHAR_CLASSES]
    pool = "".join(CHAR_CLASSES)
    chars += [secrets.choice(pool) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def create_access_token(user_id: int, session_id: int, now: datetime | None = None) -> tuple[str, int]:
    now = now or datetime.now(timezone.utc)
    expires_in = get_auth_settings().access_token_minutes * 60
    claims = {
        "sub": str(user_id),
        "sid": session_id,
        "typ": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(claims, get_auth_settings().jwt_secret, algorithm=ALGORITHM), expires_in


def decode_access_token(token: str) -> tuple[int, int]:
    """(user_id, session_id). 만료면 TOKEN_EXPIRED, 그 밖의 문제는 UNAUTHORIZED."""
    try:
        claims = jwt.decode(
            token, get_auth_settings().jwt_secret, algorithms=[ALGORITHM],
            options={"require": ["sub", "sid", "typ", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        raise AppError(ErrorCode.TOKEN_EXPIRED)
    except jwt.InvalidTokenError:
        raise AppError(ErrorCode.UNAUTHORIZED)
    if claims["typ"] != ACCESS_TOKEN_TYPE or not isinstance(claims["sid"], int):
        raise AppError(ErrorCode.UNAUTHORIZED)
    try:
        return int(claims["sub"]), claims["sid"]
    except ValueError:
        raise AppError(ErrorCode.UNAUTHORIZED)


# ---------------------------------------------------------------- Refresh Token

def new_refresh_token(session_id: int) -> tuple[str, str]:
    """(쿠키에 줄 토큰 '<세션 id>.<무작위 값>', DB 에 저장할 해시)."""
    token = f"{session_id}.{secrets.token_urlsafe(32)}"
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    # 무작위 값이 충분히 길어 느린 해시가 필요 없다
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_token_matches(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_refresh_token(token), token_hash)


def refresh_session_id(token: str) -> int | None:
    sid, _, secret = token.partition(".")
    return int(sid) if sid.isdigit() and secret else None
