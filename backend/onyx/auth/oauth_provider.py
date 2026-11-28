"""Pure helpers for OAuth provider bearer token values."""

import re
import secrets
from collections.abc import Iterable
from enum import Enum

from pydantic import BaseModel

from onyx.auth.constants import (
    OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX,
    OAUTH_PROVIDER_CODE_PREFIX,
    OAUTH_PROVIDER_REFRESH_TOKEN_PREFIX,
    OAUTH_PROVIDER_SCOPES,
    OAUTH_PROVIDER_SECRET_PATTERN,
    OAUTH_PROVIDER_TENANT_PATTERN,
)
from onyx.auth.pat import hash_pat
from onyx.db.enums import Permission

_OAUTH_PROVIDER_TENANT_RE = re.compile(rf"\A{OAUTH_PROVIDER_TENANT_PATTERN}\Z")
_OAUTH_PROVIDER_ACCESS_TOKEN_RE = re.compile(
    rf"\A{re.escape(OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX)}"
    rf"(?P<tenant_id>{OAUTH_PROVIDER_TENANT_PATTERN})"
    rf"\.(?P<secret>{OAUTH_PROVIDER_SECRET_PATTERN})\Z"
)
_OAUTH_PROVIDER_REFRESH_TOKEN_RE = re.compile(
    rf"\A{re.escape(OAUTH_PROVIDER_REFRESH_TOKEN_PREFIX)}"
    rf"(?P<tenant_id>{OAUTH_PROVIDER_TENANT_PATTERN})"
    rf"\.(?P<secret>{OAUTH_PROVIDER_SECRET_PATTERN})\Z"
)

_OAUTH_PROVIDER_CODE_RE = re.compile(
    rf"\A{re.escape(OAUTH_PROVIDER_CODE_PREFIX)}"
    rf"(?P<tenant_id>{OAUTH_PROVIDER_TENANT_PATTERN})"
    rf"\.(?P<secret>{OAUTH_PROVIDER_SECRET_PATTERN})\Z"
)


class OAuthProviderTokenKind(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


class ParsedOAuthProviderToken(BaseModel):
    tenant_id: str
    kind: OAuthProviderTokenKind
    token_hash: str


def generate_oauth_provider_token(tenant_id: str, kind: OAuthProviderTokenKind) -> str:
    if _OAUTH_PROVIDER_TENANT_RE.fullmatch(tenant_id) is None:
        raise ValueError("Invalid OAuth provider tenant ID")
    if kind == OAuthProviderTokenKind.ACCESS:
        prefix = OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX
    elif kind == OAuthProviderTokenKind.REFRESH:
        prefix = OAUTH_PROVIDER_REFRESH_TOKEN_PREFIX
    else:
        raise ValueError("Invalid OAuth provider token kind")
    return f"{prefix}{tenant_id}.{secrets.token_urlsafe(32)}"


def parse_oauth_provider_token(token: str) -> ParsedOAuthProviderToken | None:
    for kind, token_re in (
        (OAuthProviderTokenKind.ACCESS, _OAUTH_PROVIDER_ACCESS_TOKEN_RE),
        (OAuthProviderTokenKind.REFRESH, _OAUTH_PROVIDER_REFRESH_TOKEN_RE),
    ):
        match = token_re.fullmatch(token)
        if match is None:
            continue
        return ParsedOAuthProviderToken(
            tenant_id=match.group("tenant_id"),
            kind=kind,
            token_hash=hash_pat(token),
        )
    return None


def generate_oauth_provider_code(tenant_id: str) -> str:
    """An authorization code that names its tenant, so the token endpoint can find
    it without a tenant session. The tenant is only a lookup hint: the code is
    stored under a hash of the whole value, so editing the tenant misses."""
    if _OAUTH_PROVIDER_TENANT_RE.fullmatch(tenant_id) is None:
        raise ValueError("Invalid OAuth provider tenant ID")
    return f"{OAUTH_PROVIDER_CODE_PREFIX}{tenant_id}.{secrets.token_urlsafe(32)}"


def parse_oauth_provider_code_tenant(code: str) -> str | None:
    match = _OAUTH_PROVIDER_CODE_RE.fullmatch(code)
    return match.group("tenant_id") if match is not None else None


def is_supported_oauth_provider_scope_request(scopes: Iterable[str]) -> bool:
    """A client may ask for any of the scopes. Its grant carries all of them."""
    requested = set(scopes)
    return bool(requested) and requested <= set(OAUTH_PROVIDER_SCOPES)


def is_valid_oauth_provider_grant_scope(scopes: Iterable[str]) -> bool:
    granted = set(scopes)
    return Permission.READ_SEARCH.value in granted and granted <= set(
        OAUTH_PROVIDER_SCOPES
    )
