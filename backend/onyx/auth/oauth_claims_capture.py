"""Capture the OIDC/OAuth claims received at login and derive a directory
profile from them.

The IdP sends user information in the id_token and on the userinfo endpoint,
but the login flow only consumes ``sub`` and ``email`` — everything else is
discarded. When ``IDP_PROFILE_ENRICHMENT_ENABLED`` is set, this module
snapshots the full claim set into Redis at login time and derives a
"directory profile" (country, department, job title, ...) from it, which is
then used to (a) enrich the chat system prompt and (b) resolve
author-controlled ``{{user.<key>}}`` placeholders in agent prompts.

Profile fields are resolved through a provider-agnostic claim map: each field
has an ordered list of claim aliases checked against three sources in
precedence order — the provider directory API (Microsoft Graph for Entra ID),
the OIDC userinfo response, then the raw id_token claims. Okta/Keycloak/Google
deployments therefore work out of the box for whatever claims they release,
and the map can be extended per-deployment via ``IDP_PROFILE_CLAIM_MAP``.

Capture is strictly best-effort: any failure is logged and swallowed so the
login flow can never break because of it. No tokens are persisted — only
claims and token metadata (key names, scope, expiry).
"""

import asyncio
import json
from datetime import datetime
from datetime import timezone
from typing import Any

import httpx
import jwt

from onyx.configs.app_configs import IDP_PROFILE_CLAIM_MAP
from onyx.configs.app_configs import IDP_PROFILE_ENRICHMENT_ENABLED
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_OAUTH_CLAIMS_KEY_PREFIX = "oauth_login_claims"
# Long enough that an admin can log in and inspect at leisure; short enough
# that stale directory data doesn't linger forever.
_OAUTH_CLAIMS_TTL_SECONDS = 60 * 60 * 24 * 30

# Hard ceiling on the whole best-effort capture. It runs inline in the login
# flow, so a slow userinfo/Graph endpoint or an unreachable Redis must never
# hold the login open indefinitely. Capture is refreshed on every login, so
# dropping one is harmless.
_OAUTH_CLAIMS_CAPTURE_TIMEOUT_SECONDS = 10

# Entra ID hosts its OIDC userinfo endpoint on Microsoft Graph; when we see
# that host we can also query the Graph profile, which carries directory
# fields the id_token/userinfo never include (country, usageLocation, ...).
_MS_GRAPH_HOST = "graph.microsoft.com"
_MS_GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"
# usageLocation is the most reliably populated location field in corporate
# tenants (required for license assignment); `country` is the profile field.
_MS_GRAPH_SELECT_FIELDS = (
    "country,usageLocation,city,state,officeLocation,"
    "department,jobTitle,companyName,preferredLanguage"
)


def _oauth_claims_key(tenant_id: str, email: str) -> str:
    return f"{_OAUTH_CLAIMS_KEY_PREFIX}:{tenant_id}:{email.lower()}"


def _decode_id_token_claims(raw_id_token: str) -> dict[str, Any]:
    # Display-only decode: the token was just received directly from the
    # IdP's token endpoint over TLS, so skipping signature verification is
    # safe here — we never make authorization decisions from this data.
    return jwt.decode(
        raw_id_token,
        options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
    )


async def _fetch_userinfo(
    userinfo_endpoint: str, access_token: str
) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code >= 400:
            logger.warning(
                "OAuth claims capture: userinfo endpoint returned %s",
                response.status_code,
            )
            return None
        data = response.json()
        return data if isinstance(data, dict) else None


