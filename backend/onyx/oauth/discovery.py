"""Best-effort PKCE capability discovery for configured OAuth endpoints."""

import json
import time
from urllib.parse import urlsplit, urlunsplit

import requests
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
)

from onyx.auth.oauth_token_manager import validate_oauth_endpoint_url
from onyx.oauth.models import PKCESupport
from onyx.server.security.models import outbound_ssrf_params
from onyx.server.security.store import get_security_settings
from onyx.utils.url import SSRFException, ssrf_safe_get

_DISCOVERY_BUDGET_SECONDS = 10.0
_REQUEST_TIMEOUT_SECONDS = 0.75
_MAX_METADATA_BYTES = 64 * 1024
_MAX_ISSUER_PARENTS = 3


def _metadata_support(
    body: bytes,
    issuer: str,
    authorization_url: str,
    token_url: str,
) -> PKCESupport:
    metadata = json.loads(body)
    if not isinstance(metadata, dict) or (
        metadata.get("issuer") != issuer
        or metadata.get("authorization_endpoint") != authorization_url
        or metadata.get("token_endpoint") != token_url
    ):
        return "unknown"
    methods = metadata.get("code_challenge_methods_supported", [])
    if not isinstance(methods, list) or any(
        not isinstance(method, str) for method in methods
    ):
        return "unknown"
    return "supported" if "S256" in methods else "unsupported"


def detect_pkce_support(authorization_url: str, token_url: str) -> PKCESupport:
    """Trust only metadata bound to the configured endpoints and candidate issuer.

    Endpoint URLs do not identify an issuer uniquely. Probe a bounded set of
    parent paths, then the origin; absent or mismatched metadata stays unknown.
    The network budget excludes time spent in the system DNS resolver.
    """
    deadline = time.monotonic() + _DISCOVERY_BUDGET_SECONDS
    try:
        validate_oauth_endpoint_url(authorization_url, resolve_dns=False)
        validate_oauth_endpoint_url(token_url, resolve_dns=False)
        parsed = urlsplit(authorization_url)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        path = parsed.path.rstrip("/")
        issuers: list[str] = []
        for _ in range(_MAX_ISSUER_PARENTS):
            path = path.rpartition("/")[0]
            if not path:
                break
            issuers.append(origin + path)
        issuers.append(origin)
    except (ValueError, SSRFException):
        return "unknown"

    policy = outbound_ssrf_params(get_security_settings().ssrf_protection_level)
    for issuer in issuers:
        candidates = build_oauth_authorization_server_metadata_discovery_urls(
            issuer, issuer
        )
        for candidate in candidates:
            if time.monotonic() >= deadline:
                return "unknown"
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "unknown"
                with ssrf_safe_get(
                    candidate,
                    headers={"Accept": "application/json"},
                    timeout=min(_REQUEST_TIMEOUT_SECONDS, remaining),
                    follow_redirects=False,
                    https_only=True,
                    trust_env=False,
                    allow_private_network=policy.allow_private_network,
                    block_loopback_and_link_local=policy.block_loopback_and_link_local,
                    block_link_local_only=policy.block_link_local_only,
                    stream=True,
                ) as response:
                    if response.status_code != 200:
                        continue
                    body = bytearray()
                    # One-byte reads let the deadline stop a trickling response.
                    for chunk in response.iter_content(chunk_size=1):
                        if time.monotonic() >= deadline:
                            return "unknown"
                        body.extend(chunk)
                        if len(body) > _MAX_METADATA_BYTES:
                            break
                    else:
                        result = _metadata_support(
                            bytes(body), issuer, authorization_url, token_url
                        )
                        if result != "unknown":
                            return result
            except (
                requests.RequestException,
                ValueError,
                SSRFException,
                RecursionError,
            ):
                continue
    return "unknown"
