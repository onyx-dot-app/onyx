"""The one OAuth sign-in flow for every integration.

``start_integration_oauth`` gives the authorization URL and stores the
attempt (state and PKCE verifier) in the shared attempt store.
``complete_integration_oauth`` exchanges the code and stores the connection:
a user row for individual sign-in, the organization row when an admin
connects a shared integration.

Endpoints come from the kind of the OAuth client:
- manual: the token and authorization URLs the admin entered;
- preset: the code of a built-in provider;
- MCP servers (manual or discovery): the MCP SDK, which also runs discovery,
  dynamic client registration and client metadata documents.
"""

import secrets
from datetime import datetime, timezone
from uuid import UUID

import requests
from mcp.client.auth import PKCEParameters
from mcp.client.auth.oauth2 import OAuthContext
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    ProtectedResourceMetadata,
)
from pydantic import AnyUrl, BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.auth.oauth_token_manager import exchange_oauth_code_for_token
from onyx.auth.permissions import has_global_permission
from onyx.auth.pkce import generate_pkce_pair
from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    IntegrationOAuthProviderMode,
    MCPTransport,
    Permission,
)
from onyx.db.integration_connection import (
    fetch_integration,
    get_mcp_server_for_integration,
    get_oauth_client,
    upsert_connection__no_commit,
)
from onyx.db.models import Integration, IntegrationOAuthClient, MCPServer, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.oauth_exchange import exchange_preset_code
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.connections import (
    preset_host_values,
    preset_provider_for,
    sign_in_settings_for,
)
from onyx.oauth.authorization_attempt import (
    AuthorizationAttemptStore,
    canonical_json_fingerprint,
    generate_authorization_state,
)
from onyx.oauth.models import (
    OAuthConfigurationFingerprint,
    PKCECodeVerifier,
    SafeOAuthReturnPath,
)
from onyx.oauth.protocol import (
    OAuthFlowParams,
    build_authorization_url,
    validate_authorization_params,
)
from onyx.server.features.mcp.client_metadata import mcp_oauth_redirect_uri
from onyx.server.features.mcp.credentials import (
    mcp_oauth_client_information_fingerprint,
)
from onyx.server.features.mcp.models import MCPPendingOAuthAuthorization
from onyx.server.features.mcp.oauth import (
    IntegrationTokenStorage,
    MCPClientRegistrationConflict,
    OnyxOAuthClientProvider,
    integration_mcp_server_connection,
    make_integration_oauth_provider,
)
from onyx.server.features.mcp.oauth_discovery import oauth_setup_error
from onyx.server.features.mcp.oauth_flow import (
    OAuthAuthorizationRedirect,
    run_oauth_discovery,
    validate_client_metadata_authorization,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_async_sync_no_cancel

logger = setup_logger()

# The redirect URIs admins registered with each service before the
# integration tables. Keep them, so no OAuth app needs a new registration.
_PRESET_REDIRECT_URI = f"{WEB_DOMAIN}/craft/v1/apps/oauth/callback"
_MANUAL_REDIRECT_URI = f"{WEB_DOMAIN}/oauth-config/callback"

_PRESET_TOKEN_FIELDS = frozenset(
    {"access_token", "refresh_token", "token_type", "expires_in", "expires_at", "scope"}
)


class IntegrationMCPAttempt(BaseModel):
    """The SDK context to restore at the callback of an MCP sign-in."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    redirect_uri: AnyUrl
    client_information_fingerprint: OAuthConfigurationFingerprint
    protected_resource_metadata: ProtectedResourceMetadata | None = None
    oauth_metadata: OAuthMetadata | None = None
    authorization_server_url: str | None = None
    protocol_version: str | None = None
    scope: str | None = None
    resource: AnyUrl | None = None


class IntegrationOAuthAttemptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    integration_id: int
    for_organization: bool
    configuration_fingerprint: OAuthConfigurationFingerprint
    code_verifier: PKCECodeVerifier | None = None
    return_path: SafeOAuthReturnPath | None = None
    mcp: IntegrationMCPAttempt | None = None


INTEGRATION_OAUTH_ATTEMPTS = AuthorizationAttemptStore(
    cache_backend_provider=get_cache_backend,
    namespace="integration",
    payload_type=IntegrationOAuthAttemptPayload,
)


class IntegrationOAuthCallbackResult(BaseModel):
    integration_id: int
    return_path: str | None


def integration_oauth_redirect_uri(
    integration: Integration, oauth_client: IntegrationOAuthClient
) -> str:
    if integration.kind is IntegrationKind.MCP_SERVER:
        return mcp_oauth_redirect_uri()
    if oauth_client.provider_mode is IntegrationOAuthProviderMode.PRESET:
        return _PRESET_REDIRECT_URI
    return _MANUAL_REDIRECT_URI


def _sign_in_host(integration: Integration, db_session: Session) -> str | None:
    if integration.kind is IntegrationKind.MCP_SERVER:
        mcp_server = get_mcp_server_for_integration(db_session, integration.id)
        return mcp_server.server_url if mcp_server is not None else None
    host_values = preset_host_values(integration, db_session)
    return canonical_json_fingerprint(host_values) if host_values else None


def _configuration_fingerprint(
    integration: Integration,
    oauth_client: IntegrationOAuthClient,
    for_organization: bool,
    db_session: Session,
) -> str:
    settings = sign_in_settings_for(
        integration, oauth_client, _sign_in_host(integration, db_session)
    )
    return canonical_json_fingerprint(
        {
            "integration_id": integration.id,
            "auth_mode": integration.auth_mode.value,
            "provider_mode": oauth_client.provider_mode.value,
            "for_organization": for_organization,
            "redirect_uri": integration_oauth_redirect_uri(integration, oauth_client),
            "settings": settings.model_dump(mode="json"),
        }
    )


def _check_may_connect(integration: Integration, user: User) -> bool:
    """Raise when the user may not sign in. Returns whether the connection
    is the organization connection."""
    if user.is_anonymous:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED, "Sign in to Onyx first.")
    if not integration.enabled:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"An admin turned off {integration.name}.",
        )
    if integration.auth_method is not IntegrationAuthMethod.OAUTH2:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{integration.name} does not use OAuth sign-in.",
        )
    if integration.auth_mode is IntegrationAuthMode.SHARED:
        if not has_global_permission(user, Permission.MANAGE_ACTIONS):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                f"Only an admin can connect {integration.name} for the organization.",
            )
        return True
    if integration.auth_mode is IntegrationAuthMode.INDIVIDUAL:
        return False
    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT, f"{integration.name} needs no sign-in."
    )


def _oauth_client_or_raise(
    integration: Integration, db_session: Session
) -> IntegrationOAuthClient:
    oauth_client = get_oauth_client(db_session, integration.id)
    if oauth_client is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{integration.name} is not set up for your organization. Ask your admin.",
        )
    return oauth_client


def _client_id_and_secret(
    integration: Integration, oauth_client: IntegrationOAuthClient
) -> tuple[str, str | None]:
    client_id = (
        oauth_client.client_id.get_value(apply_mask=False)
        if oauth_client.client_id is not None
        else ""
    )
    client_secret = (
        oauth_client.client_secret.get_value(apply_mask=False)
        if oauth_client.client_secret is not None
        else None
    )
    if not client_id:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{integration.name} is not set up for your organization. Ask your admin.",
        )
    return client_id, client_secret or None


def _mcp_server_or_raise(integration: Integration, db_session: Session) -> MCPServer:
    mcp_server = get_mcp_server_for_integration(db_session, integration.id)
    if mcp_server is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND, f"{integration.name} has no MCP server."
        )
    return mcp_server


def _owner_id(user: User, for_organization: bool) -> UUID | None:
    return None if for_organization else user.id


# Start


def start_integration_oauth(
    integration: Integration,
    user: User,
    db_session: Session,
    return_path: str | None = None,
) -> str:
    """Begin a sign-in and return the authorization URL."""
    for_organization = _check_may_connect(integration, user)
    oauth_client = _oauth_client_or_raise(integration, db_session)
    fingerprint = _configuration_fingerprint(
        integration, oauth_client, for_organization, db_session
    )
    if integration.kind is IntegrationKind.MCP_SERVER:
        return _start_mcp(
            integration,
            oauth_client,
            user,
            for_organization,
            fingerprint,
            return_path,
            db_session,
        )

    state = generate_authorization_state()

    def store(code_verifier: str | None) -> None:
        INTEGRATION_OAUTH_ATTEMPTS.store(
            owner_id=str(user.id),
            state=state,
            payload=IntegrationOAuthAttemptPayload(
                integration_id=integration.id,
                for_organization=for_organization,
                configuration_fingerprint=fingerprint,
                code_verifier=code_verifier,
                return_path=return_path,
            ),
        )

    redirect_uri = integration_oauth_redirect_uri(integration, oauth_client)
    if oauth_client.provider_mode is IntegrationOAuthProviderMode.PRESET:
        provider = preset_provider_for(integration, db_session)
        if provider is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"{integration.name} has no built-in provider.",
            )
        client_id, client_secret = _client_id_and_secret(integration, oauth_client)
        if client_secret is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"{integration.name} is not set up for your organization. "
                "Ask your admin.",
            )
        flow = provider.resolve_oauth_flow(preset_host_values(integration, db_session))
        additional_params = dict(flow.extra_authorize_params)
        if flow.optional_scope:
            additional_params[flow.optional_scope_param] = flow.optional_scope
        code_verifier, code_challenge = (
            generate_pkce_pair() if flow.supports_pkce else (None, None)
        )
        authorization_url = build_authorization_url(
            authorization_url=flow.authorize_url,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scope=flow.scope,
            scope_param=flow.scope_param,
            additional_params=additional_params,
            code_challenge=code_challenge,
        )
        store(code_verifier)
        return authorization_url

    if not oauth_client.authorization_url or not oauth_client.token_url:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{integration.name} is not set up for your organization. Ask your admin.",
        )
    client_id, _ = _client_id_and_secret(integration, oauth_client)
    code_verifier, code_challenge = (
        generate_pkce_pair() if oauth_client.pkce else (None, None)
    )
    authorization_url = build_authorization_url(
        authorization_url=oauth_client.authorization_url,
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        scope=" ".join(oauth_client.scopes) if oauth_client.scopes else None,
        additional_params=oauth_client.additional_params,
        code_challenge=code_challenge,
    )
    store(code_verifier)
    return authorization_url


def _attempt_from_context(
    context: OAuthContext, client_information: OAuthClientInformationFull
) -> IntegrationMCPAttempt:
    redirect_uris = context.client_metadata.redirect_uris
    if not redirect_uris:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "MCP OAuth discovery did not produce a redirect URI.",
        )
    return IntegrationMCPAttempt(
        redirect_uri=redirect_uris[0],
        client_information_fingerprint=mcp_oauth_client_information_fingerprint(
            client_information
        ),
        protected_resource_metadata=context.protected_resource_metadata,
        oauth_metadata=context.oauth_metadata,
        authorization_server_url=context.auth_server_url,
        protocol_version=context.protocol_version,
        scope=context.client_metadata.scope,
    )


def _registration_conflict(error: BaseException) -> bool:
    if isinstance(error, MCPClientRegistrationConflict):
        return True
    if isinstance(error, BaseExceptionGroup):
        return any(_registration_conflict(child) for child in error.exceptions)
    return False


def _start_mcp(
    integration: Integration,
    oauth_client: IntegrationOAuthClient,
    user: User,
    for_organization: bool,
    fingerprint: str,
    return_path: str | None,
    db_session: Session,
) -> str:
    mcp_server = _mcp_server_or_raise(integration, db_session)
    server = integration_mcp_server_connection(mcp_server, integration, oauth_client)
    owner_id = _owner_id(user, for_organization)

    def payload(
        code_verifier: str, mcp: IntegrationMCPAttempt
    ) -> IntegrationOAuthAttemptPayload:
        return IntegrationOAuthAttemptPayload(
            integration_id=integration.id,
            for_organization=for_organization,
            configuration_fingerprint=fingerprint,
            code_verifier=code_verifier,
            return_path=return_path,
            mcp=mcp,
        )

    if oauth_client.provider_mode is not IntegrationOAuthProviderMode.DISCOVERY:
        storage = IntegrationTokenStorage(
            integration.id,
            owner_id,
            load_stored_tokens=False,
            cimd_enabled=oauth_client.cimd_enabled,
        )
        client_information = run_async_sync_no_cancel(storage.get_client_info())
        if (
            client_information is None
            or not client_information.client_id
            or not oauth_client.authorization_url
            or not oauth_client.token_url
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"{integration.name} is not set up for your organization. "
                "Ask your admin.",
            )
        try:
            validate_authorization_params(
                oauth_client.authorization_url,
                oauth_client.additional_params,
                owns_resource=True,
            )
        except ValueError as error:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(error)) from error
        state = generate_authorization_state()
        pkce = PKCEParameters.generate()
        redirect_uri = mcp_oauth_redirect_uri()
        authorization_url = build_authorization_url(
            authorization_url=oauth_client.authorization_url,
            client_id=client_information.client_id,
            redirect_uri=redirect_uri,
            state=state,
            scope=" ".join(oauth_client.scopes) if oauth_client.scopes else None,
            additional_params=oauth_client.additional_params,
            code_challenge=pkce.code_challenge,
            resource=server.server_url,
            owns_resource=True,
        )
        INTEGRATION_OAUTH_ATTEMPTS.store(
            owner_id=str(user.id),
            state=state,
            payload=payload(
                pkce.code_verifier,
                IntegrationMCPAttempt(
                    redirect_uri=AnyUrl(redirect_uri),
                    client_information_fingerprint=(
                        mcp_oauth_client_information_fingerprint(client_information)
                    ),
                    resource=AnyUrl(server.server_url),
                ),
            ),
        )
        return authorization_url

    async def persist_attempt(
        authorization: MCPPendingOAuthAuthorization, context: OAuthContext
    ) -> None:
        if context.client_info is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "MCP OAuth discovery did not produce client registration information.",
            )
        await validate_client_metadata_authorization(
            authorization.authorization_url, context.client_info.client_id
        )
        INTEGRATION_OAUTH_ATTEMPTS.store(
            owner_id=str(user.id),
            state=authorization.state,
            payload=payload(
                authorization.code_verifier,
                _attempt_from_context(context, context.client_info),
            ),
        )

    async def discover() -> str:
        provider = make_integration_oauth_provider(
            server,
            IntegrationTokenStorage(
                integration.id,
                owner_id,
                load_stored_tokens=False,
                cimd_enabled=oauth_client.cimd_enabled,
            ),
            authorization_request_handler=persist_attempt,
        )
        if oauth_client.scopes:
            provider.context.client_metadata.scope = " ".join(oauth_client.scopes)
        result = await run_oauth_discovery(
            oauth_provider=provider,
            server_url=server.server_url,
            connection_headers={},
            transport=MCPTransport.STREAMABLE_HTTP,
        )
        if not isinstance(result, OAuthAuthorizationRedirect):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "OAuth auto-discovery did not produce an authorization redirect.",
            )
        return result.url

    for attempt in range(2):
        try:
            return run_async_sync_no_cancel(discover())
        except OnyxError:
            raise
        except Exception as error:
            if _registration_conflict(error) and attempt == 0:
                logger.info("Concurrent MCP client registration won; retrying")
                continue
            logger.warning(
                "Integration OAuth discovery failed for integration %s",
                integration.id,
            )
            raise oauth_setup_error(error) from error
    raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "OAuth discovery did not finish.")


# Callback


def complete_integration_oauth(
    code: str, state: str, user: User, db_session: Session
) -> IntegrationOAuthCallbackResult:
    """Exchange the code and store the connection."""
    payload = INTEGRATION_OAUTH_ATTEMPTS.consume(
        owner_id=str(user.id), state=state
    ).payload
    integration = fetch_integration(db_session, payload.integration_id)
    if integration is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "The integration no longer exists.")
    for_organization = _check_may_connect(integration, user)
    oauth_client = _oauth_client_or_raise(integration, db_session)
    if for_organization != payload.for_organization or not secrets.compare_digest(
        payload.configuration_fingerprint,
        _configuration_fingerprint(
            integration, oauth_client, for_organization, db_session
        ),
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "The sign-in settings changed while you signed in. Try again.",
        )
    owner_id = _owner_id(user, for_organization)

    if integration.kind is IntegrationKind.MCP_SERVER:
        _complete_mcp(integration, oauth_client, payload, owner_id, code, db_session)
    elif oauth_client.provider_mode is IntegrationOAuthProviderMode.PRESET:
        _complete_preset(integration, oauth_client, payload, owner_id, code, db_session)
    else:
        _complete_manual(integration, oauth_client, payload, owner_id, code, db_session)
    return IntegrationOAuthCallbackResult(
        integration_id=integration.id, return_path=payload.return_path
    )


def _complete_manual(
    integration: Integration,
    oauth_client: IntegrationOAuthClient,
    payload: IntegrationOAuthAttemptPayload,
    owner_id: UUID | None,
    code: str,
    db_session: Session,
) -> None:
    client_id, client_secret = _client_id_and_secret(integration, oauth_client)
    if not oauth_client.authorization_url or not oauth_client.token_url:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{integration.name} is not set up for your organization. Ask your admin.",
        )
    try:
        token_data = exchange_oauth_code_for_token(
            OAuthFlowParams(
                authorization_url=oauth_client.authorization_url,
                token_url=oauth_client.token_url,
                client_id=client_id,
                client_secret=client_secret,
                scopes=oauth_client.scopes,
                additional_params=oauth_client.additional_params,
            ),
            code,
            integration_oauth_redirect_uri(integration, oauth_client),
            code_verifier=payload.code_verifier,
        )
    except (requests.RequestException, ValueError) as error:
        logger.warning(
            "Integration OAuth token exchange failed for integration %s: %s",
            integration.id,
            type(error).__name__,
        )
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{integration.name} did not complete the sign-in.",
        ) from error
    expires_at = token_data.get("expires_at")
    scope = token_data.get("scope")
    refresh_token = token_data.get("refresh_token")
    token_type = token_data.get("token_type")
    upsert_connection__no_commit(
        db_session,
        integration_id=integration.id,
        user_id=owner_id,
        secret=ConnectionSecret(
            access_token=token_data["access_token"],
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            token_type=token_type if isinstance(token_type, str) else None,
        ).model_dump(mode="json"),
        expires_at=(
            datetime.fromtimestamp(expires_at, tz=timezone.utc)
            if isinstance(expires_at, (int, float))
            else None
        ),
        granted_scopes=scope.split() if isinstance(scope, str) and scope else None,
    )
    db_session.commit()


def _complete_preset(
    integration: Integration,
    oauth_client: IntegrationOAuthClient,
    payload: IntegrationOAuthAttemptPayload,
    owner_id: UUID | None,
    code: str,
    db_session: Session,
) -> None:
    provider = preset_provider_for(integration, db_session)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{integration.name} has no built-in provider.",
        )
    client_id, client_secret = _client_id_and_secret(integration, oauth_client)
    if client_secret is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{integration.name} is not set up for your organization. Ask your admin.",
        )
    grant = exchange_preset_code(
        provider,
        provider.resolve_oauth_flow(preset_host_values(integration, db_session)),
        app_name=integration.name,
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=integration_oauth_redirect_uri(integration, oauth_client),
        code_verifier=payload.code_verifier,
    )
    secret, expires_at = preset_credentials_to_secret(grant.credentials)
    upsert_connection__no_commit(
        db_session,
        integration_id=integration.id,
        user_id=owner_id,
        secret=secret.model_dump(mode="json"),
        expires_at=expires_at,
        granted_scopes=grant.granted_scopes,
    )
    db_session.commit()


def preset_credentials_to_secret(
    credentials: dict[str, object],
) -> tuple[ConnectionSecret, datetime | None]:
    """Map the credential dict of a built-in provider to the one secret
    shape and its expiry."""
    access_token = credentials.get("access_token")
    refresh_token = credentials.get("refresh_token")
    token_type = credentials.get("token_type")
    expires_at_raw = credentials.get("expires_at")
    expires_at: datetime | None = None
    if isinstance(expires_at_raw, str):
        try:
            expires_at = datetime.fromisoformat(expires_at_raw)
        except ValueError:
            expires_at = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    return (
        ConnectionSecret(
            access_token=access_token if isinstance(access_token, str) else None,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            token_type=token_type if isinstance(token_type, str) else None,
            fields={
                key: value
                for key, value in credentials.items()
                if key not in _PRESET_TOKEN_FIELDS and isinstance(value, str)
            },
        ),
        expires_at,
    )


def _complete_mcp(
    integration: Integration,
    oauth_client: IntegrationOAuthClient,
    payload: IntegrationOAuthAttemptPayload,
    owner_id: UUID | None,
    code: str,
    db_session: Session,
) -> None:
    mcp = payload.mcp
    if mcp is None or payload.code_verifier is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "The sign-in attempt is not an MCP sign-in."
        )
    mcp_server = _mcp_server_or_raise(integration, db_session)
    server = integration_mcp_server_connection(mcp_server, integration, oauth_client)
    storage = IntegrationTokenStorage(
        integration.id,
        owner_id,
        load_stored_tokens=False,
        cimd_enabled=oauth_client.cimd_enabled,
        expected_client_information_fingerprint=mcp.client_information_fingerprint,
    )
    provider: OnyxOAuthClientProvider = make_integration_oauth_provider(server, storage)
    client_information = run_async_sync_no_cancel(storage.get_client_info())
    if client_information is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "MCP OAuth client registration changed while authorization was pending.",
        )
    context = provider.context
    if oauth_client.provider_mode is IntegrationOAuthProviderMode.DISCOVERY:
        context.protected_resource_metadata = mcp.protected_resource_metadata
        context.oauth_metadata = mcp.oauth_metadata
        context.auth_server_url = mcp.authorization_server_url
        context.protocol_version = mcp.protocol_version
    context.client_metadata.scope = mcp.scope
    context.client_metadata.redirect_uris = [mcp.redirect_uri]
    context.client_info = client_information
    run_async_sync_no_cancel(
        provider.complete_authorization_code_exchange(
            code,
            payload.code_verifier,
            resource=str(mcp.resource) if mcp.resource else None,
        )
    )
