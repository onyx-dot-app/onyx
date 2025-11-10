"""Shared authentication utilities for bearer token extraction and validation."""

from collections.abc import Callable
from urllib.parse import unquote

from fastapi import Request

from onyx.auth.constants import API_KEY_HEADER_ALTERNATIVE_NAME
from onyx.auth.constants import API_KEY_HEADER_NAME
from onyx.auth.constants import API_KEY_PREFIX
from onyx.auth.constants import BEARER_PREFIX
from onyx.auth.constants import DEPRECATED_API_KEY_PREFIX
from onyx.auth.constants import PAT_PREFIX


def get_hashed_bearer_token_from_request(
    request: Request,
    valid_prefixes: list[str],
    hash_fn: Callable[[str], str],
    allow_non_bearer: bool = False,
) -> str | None:
    """Generic extraction and hashing of bearer tokens from request headers.

    Args:
        request: The FastAPI request
        valid_prefixes: List of valid token prefixes (e.g., ["on_", "onyx_pat_"])
        hash_fn: Function to hash the token (e.g., hash_api_key or hash_pat)
        allow_non_bearer: If True, accept raw tokens without "Bearer " prefix

    Returns:
        Hashed token if valid format, else None
    """
    auth_header = request.headers.get(
        API_KEY_HEADER_ALTERNATIVE_NAME
    ) or request.headers.get(API_KEY_HEADER_NAME)

    if not auth_header:
        return None

    # Handle bearer format
    if auth_header.startswith(BEARER_PREFIX):
        token = auth_header[len(BEARER_PREFIX) :].strip()
    elif allow_non_bearer:
        token = auth_header
    else:
        return None

    # Check if token starts with any valid prefix
    if valid_prefixes:
        valid = any(token.startswith(prefix) for prefix in valid_prefixes)
        if not valid:
            return None

    return hash_fn(token)


def _extract_tenant_from_bearer_token(
    request: Request, valid_prefixes: list[str]
) -> str | None:
    """Generic tenant extraction from bearer token. Returns None if invalid format.

    Args:
        request: The FastAPI request
        valid_prefixes: List of valid token prefixes (e.g., ["on_", "dn_"])

    Returns:
        Tenant ID if found in format <prefix><tenant>.<random>, else None
    """
    auth_header = request.headers.get(
        API_KEY_HEADER_ALTERNATIVE_NAME
    ) or request.headers.get(API_KEY_HEADER_NAME)

    if not auth_header or not auth_header.startswith(BEARER_PREFIX):
        return None

    token = auth_header[len(BEARER_PREFIX) :].strip()

    # Check if token starts with any valid prefix
    matched_prefix = None
    for prefix in valid_prefixes:
        if token.startswith(prefix):
            matched_prefix = prefix
            break

    if not matched_prefix:
        return None

    # Parse tenant from token format: <prefix><tenant>.<random>
    parts = token[len(matched_prefix) :].split(".", 1)
    if len(parts) != 2:
        return None

    tenant_id = parts[0]
    return unquote(tenant_id) if tenant_id else None


def extract_tenant_from_auth_header(request: Request) -> str | None:
    """Extract tenant ID from API key or PAT header.

    Unified function for extracting tenant from any bearer token (API key or PAT).
    Checks all known token prefixes in order.

    Returns:
        Tenant ID if found, else None
    """
    return _extract_tenant_from_bearer_token(
        request, [API_KEY_PREFIX, DEPRECATED_API_KEY_PREFIX, PAT_PREFIX]
    )
