from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from danswer import __version__
from danswer.auth.users import user_needs_to_be_verified
from danswer.configs.app_configs import AUTH_TYPE
from danswer.server.manage.models import AuthTypeResponse
from danswer.server.manage.models import VersionResponse
from danswer.server.models import StatusResponse
from danswer.server.manage.connectors_state import get_connectors_state

from danswer.db.engine import get_session
from danswer.db.engine import get_current_tenant_id
from danswer.db.enums import ConnectorCredentialPairStatus
from danswer.db.models import IndexingStatus

router = APIRouter()


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

@router.get("/connectors_health")
def connectors_healthcheck(
    db_session: Session = Depends(get_session),
    tenant_id: str | None = Depends(get_current_tenant_id),
) -> StatusResponse:
    success = True
    message = "ok"

    states = get_connectors_state(db_session, tenant_id)
    error_cnt = 0
    for state in states:
        if state.cc_pair_status == ConnectorCredentialPairStatus.ACTIVE and \
            state.last_finished_status == IndexingStatus.FAILED:
            error_cnt += 1
    if error_cnt > 0:
        success = False
        message = f"{error_cnt} of {len(states)} connectors failed"
    return StatusResponse(success=success, message=message)
