"""OAuth for proposed MCP settings, with credentials held outside server rows."""

import base64
import time

from mcp.client.auth import PKCEParameters, TokenStorage
from mcp.client.auth.oauth2 import OAuthContext
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from pydantic import AnyUrl, BaseModel, ConfigDict, ValidationError

from onyx.cache.factory import get_cache_backend
from onyx.db.enums import MCPOAuthProviderMode, MCPTransport
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth.authorization_attempt import (
    AuthorizationAttemptStore,
    generate_authorization_state,
)
from onyx.oauth.models import OAuthConfigurationFingerprint, PKCECodeVerifier
from onyx.oauth.protocol import build_authorization_url, validate_authorization_params
from onyx.server.features.mcp.client_metadata import mcp_oauth_redirect_uri
from onyx.server.features.mcp.models import (
    MCPConnectionData,
    MCPOAuthKeys,
    MCPPendingOAuthAuthorization,
    MCPServerConnection,
    MCPSetupRequest,
)
from onyx.server.features.mcp.oauth import (
    TOKEN_EXPIRY_BUFFER_SECONDS,
    OnyxOAuthClientProvider,
    make_oauth_provider_with_storage,
)
from onyx.server.features.mcp.oauth_flow import (
    OAuthAuthorizationRedirect,
    run_oauth_discovery,
    validate_client_metadata_authorization,
)
from onyx.utils.encryption import decrypt_bytes_to_string, encrypt_string_to_bytes

SETUP_OAUTH_STATE_PREFIX = "mcp-setup_"


class SetupOAuthAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: MCPSetupRequest
    expected_configuration_fingerprint: OAuthConfigurationFingerprint | None = None
    client_information: OAuthClientInformationFull
    code_verifier: PKCECodeVerifier
    redirect_uri: AnyUrl
    protected_resource_metadata: ProtectedResourceMetadata | None = None
    oauth_metadata: OAuthMetadata | None = None
    authorization_server_url: str | None = None
    protocol_version: str | None = None
    scope: str | None = None
    resource: str | None = None


class _EncryptedSetupAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    encrypted_payload: str


SETUP_OAUTH_ATTEMPTS = AuthorizationAttemptStore(
    cache_backend_provider=get_cache_backend,
    namespace="mcp-setup",
    payload_type=_EncryptedSetupAttempt,
)


class TransientTokenStorage(TokenStorage):
    """Collect registration and grant results until tool discovery succeeds."""

    def __init__(
        self, client_information: OAuthClientInformationFull | None = None
    ) -> None:
        self.client_information = client_information
        self.tokens: OAuthToken | None = None
        self.token_expires_at: float | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens
        self.token_expires_at = (
            time.time() + tokens.expires_in - TOKEN_EXPIRY_BUFFER_SECONDS
            if tokens.expires_in is not None
            else None
        )

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_information

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_information = client_info

    def connection_data(self, context: OAuthContext) -> MCPConnectionData:
        data = MCPConnectionData(headers={})
        if self.client_information is not None:
            data[MCPOAuthKeys.CLIENT_INFO.value] = self.client_information.model_dump(
                mode="json"
            )
        if self.tokens is not None:
            data[MCPOAuthKeys.TOKENS.value] = self.tokens.model_dump(mode="json")
        if self.token_expires_at is not None:
            data[MCPOAuthKeys.TOKEN_EXPIRES_AT.value] = self.token_expires_at
        if context.oauth_metadata is not None:
            data[MCPOAuthKeys.METADATA.value] = context.oauth_metadata.model_dump(
                mode="json"
            )
        return data


def _setup_state() -> str:
    return SETUP_OAUTH_STATE_PREFIX + generate_authorization_state()


def _connection(request: MCPSetupRequest) -> MCPServerConnection:
    return MCPServerConnection(
        id=request.existing_server_id or 0,
        name=request.name,
        server_url=request.server_url,
        auth_type=request.auth_type,
        transport=request.transport,
        oauth_provider_mode=request.oauth_provider_mode,
        oauth_cimd_enabled=request.oauth_cimd_enabled,
        oauth_authorization_endpoint=request.oauth_authorization_endpoint,
        oauth_token_endpoint=request.oauth_token_endpoint,
    )


def _store_attempt(owner_id: str, state: str, attempt: SetupOAuthAttempt) -> None:
    encrypted_payload = base64.b64encode(
        encrypt_string_to_bytes(attempt.model_dump_json())
    ).decode()
    SETUP_OAUTH_ATTEMPTS.store(
        owner_id=owner_id,
        state=state,
        payload=_EncryptedSetupAttempt(encrypted_payload=encrypted_payload),
    )


