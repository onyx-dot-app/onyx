"""Query-time Notion access check. Notion's API exposes no page permissions, so
each Notion page in a user's results is fetched through Notion MCP with that
user's own OAuth token: a fetch that succeeds proves access, object_not_found
or validation_error denies it, and anything else (rate limit, transport
failure, no connection) drops the page for this query without caching."""

import hashlib
import json
from enum import Enum
from urllib.parse import urlparse

from mcp.client.auth import OAuthClientProvider
from mcp.types import CallToolResult

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.context.search.models import InferenceChunk
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import get_all_mcp_servers
from onyx.db.models import User
from onyx.db.users import get_user_by_email
from onyx.server.features.mcp.client import (
    call_mcp_tools_in_one_session,
    process_mcp_result,
)
from onyx.server.features.mcp.credentials import (
    ResolvedMCPCredentials,
    resolve_mcp_credentials,
)
from onyx.server.features.mcp.models import MCPServerConnection
from onyx.server.features.mcp.oauth import mcp_call_auth
from onyx.utils.logger import setup_logger

logger = setup_logger()

NOTION_MCP_HOST = "mcp.notion.com"
NOTION_FETCH_TOOL = "notion-fetch"
# Notion answers object_not_found for pages the user cannot see, the same as
# for missing ones, and validation_error for ids it cannot parse. Both deny.
_DENIED_ERROR_CODES = {"object_not_found", "validation_error"}
# 50 fetches, 10 at a time, measured about 1.5 s and stayed under the limit
# Notion MCP enforced at roughly 150 calls a minute per token. Pages past the
# cap are dropped for this query.
MAX_PAGES_PER_QUERY = 50
MAX_PARALLEL_FETCHES = 10
# Notion gives no signal when sharing changes, so a time bound is the only
# invalidation available.
ACCESS_CACHE_TTL_S = 10 * 60
_CACHE_PREFIX = "notion_page_access"
_CACHED_ALLOWED = b"1"
_CACHED_DENIED = b"0"


class PageAccess(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


def censor_notion_chunks(
    chunks: list[InferenceChunk], user_email: str
) -> list[InferenceChunk]:
    """Keep the chunks of pages the user can open in Notion, in result order."""
    page_ids: list[str] = list(dict.fromkeys(chunk.document_id for chunk in chunks))
    allowed_page_ids: set[str] = _allowed_page_ids(page_ids, user_email)
    return [chunk for chunk in chunks if chunk.document_id in allowed_page_ids]


def _grant_fingerprint(credentials: ResolvedMCPCredentials) -> str:
    """Identifies the exact Notion grant, so answers cached under one account
    or token never serve another after a reconnect."""
    bearer: str = credentials.build_headers().get("Authorization", "")
    return hashlib.sha256(bearer.encode()).hexdigest()[:16]


def _cache_key(user_email: str, grant: str, page_id: str) -> str:
    return f"{_CACHE_PREFIX}:{user_email}:{grant}:{page_id}"


def _allowed_page_ids(page_ids: list[str], user_email: str) -> set[str]:
    """Pages the user's current Notion grant can open. Cached answers count
    only for that grant while it still works, and a session that fails hides
    everything rather than falling back to them."""
    connection: tuple[MCPServerConnection, ResolvedMCPCredentials] | None = (
        _usable_notion_connection(user_email)
    )
    if connection is None:
        logger.info(
            "Notion censor: %s has no working per-user Notion MCP connection",
            user_email,
        )
        return set()
    mcp_server, credentials = connection
    grant: str = _grant_fingerprint(credentials)

    cache: CacheBackend = get_cache_backend()
    allowed: set[str] = set()
    unchecked: list[str] = []
    for page_id in page_ids:
        cached: bytes | None = cache.get(_cache_key(user_email, grant, page_id))
        if cached == _CACHED_ALLOWED:
            allowed.add(page_id)
        elif cached != _CACHED_DENIED:
            unchecked.append(page_id)

    if len(unchecked) > MAX_PAGES_PER_QUERY:
        logger.warning(
            "Notion censor checking %s of %s pages for %s",
            MAX_PAGES_PER_QUERY,
            len(unchecked),
            user_email,
        )
        unchecked = unchecked[:MAX_PAGES_PER_QUERY]
    if not unchecked:
        return allowed

    answers: list[PageAccess] | None = _fetch_pages(mcp_server, credentials, unchecked)
    if answers is None:
        return set()
    for page_id, access in zip(unchecked, answers, strict=True):
        if access == PageAccess.UNKNOWN:
            continue
        cache.set(
            _cache_key(user_email, grant, page_id),
            _CACHED_ALLOWED if access == PageAccess.ALLOWED else _CACHED_DENIED,
            ex=ACCESS_CACHE_TTL_S,
        )
        if access == PageAccess.ALLOWED:
            allowed.add(page_id)
    return allowed


def _usable_notion_connection(
    user_email: str,
) -> tuple[MCPServerConnection, ResolvedMCPCredentials] | None:
    """The first per-user OAuth Notion MCP server this user has a working
    grant for, copied out of the session. An admin-level server would act as
    the admin, so it never qualifies."""
    with get_session_with_current_tenant() as db_session:
        user: User | None = get_user_by_email(user_email, db_session)
        if user is None:
            logger.warning("Notion censor found no user for %s", user_email)
            return None
        for mcp_server in get_all_mcp_servers(db_session):
            if (
                urlparse(mcp_server.server_url).hostname != NOTION_MCP_HOST
                or mcp_server.auth_type != MCPAuthenticationType.OAUTH
                or mcp_server.auth_performer != MCPAuthenticationPerformer.PER_USER
            ):
                continue
            credentials = resolve_mcp_credentials(mcp_server, user, db_session)
            if credentials.can_authenticate() and credentials.connection_config_id:
                return MCPServerConnection.model_validate(mcp_server), credentials
    return None


def _fetch_pages(
    mcp_server: MCPServerConnection,
    credentials: ResolvedMCPCredentials,
    page_ids: list[str],
) -> list[PageAccess] | None:
    """One access answer per page id from fetching each page through Notion
    MCP as the user, or None when the session fails. Runs with no DB session
    open, since the OAuth refresh can wait on a lock and call out."""
    headers: dict[str, str] = credentials.build_headers()
    auth: OAuthClientProvider | None = mcp_call_auth(mcp_server, credentials, headers)
    try:
        results: list[CallToolResult] = call_mcp_tools_in_one_session(
            mcp_server.server_url,
            [(NOTION_FETCH_TOOL, {"id": page_id}) for page_id in page_ids],
            MAX_PARALLEL_FETCHES,
            connection_headers=headers,
            transport=mcp_server.transport or MCPTransport.STREAMABLE_HTTP,
            auth=auth,
        )
    except Exception:
        logger.exception(
            "Notion censor could not fetch pages as %s", credentials.user_email
        )
        return None
    return [classify_fetch_result(result) for result in results]


def classify_fetch_result(result: CallToolResult) -> PageAccess:
    """A successful fetch means the user can open the page. A Notion error
    with a denying code means they cannot. Anything else, such as the plain
    text rate-limit error, is unknown."""
    if not result.isError:
        return PageAccess.ALLOWED
    try:
        payload: object = json.loads(process_mcp_result(result))
    except ValueError:
        return PageAccess.UNKNOWN
    if not isinstance(payload, dict):
        return PageAccess.UNKNOWN
    return (
        PageAccess.DENIED
        if payload.get("code") in _DENIED_ERROR_CODES
        else PageAccess.UNKNOWN
    )
