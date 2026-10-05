from typing import Annotated, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.pkce import generate_pkce_pair
from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import OAuthConnector
from onyx.db.credentials import create_credential
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth.authorization_attempt import (
    AuthorizationAttemptStore,
    generate_authorization_state,
)
from onyx.server.documents.models import CredentialBase
from onyx.utils.logger import setup_logger
from onyx.utils.subclasses import find_all_subclasses_in_package
from onyx.utils.url import sanitize_next_url

logger = setup_logger()

router = APIRouter(prefix="/connector/oauth")

_OAUTH_STATE_EXPIRATION_SECONDS = 10 * 60
_OAUTH_ATTEMPT_NAMESPACE_PREFIX = "connector"

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
    _validate_additional_kwargs(connector_cls, additional_kwargs_dict)
    return additional_kwargs_dict


def _validate_additional_kwargs(
    connector_cls: type[OAuthConnector], additional_kwargs: dict[str, str]
) -> None:
    try:
        connector_cls.AdditionalOauthKwargs(**additional_kwargs)
    except ValidationError as error:
        messages = {
            str(item["msg"]).removeprefix("Value error, ")
            for item in error.errors(include_url=False, include_input=False)
        }
        detail = "Invalid OAuth configuration: " + "; ".join(sorted(messages))
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, detail) from error


class _ConnectorOAuthAttemptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    desired_return_path: str
    additional_kwargs: dict[str, str]
    code_verifier: str | None = None

    @field_validator("desired_return_path")
    @classmethod
    def validate_return_path(cls, value: str) -> str:
        if sanitize_next_url(value) != value or any(
            not character.isprintable() for character in value
        ):
            raise ValueError("OAuth return path must be a local application path")
        return value


def _authorization_attempt_store(
    source: DocumentSource,
) -> AuthorizationAttemptStore[_ConnectorOAuthAttemptPayload]:
    return AuthorizationAttemptStore(
        get_cache_backend(),
        namespace=f"{_OAUTH_ATTEMPT_NAMESPACE_PREFIX}-{source.value}",
        payload_type=_ConnectorOAuthAttemptPayload,
        ttl_seconds=_OAUTH_STATE_EXPIRATION_SECONDS,
    )


def _attempt_payload(
    desired_return_url: str,
    additional_kwargs: dict[str, str],
    code_verifier: str | None,
) -> _ConnectorOAuthAttemptPayload:
    try:
        return_url = urlsplit(desired_return_url)
    except ValueError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth return URL is invalid",
        ) from error

    if return_url.scheme or return_url.netloc:
        try:
            web_domain = urlsplit(WEB_DOMAIN)
            return_origin = (
                return_url.scheme.lower(),
                (return_url.hostname or "").lower(),
                return_url.port
                or (443 if return_url.scheme.lower() == "https" else 80),
            )
            web_origin = (
                web_domain.scheme.lower(),
                (web_domain.hostname or "").lower(),
                web_domain.port
                or (443 if web_domain.scheme.lower() == "https" else 80),
            )
        except ValueError as error:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "OAuth return URL is invalid",
            ) from error
        if return_origin != web_origin or (
            return_url.username is not None or return_url.password is not None
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "OAuth return URL must use the Onyx application origin",
            )
        desired_return_url = urlunsplit(
            ("", "", return_url.path or "/", return_url.query, return_url.fragment)
        )

    try:
        return _ConnectorOAuthAttemptPayload(
            desired_return_path=desired_return_url,
            additional_kwargs=additional_kwargs,
            code_verifier=code_verifier,
        )
    except ValidationError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth return path must be a local application path",
        ) from error


def _return_path_with_credential(return_path: str, credential_id: int) -> str:
    parsed = urlsplit(return_path)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "credentialId"
    ]
    query.append(("credentialId", str(credential_id)))
    return urlunsplit(("", "", parsed.path, urlencode(query), parsed.fragment))


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
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> AuthorizeResponse:
    """Initiates the OAuth flow by redirecting to the provider's auth page"""

    connector_cls = _get_enabled_oauth_connector(source)
    base_url = WEB_DOMAIN

    additional_kwargs = _get_additional_kwargs(
        request, connector_cls, ["desired_return_url"]
    )

    if not desired_return_url:
        desired_return_url = f"/admin/connectors/{source}?step=0"
    code_verifier = None
    code_challenge = None
    if connector_cls.supports_pkce:
        code_verifier, code_challenge = generate_pkce_pair()
    payload = _attempt_payload(
        desired_return_url,
        additional_kwargs,
        code_verifier,
    )

    state = generate_authorization_state()
    redirect_url = connector_cls.oauth_authorization_url(
        base_url, state, additional_kwargs, code_challenge
    )
    _authorization_attempt_store(source).store(
        owner_id=str(user.id),
        state=state,
        payload=payload,
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
    attempt = _authorization_attempt_store(source).consume(
        owner_id=str(user.id),
        state=state,
    )
    _validate_additional_kwargs(connector_cls, attempt.payload.additional_kwargs)
    if connector_cls.supports_pkce and not attempt.payload.code_verifier:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Invalid OAuth state")

    token_info = connector_cls.oauth_code_to_token(
        WEB_DOMAIN,
        code,
        attempt.payload.additional_kwargs,
        attempt.payload.code_verifier,
    )
    credential = create_credential(
        credential_data=CredentialBase(
            credential_json=token_info,
            admin_public=True,
            source=source,
            name=f"{source.title()} OAuth Credential",
        ),
        user=user,
        db_session=db_session,
    )
    return_path = _return_path_with_credential(
        attempt.payload.desired_return_path,
        credential.id,
    )
    return CallbackResponse(redirect_url=f"{WEB_DOMAIN.rstrip('/')}{return_path}")


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
