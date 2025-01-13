import uuid
from typing import Annotated
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import OAuthConnector
from onyx.db.credentials import create_credential
from onyx.db.engine import get_current_tenant_id
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import CredentialBase
from onyx.utils.logger import setup_logger
from onyx.utils.subclasses import find_all_subclasses_in_dir

logger = setup_logger()

router = APIRouter(prefix="/connector/oauth")

_OAUTH_STATE_KEY_FMT = "oauth_state:{state}"
_OAUTH_STATE_EXPIRATION_SECONDS = 10 * 60  # 10 minutes

# Cache for OAuth connectors, populated at module load time
_OAUTH_CONNECTORS: dict[DocumentSource, type[OAuthConnector]] = {}


def _discover_oauth_connectors() -> dict[DocumentSource, type[OAuthConnector]]:
    """Walk through the connectors package to find all OAuthConnector implementations"""
    global _OAUTH_CONNECTORS
    if _OAUTH_CONNECTORS:  # Return cached connectors if already discovered
        return _OAUTH_CONNECTORS

    oauth_connectors = find_all_subclasses_in_dir(
        cast(type[OAuthConnector], OAuthConnector), "onyx.connectors"
    )

    _OAUTH_CONNECTORS = {cls.oauth_id(): cls for cls in oauth_connectors}
    return _OAUTH_CONNECTORS


# Discover OAuth connectors at module load time
_discover_oauth_connectors()


class AuthorizeResponse(BaseModel):
    redirect_url: str


@router.get("/authorize/{source}")
def oauth_authorize(
    source: DocumentSource,
    desired_return_url: Annotated[str | None, Query()] = None,
    _: User = Depends(current_user),
    tenant_id: str | None = Depends(get_current_tenant_id),
) -> AuthorizeResponse:
    """Initiates the OAuth flow by redirecting to the provider's auth page"""
    oauth_connectors = _discover_oauth_connectors()

    if source not in oauth_connectors:
        raise HTTPException(status_code=400, detail=f"Unknown OAuth source: {source}")

    connector_cls = oauth_connectors[source]
    base_url = WEB_DOMAIN

    # store state in redis
    if not desired_return_url:
        desired_return_url = f"{base_url}/admin/connectors/{source}?step=0"
    redis_client = get_redis_client(tenant_id=tenant_id)
    state = str(uuid.uuid4())
    redis_client.set(
        _OAUTH_STATE_KEY_FMT.format(state=state),
        desired_return_url,
        ex=_OAUTH_STATE_EXPIRATION_SECONDS,
    )

    return AuthorizeResponse(
        redirect_url=connector_cls.oauth_authorization_url(base_url, state)
    )


class CallbackResponse(BaseModel):
    redirect_url: str


@router.get("/callback/{source}")
def oauth_callback(
    source: DocumentSource,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    db_session: Session = Depends(get_session),
    user: User = Depends(current_user),
    tenant_id: str | None = Depends(get_current_tenant_id),
) -> CallbackResponse:
    """Handles the OAuth callback and exchanges the code for tokens"""
    oauth_connectors = _discover_oauth_connectors()

    if source not in oauth_connectors:
        raise HTTPException(status_code=400, detail=f"Unknown OAuth source: {source}")

    connector_cls = oauth_connectors[source]

    # get state from redis
    redis_client = get_redis_client(tenant_id=tenant_id)
    original_url_bytes = cast(
        bytes, redis_client.get(_OAUTH_STATE_KEY_FMT.format(state=state))
    )
    if not original_url_bytes:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    original_url = original_url_bytes.decode("utf-8")

    base_url = WEB_DOMAIN
    token_info = connector_cls.oauth_code_to_token(base_url, code)

    # Create a new credential with the token info
    credential_data = CredentialBase(
        credential_json=token_info,
        admin_public=True,  # Or based on some logic/parameter
        source=source,
        name=f"{source.title()} OAuth Credential",
    )

    credential = create_credential(
        credential_data=credential_data,
        user=user,
        db_session=db_session,
    )

    return CallbackResponse(
        redirect_url=(
            f"{original_url}?credentialId={credential.id}"
            if "?" not in original_url
            else f"{original_url}&credentialId={credential.id}"
        )
    )
