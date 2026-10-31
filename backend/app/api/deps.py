from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.services.auth import AuthContext, AuthServiceDep

bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def access_token(credentials: Credentials) -> str | None:
    return credentials.credentials if credentials else None


def get_current_auth(credentials: Credentials, service: AuthServiceDep) -> AuthContext:
    return service.authenticate(access_token(credentials))


def get_auth_allow_temp_password(credentials: Credentials, service: AuthServiceDep) -> AuthContext:
    return service.authenticate(access_token(credentials), allow_temp_password=True)


def require_admin(auth: Annotated[AuthContext, Depends(get_current_auth)]) -> AuthContext:
    if auth.user.service_role != "ADMIN":
        raise AppError(ErrorCode.FORBIDDEN)
    return auth


def require_agent(auth: Annotated[AuthContext, Depends(get_current_auth)]) -> AuthContext:
    if auth.user.service_role not in ("AGENT", "ADMIN"):
        raise AppError(ErrorCode.FORBIDDEN)
    return auth


CurrentAuth = Annotated[AuthContext, Depends(get_current_auth)]
CurrentAuthAllowTempPassword = Annotated[AuthContext, Depends(get_auth_allow_temp_password)]
AdminAuth = Annotated[AuthContext, Depends(require_admin)]
AgentAuth = Annotated[AuthContext, Depends(require_agent)]

