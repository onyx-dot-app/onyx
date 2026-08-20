"""Resumable browser OAuth flows for MCP connections."""

import asyncio
import secrets
from dataclasses import dataclass

import httpx
from mcp.client.auth import OAuthClientProvider, PKCEParameters
from mcp.client.auth.oauth2 import OAuthContext
from mcp.client.auth.utils import (
    build_protected_resource_metadata_discovery_urls,
    create_oauth_metadata_request,
    handle_protected_resource_response,
)
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from onyx.auth.oauth_token_manager import (
    OAuthFlowParams,
    build_oauth_authorization_url,
)
from onyx.cache.factory import get_cache_backend
from onyx.db.enums import MCPOAuthProviderMode, MCPTransport
from onyx.db.models import MCPServer
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth.authorization_attempt import (
    AuthorizationAttemptStore,
    generate_authorization_state,
)
from onyx.server.features.mcp.client import initialize_mcp_client
from onyx.server.features.mcp.client_metadata import mcp_oauth_redirect_uri
from onyx.server.features.mcp.credentials import (
    mcp_oauth_client_information_fingerprint,
    mcp_oauth_connection_headers_fingerprint,
)
from onyx.server.features.mcp.models import (
    DENYLISTED_MCP_HEADERS,
    RESERVED_MCP_OAUTH_AUTHORIZATION_PARAMS,
    MCPOAuthFlowState,
    MCPOAuthServerSnapshot,
    MCPPendingOAuthAuthorization,
)
from onyx.server.features.mcp.oauth import (
    OAUTH_HTTP_TIMEOUT_SECONDS,
    MCPClientRegistrationConflict,
    OAuthAuthorizationRequired,
    OnyxOAuthClientProvider,
    make_oauth_provider,
)
from onyx.server.features.mcp.ssrf import (
    mcp_oauth_challenge_httpx_client_factory,
    mcp_ssrf_httpx_client_factory,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

MCP_OAUTH_FLOW_TTL_SECONDS = 10 * 60


@dataclass(frozen=True, slots=True)
class OAuthAlreadyAuthenticated:
    pass


@dataclass(frozen=True, slots=True)
class OAuthAuthorizationRedirect:
    url: str


type OAuthStartResult = OAuthAlreadyAuthenticated | OAuthAuthorizationRedirect


def _known_provider_flow_params(
    mcp_server: MCPServer,
    client_information: OAuthClientInformationFull,
) -> OAuthFlowParams:
    if (
        not mcp_server.oauth_authorization_endpoint
        or not mcp_server.oauth_token_endpoint
        or not client_information.client_id
    ):
        raise OnyxError(
            OnyxErrorCode.MISSING_REQUIRED_FIELD,
            "Known-provider OAuth requires oauth_authorization_endpoint, "
            "oauth_token_endpoint, and a non-empty client_id.",
        )
    reserved_params = RESERVED_MCP_OAUTH_AUTHORIZATION_PARAMS.intersection(
        mcp_server.oauth_additional_auth_params or {}
    )
    if reserved_params:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Known-provider OAuth additional parameters cannot override: "
            f"{', '.join(sorted(reserved_params))}",
        )
    return OAuthFlowParams(
        authorization_url=mcp_server.oauth_authorization_endpoint,
        token_url=mcp_server.oauth_token_endpoint,
        client_id=client_information.client_id,
        client_secret=client_information.client_secret,
        scopes=mcp_server.oauth_scopes_override,
        additional_params=mcp_server.oauth_additional_auth_params,
    )


def _snapshot_server_configuration(
    mcp_server: MCPServer,
) -> MCPOAuthServerSnapshot:
    return MCPOAuthServerSnapshot(
        server_url=mcp_server.server_url,
        auth_type=mcp_server.auth_type,
        auth_performer=mcp_server.auth_performer,
        provider_mode=mcp_server.oauth_provider_mode,
        transport=mcp_server.transport,
        authorization_endpoint=mcp_server.oauth_authorization_endpoint,
        token_endpoint=mcp_server.oauth_token_endpoint,
        scopes=mcp_server.oauth_scopes_override,
        additional_authorization_parameters=mcp_server.oauth_additional_auth_params,
    )


