"""Authentication helpers for the Onyx MCP server."""

from collections.abc import Callable
from typing import Any
from typing import Optional
from urllib.parse import unquote

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.auth import TokenVerifier

from onyx.auth.api_key import hash_api_key
from onyx.auth.constants import API_KEY_PREFIX
from onyx.auth.constants import PAT_PREFIX
from onyx.auth.pat import hash_pat
from onyx.db.api_key import fetch_user_for_api_key
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.pat import fetch_user_for_pat
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def _extract_tenant_from_token(token: str, prefix: str) -> str | None:
    """Extract tenant identifier from a token of the form <prefix><tenant>.<random>."""

    if not token.startswith(prefix):
        return None

    parts = token[len(prefix) :].split(".", 1)
    if len(parts) != 2:
        return None

    tenant_id = parts[0]
    return unquote(tenant_id) if tenant_id else None


class OnyxTokenVerifier(TokenVerifier):
    """Verifies PATs and API keys used to access the MCP server."""

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        """
        Verify PAT or API key and return AccessToken with user information.

        Args:
            token: Credential extracted from the Authorization header

        Returns:
            AccessToken with user data in claims, or None if invalid
        """
        try:
            credential_type: str
            hashed_token: str
            fetcher: Callable[[str, Any], Any]
            tenant_prefix: str | None = None

            if token.startswith(PAT_PREFIX):
                credential_type = "pat"
                hashed_token = hash_pat(token)
                fetcher = fetch_user_for_pat
                tenant_prefix = PAT_PREFIX
            elif token.startswith(API_KEY_PREFIX):
                credential_type = "api_key"
                hashed_token = hash_api_key(token)
                fetcher = fetch_user_for_api_key
                tenant_prefix = API_KEY_PREFIX
            else:
                logger.warning("Unsupported credential presented to MCP server")
                return None

            async with get_async_session_context_manager() as db_session:
                user = await fetcher(hashed_token, db_session)

            if user is None:
                logger.warning(
                    "Invalid %s credential: %s...",
                    credential_type,
                    hashed_token[:8],
                )
                return None

            tenant_id = None
            if MULTI_TENANT:
                tenant_id = (
                    _extract_tenant_from_token(token, tenant_prefix)
                    if tenant_prefix
                    else None
                )
                if not tenant_id:
                    logger.error("Multi-tenant mode requires tenant-scoped credentials")
                    return None

            logger.debug("Authenticated %s via %s", user.email, credential_type)

            return AccessToken(
                token=token,
                client_id=user.email,
                scopes=["mcp:use"],
                expires_at=None,
                resource=None,
                claims={
                    "user_id": user.id,
                    "email": user.email,
                    "role": user.role.value,
                    "tenant_id": tenant_id,
                    "credential_type": credential_type,
                    "_user": user,
                },
            )

        except Exception as e:
            logger.error(f"Credential verification error: {e}", exc_info=True)
            return None
