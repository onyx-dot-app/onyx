"""Authentication helpers for the Onyx MCP server."""

from typing import Optional

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.auth import TokenVerifier
from prometheus_client import Counter

from onyx.mcp_server.utils import get_http_client
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests

logger = setup_logger()

MCP_SERVER_AUTH_TOTAL = Counter(
    "onyx_mcp_server_auth_total",
    "MCP server authentication attempts",
    ["result"],  # success, rejected, error
)


class OnyxTokenVerifier(TokenVerifier):
    """Validates bearer tokens by delegating to the API server."""

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        """Call API /me to verify the token, return minimal AccessToken on success."""
        try:
            response = await get_http_client().get(
                f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        except Exception as exc:
            MCP_SERVER_AUTH_TOTAL.labels(result="error").inc()
            logger.error(
                "MCP server failed to reach API /me for authentication: %s",
                exc,
                exc_info=True,
            )
            return None

        if response.status_code != 200:
            MCP_SERVER_AUTH_TOTAL.labels(result="rejected").inc()
            logger.warning(
                "API server rejected MCP auth token with status %s",
                response.status_code,
            )
            return None

        MCP_SERVER_AUTH_TOTAL.labels(result="success").inc()
        return AccessToken(
            token=token,
            client_id="mcp",
            scopes=["mcp:use"],
            expires_at=None,
            resource=None,
            claims={},
        )
