from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuthSession(Base):
    """로그인 세션. Access Token 의 sid 가 이 행을 가리키고, 행이 폐기되면 토큰도 바로 쓸 수 없다."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "revoke_reason in ('LOGOUT', 'PASSWORD_CHANGE', 'PASSWORD_RESET', 'TOKEN_REUSE')",
            name="revoke_reason",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    refresh_token_hash: Mapped[str]              # 현재 유효한 Refresh Token 의 SHA-256. 재발급마다 바뀐다
    expires_at: Mapped[datetime]                 # Refresh Token 만료 시각. 재발급마다 연장
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    refreshed_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoke_reason: Mapped[str | None]