async def _fetch_ms_graph_profile(access_token: str) -> dict[str, Any]:
    """Fetch directory profile fields (incl. country/usageLocation) from
    Microsoft Graph. Returns an ``{"error": ...}`` dict on failure so the
    admin page can show WHY the data is missing (typically the token lacks
    the User.Read scope — add it via OIDC_SCOPE_OVERRIDE)."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            _MS_GRAPH_ME_URL,
            params={"$select": _MS_GRAPH_SELECT_FIELDS},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code >= 400:
            return {
                "error": (
                    f"Graph /me returned HTTP {response.status_code}. "
                    "The access token likely lacks the User.Read scope — "
                    "add it to OIDC_SCOPE_OVERRIDE and log in again."
                )
            }
        data = response.json()
        if not isinstance(data, dict):
            return {"error": "Graph /me returned a non-object response"}
        data.pop("@odata.context", None)
        return data


async def capture_oauth_login_claims(
    oauth_client: Any,
    email: str,
    token: dict[str, Any],
) -> None:
    """Snapshot the claims the IdP sent for this login into Redis.

    ``oauth_client`` is the httpx_oauth client used for the login (its
    ``openid_configuration`` — present on OpenID clients — supplies the
    userinfo endpoint). No-op unless IDP_PROFILE_ENRICHMENT_ENABLED.
    Never raises, and never holds the login open past
    _OAUTH_CLAIMS_CAPTURE_TIMEOUT_SECONDS.
    """
    if not IDP_PROFILE_ENRICHMENT_ENABLED:
        return
    try:
        await asyncio.wait_for(
            _capture_oauth_login_claims(oauth_client, email, token),
            timeout=_OAUTH_CLAIMS_CAPTURE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "OAuth claims capture timed out for %s (login unaffected)", email
        )


async def _capture_oauth_login_claims(
    oauth_client: Any,
    email: str,
    token: dict[str, Any],
) -> None:
    try:
        id_token_claims: dict[str, Any] = {}
        raw_id_token = token.get("id_token")
        if raw_id_token:
            try:
                id_token_claims = _decode_id_token_claims(raw_id_token)
            except Exception as e:
                logger.warning("OAuth claims capture: id_token decode failed: %s", e)

        userinfo: dict[str, Any] | None = None
        openid_configuration = getattr(oauth_client, "openid_configuration", None)
        userinfo_endpoint = (
            openid_configuration.get("userinfo_endpoint")
            if isinstance(openid_configuration, dict)
            else None
        )
        access_token = token.get("access_token")
        if userinfo_endpoint and access_token:
            try:
                userinfo = await _fetch_userinfo(userinfo_endpoint, access_token)
            except Exception as e:
                logger.warning("OAuth claims capture: userinfo fetch failed: %s", e)

        # Entra ID: also pull the Graph directory profile — country and
        # usageLocation live there, not in the id_token/userinfo (unless the
        # `ctry` optional claim is configured on the app registration). Other
        # providers release directory data directly in userinfo/id_token.
        directory_profile: dict[str, Any] | None = None
        directory_source: str | None = None
        if access_token and userinfo_endpoint and _MS_GRAPH_HOST in userinfo_endpoint:
            try:
                directory_profile = await _fetch_ms_graph_profile(access_token)
                directory_source = "ms_graph"
            except Exception as e:
                logger.warning("OAuth claims capture: Graph fetch failed: %s", e)

        snapshot = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "oauth_name": getattr(oauth_client, "name", "unknown"),
            "email": email,
            "id_token_claims": id_token_claims,
            "userinfo": userinfo or {},
            "directory_profile": directory_profile,
            "directory_source": directory_source,
            "token_meta": {
                # Which fields the token response contained — values omitted.
                "keys": sorted(token.keys()),
                "scope": token.get("scope"),
                "token_type": token.get("token_type"),
                "expires_at": token.get("expires_at"),
                "has_refresh_token": bool(token.get("refresh_token")),
                "has_id_token": bool(raw_id_token),
            },
        }

        redis = await get_async_redis_connection()
        await redis.set(
            _oauth_claims_key(get_current_tenant_id(), email),
            json.dumps(snapshot, default=str),
            ex=_OAUTH_CLAIMS_TTL_SECONDS,
        )
    except Exception:
        logger.warning(
            "OAuth claims capture failed for %s (login unaffected)",
            email,
            exc_info=True,
        )


# Profile field definitions: (placeholder_key, human-readable label, ordered
# claim aliases). Aliases are checked against each captured source in
# precedence order (directory API -> userinfo -> id_token claims); the first
# non-empty string wins. Aliases cover Microsoft Graph names plus the common
# OIDC/Okta/Keycloak claim names for the same concept, and can be extended
# per-deployment via IDP_PROFILE_CLAIM_MAP. This is the single source of truth
# for the derived views (prompt labels vs. placeholder keys) so they can never
# drift.
_PROFILE_FIELDS: list[tuple[str, str, tuple[str, ...]]] = [
    ("country", "Country", ("country", "ctry")),
    ("usage_location", "Usage location (ISO code)", ("usageLocation",)),
    ("city", "City", ("city", "l", "locality")),
    ("state", "State", ("state", "region")),
    ("office_location", "Office location", ("officeLocation", "office")),
    ("department", "Department", ("department", "division")),
    ("job_title", "Job title", ("jobTitle", "title")),
    ("company_name", "Company", ("companyName", "organization", "org")),
    ("preferred_language", "Preferred language", ("preferredLanguage", "locale")),
    ("timezone", "Timezone", ("zoneinfo", "timezone")),
]

# The `{{user.<key>}}` placeholder keys sourced from the IdP directory profile.
# Basic identity keys (email/name/role) are added by the substitution layer.
IDP_PLACEHOLDER_KEYS: frozenset[str] = frozenset(
    placeholder_key for placeholder_key, _, _ in _PROFILE_FIELDS
)


def _claim_aliases(placeholder_key: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    """Deployment-configured aliases (IDP_PROFILE_CLAIM_MAP) take precedence
    over the built-in ones; the built-ins remain as a fallback."""
    override = IDP_PROFILE_CLAIM_MAP.get(placeholder_key)
    if not override:
        return defaults
    return tuple(override) + tuple(a for a in defaults if a not in override)


def _load_profile_sources(email: str) -> list[dict[str, Any]]:
    """Read the captured login snapshot and return the claim sources to
    resolve profile fields against, in precedence order.

    Must use the RAW client — the capture writes via the raw async connection,
    and the tenant-prefixing TenantRedisClient would look up a different key
    (the tenant id is already part of ``_oauth_claims_key``). Best-effort: the
    chat pipeline that consumes this must treat the profile as optional."""
    from onyx.redis.redis_pool import get_raw_redis_client

    redis = get_raw_redis_client()
    raw = redis.get(_oauth_claims_key(get_current_tenant_id(), email))
    if not isinstance(raw, (str, bytes)):
        return []
    snapshot = json.loads(raw)

    sources: list[dict[str, Any]] = []
    directory_profile = snapshot.get("directory_profile")
    if isinstance(directory_profile, dict) and "error" not in directory_profile:
        sources.append(directory_profile)
    userinfo = snapshot.get("userinfo")
    if isinstance(userinfo, dict):
        sources.append(userinfo)
    id_token_claims = snapshot.get("id_token_claims")
    if isinstance(id_token_claims, dict):
        sources.append(id_token_claims)
    return sources


def _resolve_profile(email: str) -> dict[str, tuple[str, str]]:
    """Resolve the directory profile for ``email`` from the captured claim
    sources. Returns ``{placeholder_key: (label, value)}`` in field order."""
    sources = _load_profile_sources(email)
    if not sources:
        return {}
    resolved: dict[str, tuple[str, str]] = {}
    for placeholder_key, label, default_aliases in _PROFILE_FIELDS:
        aliases = _claim_aliases(placeholder_key, default_aliases)
        # Sources outer, aliases inner: a higher-priority source must win even
        # when it uses a lower-priority alias for the same concept (e.g. a
        # directory `division` beats a userinfo `department`).
        value = next(
            (
                source[alias]
                for source in sources
                for alias in aliases
                if isinstance(source.get(alias), str) and source[alias].strip()
            ),
            None,
        )
        if value is not None:
            resolved[placeholder_key] = (label, value.strip())
    return resolved


def get_idp_profile_fields(email: str) -> dict[str, str]:
    """Directory profile of the user (country, department, ...) from the last
    captured login snapshot, as ordered ``{label: value}`` pairs for the auto
    "Organization Profile" prompt block. Best-effort: returns ``{}`` when the
    feature is disabled, nothing is captured, or Redis is unavailable —
    callers must treat the profile as optional."""
    if not IDP_PROFILE_ENRICHMENT_ENABLED:
        return {}
    try:
        return {label: value for label, value in _resolve_profile(email).values()}
    except Exception:
        logger.warning(
            "Failed to load IdP profile for %s (prompt continues without it)",
            email,
            exc_info=True,
        )
        return {}


def get_idp_profile_placeholder_values(email: str) -> dict[str, str]:
    """Directory profile of the user keyed by ``{{user.<key>}}`` placeholder
    key (snake_case, e.g. ``department``/``job_title``/``city``) for
    author-controlled placeholder substitution in agent prompts. Only
    populated fields are included. Best-effort: returns ``{}`` when the
    feature is disabled, nothing is captured, or Redis is unavailable —
    callers must treat it as optional."""
    if not IDP_PROFILE_ENRICHMENT_ENABLED:
        return {}
    try:
        return {
            placeholder_key: value
            for placeholder_key, (_, value) in _resolve_profile(email).items()
        }
    except Exception:
        logger.warning(
            "Failed to load IdP placeholder values for %s "
            "(prompt continues without them)",
            email,
            exc_info=True,
        )
        return {}


async def get_captured_oauth_claims(email: str) -> dict[str, Any] | None:
    """Return the last captured claims snapshot for ``email``, or None."""
    redis = await get_async_redis_connection()
    raw = await redis.get(_oauth_claims_key(get_current_tenant_id(), email))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None
