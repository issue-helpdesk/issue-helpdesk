from fastapi import APIRouter, Response, status

from app.api.auth import clear_refresh_cookie
from app.api.deps import CurrentAuthAllowTempPassword
from app.schemas.auth import Me, PasswordChangeRequest
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
