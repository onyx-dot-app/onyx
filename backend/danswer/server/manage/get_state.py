from fastapi import APIRouter
from fastapi import Depends

from danswer import __version__
from danswer.auth.api_key import validate_api_key
from danswer.auth.users import user_needs_to_be_verified
from danswer.configs.app_configs import AUTH_TYPE
from danswer.server.manage.models import AuthTypeResponse
from danswer.server.manage.models import VersionResponse
from danswer.server.models import StatusResponse

router = APIRouter(dependencies=[Depends(validate_api_key)])


@router.get("/health")
def healthcheck() -> StatusResponse:
    return StatusResponse(success=True, message="ok")


@router.get("/auth/type")
def get_auth_type() -> AuthTypeResponse:
    return AuthTypeResponse(
        auth_type=AUTH_TYPE, requires_verification=user_needs_to_be_verified()
    )


@router.get("/version")
def get_version() -> VersionResponse:
    return VersionResponse(backend_version=__version__)