def _build_mcp_oauth_attempt_payload(
    *,
    mcp_server: MCPServer,
    connection_config_id: int,
    return_path: str,
    code_verifier: str,
    connection_headers: dict[str, str],
    client_information: OAuthClientInformationFull,
    redirect_uri: AnyUrl,
    resource: str | None = None,
    context: OAuthContext | None = None,
) -> MCPOAuthFlowState:
    return MCPOAuthFlowState(
        server_id=mcp_server.id,
        connection_config_id=connection_config_id,
        return_path=return_path,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        server_snapshot=_snapshot_server_configuration(mcp_server),
        connection_headers_fingerprint=mcp_oauth_connection_headers_fingerprint(
            connection_headers
        ),
        client_information_fingerprint=mcp_oauth_client_information_fingerprint(
            client_information,
        ),
        protected_resource_metadata=(
            context.protected_resource_metadata if context else None
        ),
        oauth_metadata=context.oauth_metadata if context else None,
        authorization_server_url=context.auth_server_url if context else None,
        protocol_version=context.protocol_version if context else None,
        scope=context.client_metadata.scope if context else None,
        resource=AnyUrl(resource) if resource else None,
    )


def validate_mcp_oauth_flow_configuration(
    flow: MCPOAuthFlowState,
    mcp_server: MCPServer,
    connection_headers: dict[str, str],
) -> None:
    if flow.server_snapshot != _snapshot_server_configuration(mcp_server):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "MCP server configuration changed while authorization was pending.",
        )
    current_headers_fingerprint = mcp_oauth_connection_headers_fingerprint(
        connection_headers
    )
    if not secrets.compare_digest(
        flow.connection_headers_fingerprint, current_headers_fingerprint
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "MCP connection headers changed while authorization was pending.",
        )


def _restore_mcp_oauth_context(
    flow: MCPOAuthFlowState,
    context: OAuthContext,
    client_information: OAuthClientInformationFull,
) -> None:
    """Apply a persisted attempt at the SDK boundary used for completion."""
    if flow.server_snapshot.provider_mode is MCPOAuthProviderMode.AUTO_DISCOVERY:
        context.protected_resource_metadata = flow.protected_resource_metadata
        context.oauth_metadata = flow.oauth_metadata
        context.auth_server_url = flow.authorization_server_url
        context.protocol_version = flow.protocol_version
    context.client_metadata.scope = flow.scope
    context.client_metadata.redirect_uris = [flow.redirect_uri]
    context.client_info = client_information


def _make_completion_provider(
    flow: MCPOAuthFlowState,
    mcp_server: MCPServer,
    client_information: OAuthClientInformationFull,
) -> OnyxOAuthClientProvider:
    provider = make_oauth_provider(
        mcp_server,
        flow.connection_config_id,
        mcp_server.admin_connection_config_id,
        load_stored_tokens=False,
        expected_connection_headers_fingerprint=(flow.connection_headers_fingerprint),
        expected_client_information_fingerprint=(flow.client_information_fingerprint),
    )
    _restore_mcp_oauth_context(flow, provider.context, client_information)
    return provider


def mcp_oauth_attempt_store() -> AuthorizationAttemptStore[MCPOAuthFlowState]:
    return AuthorizationAttemptStore(
        get_cache_backend(),
        namespace="mcp",
        payload_type=MCPOAuthFlowState,
        ttl_seconds=MCP_OAUTH_FLOW_TTL_SECONDS,
    )


def _authorization_handoffs(
    error: Exception,
) -> list[OAuthAuthorizationRequired] | None:
    if isinstance(error, OAuthAuthorizationRequired):
        return [error]
    if isinstance(error, ExceptionGroup):
        handoffs: list[OAuthAuthorizationRequired] = []
        for nested_error in error.exceptions:
            nested_handoffs = _authorization_handoffs(nested_error)
            if nested_handoffs is None:
                return None
            handoffs.extend(nested_handoffs)
        return handoffs
    return None


