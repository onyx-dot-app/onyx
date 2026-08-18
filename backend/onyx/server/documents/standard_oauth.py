import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.pkce import generate_pkce_pair
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import OAuthConnector
from onyx.db.credentials import create_credential
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import CredentialBase
from onyx.utils.logger import setup_logger
from onyx.utils.subclasses import find_all_subclasses_in_package
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/connector/oauth")

_OAUTH_STATE_KEY_FMT = "oauth_state:{state}"
_OAUTH_STATE_EXPIRATION_SECONDS = 10 * 60

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
    additional_kwargs_dict = {
        k: v for k, v in request.query_params.items() if k not in args_to_ignore
    }
    try:
        connector_cls.AdditionalOauthKwargs(**additional_kwargs_dict)
    except ValidationError as error:
        messages = {
            str(item["msg"]).removeprefix("Value error, ")
            for item in error.errors(include_url=False, include_input=False)
        }
        detail = "Invalid OAuth configuration: " + "; ".join(sorted(messages))
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, detail) from error

    return additional_kwargs_dict


class OAuthState(BaseModel):
    desired_return_url: str
    additional_kwargs: dict[str, str]
    code_verifier: str | None = None


class AuthorizeResponse(BaseModel):
    redirect_url: str


def _get_enabled_oauth_connector(
    source: DocumentSource,
) -> type[OAuthConnector]:
    connector_cls = _discover_oauth_connectors().get(source)
    if connector_cls is None:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"Unknown OAuth source: {source}")
    if not connector_cls.oauth_enabled():
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"OAuth is not configured for {source}"
        )
    return connector_cls


@router.get("/authorize/{source}")
def oauth_authorize(
    request: Request,
    source: DocumentSource,
    desired_return_url: Annotated[str | None, Query()] = None,
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> AuthorizeResponse:
    """Initiates the OAuth flow by redirecting to the provider's auth page"""

    tenant_id = get_current_tenant_id()
    connector_cls = _get_enabled_oauth_connector(source)
    base_url = WEB_DOMAIN

    additional_kwargs = _get_additional_kwargs(
        request, connector_cls, ["desired_return_url"]
    )

    if not desired_return_url:
        desired_return_url = f"{base_url}/admin/connectors/{source}?step=0"

    code_verifier = None
    code_challenge = None
    if connector_cls.supports_pkce:
        code_verifier, code_challenge = generate_pkce_pair()

    state = str(uuid.uuid4())
    redirect_url = connector_cls.oauth_authorization_url(
        base_url, state, additional_kwargs, code_challenge
    )
    oauth_state = OAuthState(
        desired_return_url=desired_return_url,
        additional_kwargs=additional_kwargs,
        code_verifier=code_verifier,
    )
    redis_client = get_redis_client(tenant_id=tenant_id)
    redis_client.set(
        _OAUTH_STATE_KEY_FMT.format(state=state),
        oauth_state.model_dump_json(),
        ex=_OAUTH_STATE_EXPIRATION_SECONDS,
    )

    return AuthorizeResponse(redirect_url=redirect_url)


class CallbackResponse(BaseModel):
    redirect_url: str


@router.get("/callback/{source}")
def oauth_callback(
    source: DocumentSource,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> CallbackResponse:
    """Handles the OAuth callback and exchanges the code for tokens"""
    connector_cls = _get_enabled_oauth_connector(source)

    redis_client = get_redis_client()
    oauth_state_bytes = redis_client.getdel(_OAUTH_STATE_KEY_FMT.format(state=state))
    if not oauth_state_bytes:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Invalid OAuth state")
    try:
        oauth_state = OAuthState.model_validate_json(oauth_state_bytes)
    except ValidationError as error:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Invalid OAuth state") from error

    base_url = WEB_DOMAIN
    token_info = connector_cls.oauth_code_to_token(
        base_url,
        code,
        oauth_state.additional_kwargs,
        oauth_state.code_verifier,
    )

    credential_data = CredentialBase(
        credential_json=token_info,
        admin_public=True,
        source=source,
        name=f"{source.title()} OAuth Credential",
    )

    credential = create_credential(
        credential_data=credential_data,
        user=user,
        db_session=db_session,
    )

    # Preserve existing query parameters in the requested return URL.
    sep = "&" if "?" in oauth_state.desired_return_url else "?"
    return CallbackResponse(
        redirect_url=(
            f"{oauth_state.desired_return_url}{sep}credentialId={credential.id}"
        )
    )


class OAuthAdditionalKwargDescription(BaseModel):
    name: str
    display_name: str
    description: str


class OAuthDetails(BaseModel):
    oauth_enabled: bool
    supports_manual_credentials: bool
    additional_kwargs: list[OAuthAdditionalKwargDescription]


@router.get("/details/{source}")
def oauth_details(
    source: DocumentSource,
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> OAuthDetails:
    oauth_connectors = _discover_oauth_connectors()

    if source not in oauth_connectors:
        return OAuthDetails(
            oauth_enabled=False,
            supports_manual_credentials=True,
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
        oauth_enabled=connector_cls.oauth_enabled(),
        supports_manual_credentials=connector_cls.supports_manual_credentials,
        additional_kwargs=additional_kwarg_descriptions,
    )
