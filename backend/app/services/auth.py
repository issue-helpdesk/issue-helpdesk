from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends

from app.utils import datetime_utils
from app.core.config import get_auth_settings
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.core.security import (
    burn_verify_time,
    create_access_token,
    decode_access_token,
    hash_password,
    needs_rehash,
    new_refresh_token,
    password_policy_details,
    refresh_session_id,
    refresh_token_matches,
    verify_password,
)
from app.db.session import DbSession
from app.models import AuthSession, User
from app.repositories.audit_log import AuditLogRepositoryDep
from app.repositories.auth_session import AuthSessionRepositoryDep
from app.repositories.user import UserRepositoryDep
from app.schemas.auth import Me
from app.services.user import UserServiceDep, unlock

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 10


@dataclass
class AuthContext:
    user: User
    session: AuthSession


@dataclass
class IssuedTokens:
    me: Me
    access_token: str
    expires_in: int
    refresh_token: str


class AuthService:

    def __init__(
        self,
        db: DbSession,
        users: UserRepositoryDep,
        sessions: AuthSessionRepositoryDep,
        audit_logs: AuditLogRepositoryDep,
        user_service: UserServiceDep,
    ) -> None:
        self.db = db
        self.users = users
        self.sessions = sessions
        self.audit_logs = audit_logs
        self.user_service = user_service

    def login(self, employee_no: str, password: str) -> IssuedTokens:
        # 실패 횟수를 동시에 올리지 않도록 사용자 행을 잠근다
        user = self.users.find_by_employee_no_for_update(employee_no)
        if user is None:
            burn_verify_time(password)
            raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS)

        now = datetime_utils.now()
        if user.account_status == "LOCKED" and user.locked_until and datetime_utils.as_utc(user.locked_until) <= now:
            unlock(user)

        if user.account_status in ("LOCKED", "INACTIVE"):
            self.audit_logs.add("LOGIN_BLOCKED", "user", user.id, result=user.account_status)
            self.db.commit()
            raise blocked_error(user)

        if not verify_password(user.password_hash, password):
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.account_status = "LOCKED"
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                self.audit_logs.add("ACCOUNT_LOCKED", "user", user.id, result="LOCKED")
                self.db.commit()
                raise blocked_error(user)
            self.db.commit()
            raise AppError(ErrorCode.AUTH_INVALID_CREDENTIALS)

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        session = self.sessions.add(AuthSession(user_id=user.id, refresh_token_hash="", expires_at=refresh_expiry(now)))
        tokens = self.issue_tokens(user, session, now)
        self.db.commit()
        return tokens

    def refresh(self, refresh_token: str | None) -> IssuedTokens:
        """이미 바뀐(사용한) Refresh Token 이 다시 오면 탈취로 보고 그 세션을 폐기한다."""
        sid = refresh_session_id(refresh_token) if refresh_token else None
        session = self.sessions.get_for_update(sid) if sid else None
        if session is None or session.revoked_at is not None:
            raise AppError(ErrorCode.AUTH_REFRESH_TOKEN_INVALID)

        now = datetime_utils.now()
        if not refresh_token_matches(refresh_token, session.refresh_token_hash):
            revoke(session, "TOKEN_REUSE", now)
            self.db.commit()
            raise AppError(ErrorCode.AUTH_REFRESH_TOKEN_INVALID)
        if datetime_utils.as_utc(session.expires_at) <= now:
            raise AppError(ErrorCode.AUTH_REFRESH_TOKEN_INVALID)

        user = self.users.get(session.user_id)
        if user.account_status == "INACTIVE":
            raise AppError(ErrorCode.AUTH_ACCOUNT_INACTIVE)

        session.expires_at = refresh_expiry(now)
        session.refreshed_at = now
        tokens = self.issue_tokens(user, session, now)
        self.db.commit()
        return tokens

    def logout(self, session: AuthSession) -> None:
        revoke(session, "LOGOUT", datetime_utils.now())
        self.db.commit()

    def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(user.password_hash, current_password):
            raise AppError(ErrorCode.AUTH_CURRENT_PASSWORD_MISMATCH)
        details = password_policy_details(new_password, user.employee_no, current_password)
        if details:
            raise AppError(ErrorCode.AUTH_PASSWORD_POLICY_VIOLATION, details)

        now = datetime_utils.now()
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        user.updated_at = now
        self.sessions.revoke_all(user.id, "PASSWORD_CHANGE", now)
        self.db.commit()

    def authenticate(self, access_token: str | None, allow_temp_password: bool = False) -> AuthContext:
        if access_token is None:
            raise AppError(ErrorCode.UNAUTHORIZED)
        user_id, session_id = decode_access_token(access_token)

        # 로그아웃·비밀번호 변경으로 폐기된 세션의 토큰은 만료 전이라도 거부한다
        session = self.sessions.get(session_id)
        if (
            session is None
            or session.user_id != user_id
            or session.revoked_at is not None
            or datetime_utils.as_utc(session.expires_at) <= datetime_utils.now()
        ):
            raise AppError(ErrorCode.UNAUTHORIZED)

        # 계정 상태·권한은 토큰이 아니라 DB 의 현재 값으로 판단한다
        user = self.users.get(user_id)
        if user.account_status == "INACTIVE":
            raise AppError(ErrorCode.AUTH_ACCOUNT_INACTIVE)
        if not allow_temp_password and user.password_changed_at is None:
            raise AppError(ErrorCode.AUTH_PASSWORD_CHANGE_REQUIRED)
        return AuthContext(user, session)

    def issue_tokens(self, user: User, session: AuthSession, now: datetime) -> IssuedTokens:
        refresh_token, session.refresh_token_hash = new_refresh_token(session.id)
        access_token, expires_in = create_access_token(user.id, session.id, now)
        return IssuedTokens(self.user_service.get_me(user), access_token, expires_in, refresh_token)


AuthServiceDep = Annotated[AuthService, Depends(AuthService)]


def blocked_error(user: User) -> AppError:
    if user.account_status == "INACTIVE":
        return AppError(ErrorCode.AUTH_ACCOUNT_INACTIVE)
    until = datetime_utils.to_kst(user.locked_until).isoformat() if user.locked_until else None
    return AppError(
        ErrorCode.AUTH_ACCOUNT_LOCKED,
        [{"reason": "LOCKED_UNTIL", "message": "잠금 해제 시각", "value": until}],
    )


def refresh_expiry(now: datetime) -> datetime:
    return now + timedelta(days=get_auth_settings().refresh_token_days)


def revoke(session: AuthSession, reason: str, now: datetime) -> None:
    session.revoked_at = now
    session.revoke_reason = reason