def consume_setup_oauth(state: str, owner_id: str) -> SetupOAuthAttempt:
    """Consume the owner-bound attempt before permission checks or exchange."""
    attempt = SETUP_OAUTH_ATTEMPTS.consume(owner_id=owner_id, state=state)
    try:
        return SetupOAuthAttempt.model_validate_json(
            decrypt_bytes_to_string(base64.b64decode(attempt.payload.encrypted_payload))
        )
    except (ValueError, ValidationError) as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Invalid or expired MCP setup authorization"
        ) from error


async def start_setup_oauth(
    request: MCPSetupRequest,
    owner_id: str,
    connection_headers: dict[str, str],
    expected_configuration_fingerprint: str | None = None,
    client_information: OAuthClientInformationFull | None = None,
) -> tuple[OnyxOAuthClientProvider, TransientTokenStorage, str | None]:
    redirect_uri = AnyUrl(mcp_oauth_redirect_uri())
    client_information = client_information or (
        OAuthClientInformationFull(
            client_id=request.oauth_client_id,
            client_secret=request.oauth_client_secret,
            redirect_uris=[redirect_uri],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method=(
                "client_secret_post" if request.oauth_client_secret else "none"
            ),
        )
        if request.oauth_client_id
        else None
    )
    storage = TransientTokenStorage(client_information)

    async def persist_authorization(
        authorization: MCPPendingOAuthAuthorization, context: OAuthContext
    ) -> None:
        if context.client_info is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, "OAuth discovery did not register a client"
            )
        await validate_client_metadata_authorization(
            authorization.authorization_url, context.client_info.client_id
        )
        _store_attempt(
            owner_id,
            authorization.state,
            SetupOAuthAttempt(
                request=request,
                expected_configuration_fingerprint=expected_configuration_fingerprint,
                client_information=context.client_info,
                code_verifier=authorization.code_verifier,
                redirect_uri=redirect_uri,
                protected_resource_metadata=context.protected_resource_metadata,
                oauth_metadata=context.oauth_metadata,
                authorization_server_url=context.auth_server_url,
                protocol_version=context.protocol_version,
                scope=context.client_metadata.scope,
            ),
        )

    provider = make_oauth_provider_with_storage(
        _connection(request),
        storage,
        authorization_request_handler=persist_authorization,
        authorization_state_factory=_setup_state,
    )
    if request.oauth_provider_mode is MCPOAuthProviderMode.KNOWN_PROVIDER:
        if (
            client_information is None
            or not client_information.client_id
            or not request.oauth_authorization_endpoint
            or not request.oauth_token_endpoint
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Known-provider OAuth needs a client and endpoints",
            )
        validate_authorization_params(
            request.oauth_authorization_endpoint,
            request.oauth_additional_auth_params,
            owns_resource=True,
        )
        state = _setup_state()
        pkce = PKCEParameters.generate()
        scope = " ".join(request.oauth_scopes_override or []) or None
        authorization_url = build_authorization_url(
            authorization_url=request.oauth_authorization_endpoint,
            client_id=client_information.client_id,
            redirect_uri=str(redirect_uri),
            state=state,
            scope=scope,
            additional_params=request.oauth_additional_auth_params,
            code_challenge=pkce.code_challenge,
            resource=request.server_url,
            owns_resource=True,
        )
        _store_attempt(
            owner_id,
            state,
            SetupOAuthAttempt(
                request=request,
                expected_configuration_fingerprint=expected_configuration_fingerprint,
                client_information=client_information,
                code_verifier=pkce.code_verifier,
                redirect_uri=redirect_uri,
                oauth_metadata=provider.context.oauth_metadata,
                scope=scope,
                resource=request.server_url,
            ),
        )
        return provider, storage, authorization_url
    outcome = await run_oauth_discovery(
        oauth_provider=provider,
        server_url=request.server_url,
        connection_headers=connection_headers,
        transport=MCPTransport.STREAMABLE_HTTP,
    )
    return (
        provider,
        storage,
        outcome.url if isinstance(outcome, OAuthAuthorizationRedirect) else None,
    )


async def complete_setup_oauth(
    attempt: SetupOAuthAttempt, code: str
) -> tuple[OnyxOAuthClientProvider, TransientTokenStorage]:
    storage = TransientTokenStorage(attempt.client_information)
    provider = make_oauth_provider_with_storage(_connection(attempt.request), storage)
    context = provider.context
    context.client_info = attempt.client_information
    context.client_metadata.redirect_uris = [attempt.redirect_uri]
    context.client_metadata.scope = attempt.scope
    context.oauth_metadata = attempt.oauth_metadata
    context.protected_resource_metadata = attempt.protected_resource_metadata
    context.auth_server_url = attempt.authorization_server_url
    context.protocol_version = attempt.protocol_version
    await provider.complete_authorization_code_exchange(
        code, attempt.code_verifier, resource=attempt.resource
    )
    return provider, storage
