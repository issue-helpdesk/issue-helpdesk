from typing import Annotated

from fastapi import APIRouter, Cookie, Response, status

from app.api.deps import CurrentAuthAllowTempPassword
from app.core.config import get_auth_settings
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.auth import AuthServiceDep, IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])


REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_auth_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    settings = get_auth_settings()
    response.delete_cookie(
        REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, secure=settings.refresh_cookie_secure, httponly=True, samesite="strict",
    )


def token_response(response: Response, tokens: IssuedTokens) -> TokenResponse:
    set_refresh_cookie(response, tokens.refresh_token)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in, user=tokens.me)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, service: AuthServiceDep, response: Response) -> TokenResponse:
    return token_response(response, service.login(body.employee_no, body.password))


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    service: AuthServiceDep,
    response: Response,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> TokenResponse:
    return token_response(response, service.refresh(refresh_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(auth: CurrentAuthAllowTempPassword, service: AuthServiceDep, response: Response) -> None:
    service.logout(auth.session)
    clear_refresh_cookie(response)
