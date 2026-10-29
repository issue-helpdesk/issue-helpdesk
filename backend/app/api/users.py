from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.auth import clear_refresh_cookie
from app.api.deps import AdminAuth, CurrentAuthAllowTempPassword
from app.schemas.auth import Me, PasswordChangeRequest
from app.schemas.common import Page
from app.schemas.user import (
    TemporaryPasswordRequest,
    TemporaryPasswordResponse,
    User,
    UserCreateRequest,
    UserCreateResponse,
    UserListQuery,
    UserSummary,
    UserUpdateRequest,
)
from app.services.auth import AuthServiceDep
from app.services.user import UserServiceDep

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=Me)
def get_me(auth: CurrentAuthAllowTempPassword, service: UserServiceDep) -> Me:
    return service.get_me(auth.user)


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChangeRequest, auth: CurrentAuthAllowTempPassword, service: AuthServiceDep, response: Response,
) -> None:
    service.change_password(auth.user, body.current_password, body.new_password)
    clear_refresh_cookie(response)


@router.get("", response_model=Page[UserSummary])
def list_users(query: Annotated[UserListQuery, Query()], _: AdminAuth, service: UserServiceDep) -> Page[UserSummary]:
    return service.list_users(query)


@router.post("", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreateRequest, admin: AdminAuth, service: UserServiceDep) -> UserCreateResponse:
    return service.create_user(body, admin.user)


@router.get("/{user_id}", response_model=User)
def get_user(user_id: int, _: AdminAuth, service: UserServiceDep) -> User:
    return service.get_user(user_id)


@router.patch("/{user_id}", response_model=User)
def update_user(user_id: int, body: UserUpdateRequest, admin: AdminAuth, service: UserServiceDep) -> User:
    return service.update_user(user_id, body, admin.user)


@router.post("/{user_id}/temporary-password", response_model=TemporaryPasswordResponse,
             status_code=status.HTTP_201_CREATED)
def reset_password(
    user_id: int, admin: AdminAuth, service: UserServiceDep, body: TemporaryPasswordRequest | None = None,
) -> TemporaryPasswordResponse:
    return service.reset_password(user_id, body.reason if body else None, admin.user)
