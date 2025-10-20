import json
import uuid
from typing import Annotated
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from pydantic import BaseModel
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import OAuthConnector
from onyx.db.credentials import create_credential
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import CredentialBase
from onyx.utils.logger import setup_logger
from onyx.utils.subclasses import find_all_subclasses_in_package
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/connector/oauth")

_OAUTH_STATE_KEY_FMT = "oauth_state:{state}"
_OAUTH_STATE_EXPIRATION_SECONDS = 10 * 60  # 10 minutes
_DESIRED_RETURN_URL_KEY = "desired_return_url"
_ADDITIONAL_KWARGS_KEY = "additional_kwargs"

# Cache for OAuth connectors, populated at module load time
_OAUTH_CONNECTORS: dict[DocumentSource, type[OAuthConnector]] = {}


def _discover_oauth_connectors() -> dict[DocumentSource, type[OAuthConnector]]:
    """Walk through the connectors package to find all OAuthConnector implementations"""
    global _OAUTH_CONNECTORS
    if _OAUTH_CONNECTORS:  # Return cached connectors if already discovered
        return _OAUTH_CONNECTORS

    # Import submodules using package-based discovery to avoid sys.path mutations
    oauth_connectors = find_all_subclasses_in_package(
        cast(type[OAuthConnector], OAuthConnector), "onyx.connectors"
    )

    _OAUTH_CONNECTORS = {cls.oauth_id(): cls for cls in oauth_connectors}
    return _OAUTH_CONNECTORS


# Discover OAuth connectors at module load time
_discover_oauth_connectors()


def _get_additional_kwargs(
    request: Request, connector_cls: type[OAuthConnector], args_to_ignore: list[str]
) -> dict[str, str]:
    # get additional kwargs from request
    # e.g. anything except for desired_return_url
    additional_kwargs_dict = {
        k: v for k, v in request.query_params.items() if k not in args_to_ignore
    }
    try:
        # validate
        connector_cls.AdditionalOauthKwargs(**additional_kwargs_dict)
    except ValidationError:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid additional kwargs. Got {additional_kwargs_dict}, expected "
                f"{connector_cls.AdditionalOauthKwargs.model_json_schema()}"
            ),
        )

    return additional_kwargs_dict


class AuthorizeResponse(BaseModel):
    redirect_url: str


@router.get("/authorize/{source}")
def oauth_authorize(
    request: Request,
    source: DocumentSource,
    desired_return_url: Annotated[str | None, Query()] = None,
    _: User = Depends(current_user),
) -> AuthorizeResponse:
    """Initiates the OAuth flow by redirecting to the provider's auth page"""

    tenant_id = get_current_tenant_id()
    oauth_connectors = _discover_oauth_connectors()

    if source not in oauth_connectors:
        raise HTTPException(status_code=400, detail=f"Unknown OAuth source: {source}")

    connector_cls = oauth_connectors[source]
    base_url = WEB_DOMAIN

    # get additional kwargs from request
    # e.g. anything except for desired_return_url
    additional_kwargs = _get_additional_kwargs(
        request, connector_cls, ["desired_return_url"]
    )

    # store state in redis
    if not desired_return_url:
        desired_return_url = f"{base_url}/admin/connectors/{source}?step=0"
    redis_client = get_redis_client(tenant_id=tenant_id)
    state = str(uuid.uuid4())
    redis_client.set(
        _OAUTH_STATE_KEY_FMT.format(state=state),
        json.dumps(
            {
                _DESIRED_RETURN_URL_KEY: desired_return_url,
                _ADDITIONAL_KWARGS_KEY: additional_kwargs,
            }
        ),
        ex=_OAUTH_STATE_EXPIRATION_SECONDS,
    )

    return AuthorizeResponse(
        redirect_url=connector_cls.oauth_authorization_url(
            base_url, state, additional_kwargs
        )
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
) -> CallbackResponse:
    """Handles the OAuth callback and exchanges the code for tokens"""
    oauth_connectors = _discover_oauth_connectors()

    if source not in oauth_connectors:
        raise HTTPException(status_code=400, detail=f"Unknown OAuth source: {source}")

    connector_cls = oauth_connectors[source]

    # get state from redis
    redis_client = get_redis_client()
    oauth_state_bytes = cast(
        bytes, redis_client.get(_OAUTH_STATE_KEY_FMT.format(state=state))
    )
    if not oauth_state_bytes:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    oauth_state = json.loads(oauth_state_bytes.decode("utf-8"))

    desired_return_url = cast(str, oauth_state[_DESIRED_RETURN_URL_KEY])
    additional_kwargs = cast(dict[str, str], oauth_state[_ADDITIONAL_KWARGS_KEY])

    base_url = WEB_DOMAIN
    token_info = connector_cls.oauth_code_to_token(base_url, code, additional_kwargs)

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

    # TODO: use a library for url handling
    sep = "&" if "?" in desired_return_url else "?"
    return CallbackResponse(
        redirect_url=f"{desired_return_url}{sep}credentialId={credential.id}"
    )


class OAuthAdditionalKwargDescription(BaseModel):
    name: str
    display_name: str
    description: str


class OAuthDetails(BaseModel):
    oauth_enabled: bool
    additional_kwargs: list[OAuthAdditionalKwargDescription]


@router.get("/details/{source}")
def oauth_details(
    source: DocumentSource,
    _: User = Depends(current_user),
) -> OAuthDetails:
    oauth_connectors = _discover_oauth_connectors()

    if source not in oauth_connectors:
        return OAuthDetails(
            oauth_enabled=False,
            additional_kwargs=[],
        )

    connector_cls = oauth_connectors[source]

    additional_kwarg_descriptions = []
    for key, value in connector_cls.AdditionalOauthKwargs.model_json_schema()[
        "properties"
    ].items():
        additional_kwarg_descriptions.append(
            OAuthAdditionalKwargDescription(
                name=key,
                display_name=value.get("title", key),
                description=value.get("description", ""),
            )
        )

    return OAuthDetails(
        oauth_enabled=True,
        additional_kwargs=additional_kwarg_descriptions,
    )
