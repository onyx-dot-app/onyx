"""Pure helpers for MCP OAuth bearer token values."""

import re
import secrets
from enum import Enum

from pydantic import BaseModel

from onyx.auth.constants import (
    MCP_OAUTH_ACCESS_TOKEN_PREFIX,
    MCP_OAUTH_REFRESH_TOKEN_PREFIX,
)
from onyx.auth.pat import hash_pat

_MCP_OAUTH_TENANT_PATTERN = r"[A-Za-z0-9_-]{1,63}"
_MCP_OAUTH_SECRET_PATTERN = r"[A-Za-z0-9_-]{43}"
_MCP_OAUTH_TENANT_RE = re.compile(rf"\A{_MCP_OAUTH_TENANT_PATTERN}\Z")
_MCP_OAUTH_ACCESS_TOKEN_RE = re.compile(
    rf"\A{re.escape(MCP_OAUTH_ACCESS_TOKEN_PREFIX)}"
    rf"(?P<tenant_id>{_MCP_OAUTH_TENANT_PATTERN})"
    rf"\.(?P<secret>{_MCP_OAUTH_SECRET_PATTERN})\Z"
)
_MCP_OAUTH_REFRESH_TOKEN_RE = re.compile(
    rf"\A{re.escape(MCP_OAUTH_REFRESH_TOKEN_PREFIX)}"
    rf"(?P<tenant_id>{_MCP_OAUTH_TENANT_PATTERN})"
    rf"\.(?P<secret>{_MCP_OAUTH_SECRET_PATTERN})\Z"
)


class MCPOAuthTokenKind(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


class ParsedMCPOAuthToken(BaseModel):
    tenant_id: str
    kind: MCPOAuthTokenKind
    token_hash: str


def generate_mcp_oauth_token(tenant_id: str, kind: MCPOAuthTokenKind) -> str:
    if _MCP_OAUTH_TENANT_RE.fullmatch(tenant_id) is None:
        raise ValueError("Invalid MCP OAuth tenant ID")
    if kind == MCPOAuthTokenKind.ACCESS:
        prefix = MCP_OAUTH_ACCESS_TOKEN_PREFIX
    elif kind == MCPOAuthTokenKind.REFRESH:
        prefix = MCP_OAUTH_REFRESH_TOKEN_PREFIX
    else:
        raise ValueError("Invalid MCP OAuth token kind")
    return f"{prefix}{tenant_id}.{secrets.token_urlsafe(32)}"


def parse_mcp_oauth_token(token: str) -> ParsedMCPOAuthToken | None:
    for kind, token_re in (
        (MCPOAuthTokenKind.ACCESS, _MCP_OAUTH_ACCESS_TOKEN_RE),
        (MCPOAuthTokenKind.REFRESH, _MCP_OAUTH_REFRESH_TOKEN_RE),
    ):
        match = token_re.fullmatch(token)
        if match is None:
            continue
        return ParsedMCPOAuthToken(
            tenant_id=match.group("tenant_id"),
            kind=kind,
            token_hash=hash_pat(token),
        )
    return None
