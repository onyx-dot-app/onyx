from fastapi import APIRouter

from onyx import __version__
from onyx.auth.users import anonymous_user_enabled
from onyx.auth.users import user_needs_to_be_verified
from onyx.configs.app_configs import AUTH_TYPE
from onyx.server.manage.models import AuthTypeResponse
from onyx.server.manage.models import VersionResponse
from onyx.server.models import StatusResponse
from onyx.utils.eea_utils import get_connectors_health

from fastapi import Depends
from sqlalchemy.orm import Session
from onyx.db.engine.sql_engine import get_session
#from shared_configs.contextvars import get_current_tenant_id
from onyx.auth.users import current_curator_or_admin_user
from onyx.db.models import User

router = APIRouter()


@router.get("/health")
def healthcheck() -> StatusResponse:
    return StatusResponse(success=True, message="ok")


@router.get("/auth/type")
def get_auth_type() -> AuthTypeResponse:
    return AuthTypeResponse(
        auth_type=AUTH_TYPE,
        requires_verification=user_needs_to_be_verified(),
        anonymous_user_enabled=anonymous_user_enabled(),
    )


@router.get("/version")
def get_version() -> VersionResponse:
    return VersionResponse(backend_version=__version__)

@router.get("/connectors_health")
def connectors_healthcheck(
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    return get_connectors_health(user=user, db_session=db_session)