def _authorization_handoff_from_error(
    error: Exception,
) -> OAuthAuthorizationRequired:
    handoffs = _authorization_handoffs(error)
    if handoffs is None:
        raise error
    if len(handoffs) != 1:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "MCP OAuth discovery produced multiple authorization redirects.",
        )
    return handoffs[0]


def _authorization_redirect_from_group(
    error: ExceptionGroup,
) -> OAuthAuthorizationRedirect:
    matching_errors, unexpected_errors = error.split(OAuthAuthorizationRequired)
    if unexpected_errors is not None:
        raise unexpected_errors
    assert matching_errors is not None
    authorization_required = _authorization_handoff_from_error(matching_errors)
    authorization = authorization_required.authorization
    return OAuthAuthorizationRedirect(authorization.authorization_url)


async def _start_oauth_from_well_known_metadata(
    oauth_provider: OAuthClientProvider,
    server_url: str,
    connection_headers: dict[str, str],
) -> None:
    timeout = httpx.Timeout(OAUTH_HTTP_TIMEOUT_SECONDS)
    discovery_urls = build_protected_resource_metadata_discovery_urls(None, server_url)
    metadata_url: str | None = None
    excluded_headers = DENYLISTED_MCP_HEADERS | {"authorization"}
    discovery_headers = {
        key: value
        for key, value in connection_headers.items()
        if key.lower() not in excluded_headers
    }
    async with mcp_ssrf_httpx_client_factory(timeout=timeout) as client:
        for url in discovery_urls:
            request = create_oauth_metadata_request(url)
            request.headers.update(discovery_headers)
            response = await client.send(request)
            if await handle_protected_resource_response(response) is not None:
                metadata_url = url
                break

    if metadata_url is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth auto-discovery could not find protected resource metadata at "
            "the MCP server's well-known URI.",
        )

    async with mcp_oauth_challenge_httpx_client_factory(
        server_url,
        metadata_url,
        oauth_provider,
        timeout,
    ) as client:
        await client.get(server_url)


def start_known_provider_oauth_flow(
    *,
    mcp_server: MCPServer,
    user_id: str,
    connection_config_id: int,
    return_path: str,
    connection_headers: dict[str, str],
    client_information: OAuthClientInformationFull,
    include_resource_param: bool,
) -> OAuthAuthorizationRedirect:
    state = generate_authorization_state()
    pkce = PKCEParameters.generate()
    redirect_uri = mcp_oauth_redirect_uri()
    resource = mcp_server.server_url if include_resource_param else None
    authorization_url = build_oauth_authorization_url(
        _known_provider_flow_params(mcp_server, client_information),
        redirect_uri,
        state,
        code_challenge=pkce.code_challenge,
        resource=resource,
    )
    mcp_oauth_attempt_store().store(
        owner_id=user_id,
        state=state,
        payload=_build_mcp_oauth_attempt_payload(
            mcp_server=mcp_server,
            connection_config_id=connection_config_id,
            return_path=return_path,
            code_verifier=pkce.code_verifier,
            connection_headers=connection_headers,
            client_information=client_information,
            redirect_uri=AnyUrl(redirect_uri),
            resource=resource,
        ),
    )
    return OAuthAuthorizationRedirect(authorization_url)


