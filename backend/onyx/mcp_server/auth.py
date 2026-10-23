"""Authentication helpers for the Onyx MCP server."""

import time
from typing import Optional

import httpx
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.auth import AccessToken, TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url
from pydantic import AnyHttpUrl, ValidationError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from onyx.auth.constants import (
    OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX,
    OAUTH_PROVIDER_SCOPE,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, onyx_error_to_json_response
from onyx.mcp_server.utils import get_http_client
from onyx.oauth_provider import config as oauth_provider_config
from onyx.oauth_provider.models import OAuthProviderIntrospection
from onyx.server.metrics.mcp_server import MCPAuthResult, record_mcp_auth_result
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests

logger = setup_logger()


class MCPAuthErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        started = False

        async def track_response(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track_response)
        except OnyxError as error:
            if started or scope["type"] != "http":
                raise
            await onyx_error_to_json_response(error)(scope, receive, send)


class OnyxTokenVerifier(TokenVerifier):
    """Validates bearer tokens by delegating to the API server."""

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        """Validate bearer credentials through the API server."""
        if token.startswith(OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX):
            return await self.verify_oauth_token(token)
        try:
            response = await get_http_client().get(
                f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        except Exception as exc:
            record_mcp_auth_result(MCPAuthResult.ERROR)
            logger.error(
                "MCP server failed to reach API /me for authentication: %s",
                exc,
                exc_info=True,
            )
            return None

        if response.status_code != 200:
            record_mcp_auth_result(MCPAuthResult.REJECTED)
            logger.warning(
                "API server rejected MCP auth token with status %s",
                response.status_code,
            )
            return None

        record_mcp_auth_result(MCPAuthResult.SUCCESS)
        return AccessToken(
            token=token,
            client_id="mcp",
            scopes=["mcp:use"],
            expires_at=None,
            resource=None,
            claims={},
        )

    async def verify_oauth_token(self, token: str) -> AccessToken | None:
        settings = oauth_provider_config.OAUTH_PROVIDER_SETTINGS
        if settings is None:
            return None
        try:
            response = await get_http_client().get(
                f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/oauth-provider/introspect",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.RequestError as error:
            record_mcp_auth_result(MCPAuthResult.ERROR)
            raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE) from error
        if response.status_code == OnyxErrorCode.UNAUTHENTICATED.status_code:
            record_mcp_auth_result(MCPAuthResult.REJECTED)
            return None
        if response.status_code == OnyxErrorCode.SUBSCRIPTION_INACTIVE.status_code:
            record_mcp_auth_result(MCPAuthResult.REJECTED)
            raise OnyxError(
                OnyxErrorCode.SUBSCRIPTION_INACTIVE,
                "MCP access is blocked by billing or license restrictions.",
            )
        if response.status_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS.status_code:
            record_mcp_auth_result(MCPAuthResult.REJECTED)
            metadata_url = build_resource_metadata_url(
                AnyHttpUrl(settings.mcp_resource_url)
            )
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                headers={
                    "WWW-Authenticate": (
                        'Bearer error="insufficient_scope", '
                        f'scope="{OAUTH_PROVIDER_SCOPE}", '
                        f'resource_metadata="{metadata_url}"'
                    )
                },
            )
        if not response.is_success:
            record_mcp_auth_result(MCPAuthResult.ERROR)
            raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
        try:
            info = OAuthProviderIntrospection.model_validate_json(response.content)
        except ValidationError as error:
            record_mcp_auth_result(MCPAuthResult.ERROR)
            raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE) from error
        if (
            info.resource != settings.mcp_resource_url
            or info.expires_at <= time.time()
            or set(info.scopes) != {OAUTH_PROVIDER_SCOPE}
            or not info.client_id
        ):
            record_mcp_auth_result(MCPAuthResult.REJECTED)
            return None
        record_mcp_auth_result(MCPAuthResult.SUCCESS)
        return AccessToken(
            token=token,
            client_id=info.client_id,
            scopes=info.scopes,
            expires_at=info.expires_at,
            resource=info.resource,
            subject=info.subject,
        )


class OnyxRemoteAuthProvider(RemoteAuthProvider):
    def _get_resource_url(self, path: str | None = None) -> AnyHttpUrl:
        del path
        # The public MCP URL must not inherit the upstream's internal root path.
        return self.base_url


def build_mcp_server_auth() -> TokenVerifier | RemoteAuthProvider:
    verifier = OnyxTokenVerifier()
    settings = oauth_provider_config.OAUTH_PROVIDER_SETTINGS
    if settings is None:
        return verifier
    return OnyxRemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl(settings.issuer_url)],
        base_url=settings.mcp_resource_url.rstrip("/"),
        scopes_supported=[OAUTH_PROVIDER_SCOPE],
    )