async def _start_auto_discovery_oauth_flow_once(
    mcp_server: MCPServer,
    user_id: str,
    return_path: str,
    connection_config_id: int,
    shared_client_config_id: int | None,
    connection_headers: dict[str, str],
    transport: MCPTransport,
    credentials_usable: bool,
    force_reauthentication: bool = False,
) -> OAuthStartResult:
    """Return the explicit outcome of probing or beginning authorization."""

    async def persist_authorization_request(
        authorization: MCPPendingOAuthAuthorization, context: OAuthContext
    ) -> None:
        if context.client_info is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "MCP OAuth discovery did not produce client registration information.",
            )
        redirect_uris = context.client_metadata.redirect_uris
        if not redirect_uris:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "MCP OAuth discovery did not produce a redirect URI.",
            )
        mcp_oauth_attempt_store().store(
            owner_id=user_id,
            state=authorization.state,
            payload=_build_mcp_oauth_attempt_payload(
                mcp_server=mcp_server,
                connection_config_id=connection_config_id,
                return_path=return_path,
                code_verifier=authorization.code_verifier,
                connection_headers=connection_headers,
                client_information=context.client_info,
                redirect_uri=redirect_uris[0],
                context=context,
            ),
        )

    oauth_provider = make_oauth_provider(
        mcp_server,
        connection_config_id,
        shared_client_config_id,
        load_stored_tokens=not force_reauthentication,
        authorization_request_handler=persist_authorization_request,
    )
    use_authenticated_connection = credentials_usable and not force_reauthentication
    oauth_connection_headers = (
        {
            key: value
            for key, value in connection_headers.items()
            if key.lower() != "authorization"
        }
        if force_reauthentication
        else connection_headers
    )
    probe_transport = (
        transport if use_authenticated_connection else MCPTransport.STREAMABLE_HTTP
    )

    try:
        async with asyncio.timeout(OAUTH_HTTP_TIMEOUT_SECONDS):
            try:
                await initialize_mcp_client(
                    mcp_server.server_url,
                    connection_headers=oauth_connection_headers,
                    transport=probe_transport,
                    auth=oauth_provider,
                )
            except OAuthAuthorizationRequired as authorization_required:
                return OAuthAuthorizationRedirect(
                    authorization_required.authorization.authorization_url
                )
            except ExceptionGroup as error:
                return _authorization_redirect_from_group(error)
            except Exception as error:
                if _client_registration_conflict(error) is not None:
                    raise
                if (
                    use_authenticated_connection
                    or oauth_provider.context.is_token_valid()
                ):
                    raise
                logger.info(
                    "Initial MCP OAuth probe failed; trying well-known discovery",
                    exc_info=True,
                )

            if use_authenticated_connection or oauth_provider.context.is_token_valid():
                return OAuthAlreadyAuthenticated()

            try:
                await _start_oauth_from_well_known_metadata(
                    oauth_provider,
                    mcp_server.server_url,
                    oauth_connection_headers,
                )
            except OAuthAuthorizationRequired as authorization_required:
                return OAuthAuthorizationRedirect(
                    authorization_required.authorization.authorization_url
                )
            except ExceptionGroup as error:
                return _authorization_redirect_from_group(error)
    except TimeoutError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Timed out during MCP OAuth discovery.",
        ) from error

    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        "OAuth auto-discovery did not produce an authorization redirect.",
    )


def _client_registration_conflict(
    error: BaseException,
) -> MCPClientRegistrationConflict | None:
    if isinstance(error, MCPClientRegistrationConflict):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested_error in error.exceptions:
            if conflict := _client_registration_conflict(nested_error):
                return conflict
    return None


async def start_auto_discovery_oauth_flow(
    mcp_server: MCPServer,
    user_id: str,
    return_path: str,
    connection_config_id: int,
    shared_client_config_id: int | None,
    connection_headers: dict[str, str],
    transport: MCPTransport,
    credentials_usable: bool,
    force_reauthentication: bool = False,
) -> OAuthStartResult:
    """Start discovery, retrying once when concurrent DCR elects a winner."""
    for attempt in range(2):
        try:
            return await _start_auto_discovery_oauth_flow_once(
                mcp_server=mcp_server,
                user_id=user_id,
                return_path=return_path,
                connection_config_id=connection_config_id,
                shared_client_config_id=shared_client_config_id,
                connection_headers=connection_headers,
                transport=transport,
                credentials_usable=credentials_usable,
                force_reauthentication=force_reauthentication,
            )
        except Exception as error:
            if _client_registration_conflict(error) is None or attempt == 1:
                raise
            logger.info(
                "Concurrent MCP client registration won; retrying OAuth discovery"
            )
    raise AssertionError("OAuth discovery retry loop exhausted")


async def complete_mcp_oauth_flow(
    flow: MCPOAuthFlowState,
    mcp_server: MCPServer,
    client_information: OAuthClientInformationFull,
    authorization_code: str,
) -> None:
    provider = _make_completion_provider(flow, mcp_server, client_information)
    await provider.complete_authorization_code_exchange(
        authorization_code,
        flow.code_verifier,
        resource=str(flow.resource) if flow.resource else None,
    )
