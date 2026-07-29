"""Capture the identity attributes an IdP sends at login and derive a
directory profile from them, independent of login protocol.

Both protocols feed this module: OAuth/OIDC logins contribute id_token and
userinfo claims (plus the Microsoft Graph profile for Entra ID), and SAML
logins contribute assertion attributes. The login flow itself only consumes
``sub`` and ``email``, and everything else is discarded. When
``IDP_PROFILE_ENRICHMENT_ENABLED`` is set, this module snapshots the full
attribute set into Redis at login time and derives a "directory profile"
(country, department, job title, ...) from it, which is then used to (a)
enrich the chat system prompt and (b) resolve author-controlled
``{{user.<key>}}`` placeholders in agent prompts.

Profile fields are resolved through a provider-agnostic claim map: each field
has an ordered list of claim aliases checked against the captured sources in
precedence order — the provider directory API (Microsoft Graph for Entra ID),
the OIDC userinfo response, the raw id_token claims, then SAML assertion
attributes. Okta/Keycloak/Google deployments therefore work out of the box for
whatever claims they release, and the map can be extended per-deployment via
``IDP_PROFILE_CLAIM_MAP``.

Capture is strictly best-effort: any failure is logged and swallowed so the
login flow can never break because of it. Oversized snapshots are dropped, and
a fresh capture retains a previous snapshot's sources when a fetch comes back
empty. No tokens are persisted — only claims and token metadata (key names,
scope, expiry).
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Awaitable, NamedTuple, TypeGuard, cast

import httpx
import jwt
from fastapi_users import exceptions as fastapi_users_exceptions

from onyx.configs.app_configs import (
    IDP_PROFILE_CLAIM_MAP,
    IDP_PROFILE_ENRICHMENT_ENABLED,
)
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Redis HASH per (tenant, email): field = provider name, value = snapshot JSON.
# Keeping one field per provider means a login through a second IdP never
# clobbers the first provider's directory data.
_IDP_CLAIMS_KEY_PREFIX = "idp_login_claims"
# Long enough that an admin can log in and inspect at leisure, short enough
# that data for users who stop logging in doesn't linger forever.
_IDP_CLAIMS_TTL_SECONDS = 60 * 60 * 24 * 30

# Hard ceiling on the whole best-effort capture. It runs inline in the login
# flow, so a slow userinfo/Graph endpoint or an unreachable Redis must never
# hold the login open indefinitely. Capture is refreshed on every login, so
# dropping one is harmless.
_IDP_CLAIMS_CAPTURE_TIMEOUT_SECONDS = 10

# Entra ID hosts its OIDC userinfo endpoint on Microsoft Graph. When we see
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


def _idp_claims_key(tenant_id: str, email: str) -> str:
    return f"{_IDP_CLAIMS_KEY_PREFIX}:{tenant_id}:{email.lower()}"


async def _resolve_capture_tenant_id(email: str) -> str | None:
    """Tenant to key the snapshot under. The login callbacks that run capture are
    unauthenticated, so the tenant contextvar still holds the default schema
    there. On multi-tenant the user's tenant must come from the email mapping.
    Returns None when the mapping cannot resolve the email (brand-new user, or a
    lookup failure surfaced as UserNotExists), in which case capture is skipped
    and the next login picks it up. The mapping is a sync DB call, so it runs in
    a thread to stay preemptible under the capture timeout.
    """
    if not MULTI_TENANT:
        return get_current_tenant_id()
    try:
        tenant_id = await asyncio.to_thread(
            fetch_ee_implementation_or_noop(
                "onyx.server.tenants.user_mapping", "get_tenant_id_for_email", None
            ),
            email,
        )
    except fastapi_users_exceptions.UserNotExists:
        return None
    return tenant_id if isinstance(tenant_id, str) else None


# The snapshot keys that hold claim sources, in resolution precedence order.
_SOURCE_KEYS = ("directory_profile", "userinfo", "id_token_claims", "saml_attributes")

# A pathological IdP (multi-thousand-entry groups claims) must not grow the
# stored snapshot without bound.
_MAX_SNAPSHOT_BYTES = 256 * 1024


def _has_source_data(value: Any) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict) and bool(value) and "error" not in value


def _retain_richer_sources(
    old_snapshot: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of ``snapshot`` with sources carried forward from the
    previous same-provider snapshot where the fresh capture came back without
    them (or with only an error marker), so a transient userinfo or Graph
    outage at re-login cannot degrade a profile that was already captured.
    The fresh snapshot itself is left untouched so the caller can fall back to
    it when the merged form does not fit the size cap."""
    merged = dict(snapshot)
    for source_key in _SOURCE_KEYS:
        if _has_source_data(old_snapshot.get(source_key)) and not _has_source_data(
            snapshot.get(source_key)
        ):
            merged[source_key] = old_snapshot[source_key]
            logger.warning(
                "Claims capture for %s: %s missing from fresh capture, "
                "retaining previous data",
                snapshot.get("email", "<unknown>"),
                source_key,
            )
    return merged


async def _store_claims_snapshot(email: str, snapshot: dict[str, Any]) -> None:
    tenant_id = await _resolve_capture_tenant_id(email)
    if tenant_id is None:
        logger.debug(
            "Skipping claims capture for %s: tenant not yet resolved "
            "(new user or lookup failed)",
            email,
        )
        return
    provider = str(snapshot.get("oauth_name") or "unknown")
    key = _idp_claims_key(tenant_id, email)
    redis = await get_async_redis_connection()

    old_raw = await cast(Awaitable[Any], redis.hget(key, provider))
    old_snapshots = _sorted_snapshots([old_raw]) if old_raw else []
    to_store = (
        _retain_richer_sources(old_snapshots[0], snapshot)
        if old_snapshots
        else snapshot
    )

    payload = json.dumps(to_store, default=str)
    if len(payload.encode("utf-8")) > _MAX_SNAPSHOT_BYTES:
        # Retained sources must not block fresh data from landing: fall back
        # to the fresh capture alone before giving up.
        payload = json.dumps(snapshot, default=str)
        if len(payload.encode("utf-8")) > _MAX_SNAPSHOT_BYTES:
            logger.warning(
                "Claims capture for %s: snapshot exceeds %d bytes, not storing",
                email,
                _MAX_SNAPSHOT_BYTES,
            )
            return
        logger.warning(
            "Claims capture for %s: merged snapshot exceeds %d bytes, "
            "storing the fresh capture without retained sources",
            email,
            _MAX_SNAPSHOT_BYTES,
        )
    # TTL is per key, so any login through any provider keeps the whole hash
    # alive. Fields for abandoned providers persist until the hash expires.
    pipe = redis.pipeline()
    pipe.hset(key, provider, payload)
    pipe.expire(key, _IDP_CLAIMS_TTL_SECONDS)
    await pipe.execute()


def _snapshot_captured_at(snapshot: dict[str, Any]) -> datetime:
    """Parsed capture timestamp for ordering. Offset-aware parsing keeps the
    ordering correct even if a snapshot were ever written with a non-UTC
    offset. Unparseable or missing timestamps sort last (oldest)."""
    try:
        captured_at = datetime.fromisoformat(str(snapshot.get("captured_at")))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    return captured_at


def _sorted_snapshots(raw_values: list[Any]) -> list[dict[str, Any]]:
    """Parse hash values into snapshots, most recent login first. Corrupt or
    non-dict entries are dropped so one bad provider field cannot poison the
    rest."""
    snapshots: list[dict[str, Any]] = []
    for raw in raw_values:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            snapshots.append(parsed)
    snapshots.sort(key=_snapshot_captured_at, reverse=True)
    return snapshots


def _decode_id_token_claims(raw_id_token: str) -> dict[str, Any]:
    # Display-only decode: the token was just received directly from the
    # IdP's token endpoint over TLS, so skipping signature verification is
    # safe here. We never make authorization decisions from this data.
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
            logger.warning(
                "OAuth claims capture: Graph /me returned %s", response.status_code
            )
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
    _IDP_CLAIMS_CAPTURE_TIMEOUT_SECONDS.
    """
    if not IDP_PROFILE_ENRICHMENT_ENABLED:
        return
    try:
        await asyncio.wait_for(
            _capture_oauth_login_claims(oauth_client, email, token),
            timeout=_IDP_CLAIMS_CAPTURE_TIMEOUT_SECONDS,
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

        # Entra ID: also pull the Graph directory profile. Country and
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
                # Which fields the token response contained, values omitted.
                "keys": sorted(token.keys()),
                "scope": token.get("scope"),
                "token_type": token.get("token_type"),
                "expires_at": token.get("expires_at"),
                "has_refresh_token": bool(token.get("refresh_token")),
                "has_id_token": bool(raw_id_token),
            },
        }

        await _store_claims_snapshot(email, snapshot)
    except Exception:
        logger.warning(
            "OAuth claims capture failed for %s (login unaffected)",
            email,
            exc_info=True,
        )


async def capture_saml_login_claims(
    email: str,
    saml_attributes: dict[str, list[str]],
    provider_name: str,
) -> None:
    """Snapshot the directory attributes a SAML IdP asserted at login.

    SAML carries the same directory data (department, title, ...) as OIDC, just
    as assertion attributes instead of token claims. Resolution reuses the same
    claim map, so deployments map their attribute names via IDP_PROFILE_CLAIM_MAP.
    No-op unless IDP_PROFILE_ENRICHMENT_ENABLED. Never raises, and never holds the
    login open past _IDP_CLAIMS_CAPTURE_TIMEOUT_SECONDS.
    """
    if not IDP_PROFILE_ENRICHMENT_ENABLED:
        return
    try:
        await asyncio.wait_for(
            _capture_saml_login_claims(email, saml_attributes, provider_name),
            timeout=_IDP_CLAIMS_CAPTURE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("SAML claims capture timed out for %s (login unaffected)", email)


async def _capture_saml_login_claims(
    email: str,
    saml_attributes: dict[str, list[str]],
    provider_name: str,
) -> None:
    try:
        # OneLogin returns each attribute as a list. Keep the first string value
        # so the claim-map resolver can treat it like any other source.
        flattened = {
            name: values[0]
            for name, values in saml_attributes.items()
            if isinstance(values, list) and values and isinstance(values[0], str)
        }
        snapshot = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "oauth_name": provider_name,
            "email": email,
            "id_token_claims": {},
            "userinfo": {},
            "directory_profile": None,
            "directory_source": None,
            "saml_attributes": flattened,
            "token_meta": {"source": "saml"},
        }
        await _store_claims_snapshot(email, snapshot)
    except Exception:
        logger.warning(
            "SAML claims capture failed for %s (login unaffected)",
            email,
            exc_info=True,
        )


# Profile field definitions: (placeholder_key, human-readable label, ordered
# claim aliases). Aliases are checked against each captured source in
# precedence order (directory API -> userinfo -> id_token claims). The first
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


def _snapshot_sources(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Claim sources of one snapshot in _SOURCE_KEYS precedence order
    (directory API, userinfo, id_token, then SAML assertion attributes). SAML
    is lowest by convention. A snapshot is written whole per login, so today a
    SAML snapshot never carries the OIDC sources and ordering only matters if
    a future path mixes them."""
    candidates = [snapshot.get(key) for key in _SOURCE_KEYS]
    return [source for source in candidates if _has_source_data(source)]


def _load_profile_sources(email: str) -> list[dict[str, Any]]:
    """Read all captured provider snapshots and return the claim sources to
    resolve profile fields against, in precedence order: every source of the
    most recent login first, then older providers' sources as gap fillers.

    Must use the RAW client — the capture writes via the raw async connection,
    and the tenant-prefixing TenantRedisClient would look up a different key
    (the tenant id is already part of ``_idp_claims_key``). Best-effort: the
    chat pipeline that consumes this must treat the profile as optional."""
    from onyx.redis.redis_pool import get_raw_redis_client

    redis = get_raw_redis_client()
    raw_map = redis.hgetall(_idp_claims_key(get_current_tenant_id(), email))
    if not isinstance(raw_map, dict) or not raw_map:
        return []

    sources: list[dict[str, Any]] = []
    for snapshot in _sorted_snapshots(list(raw_map.values())):
        sources.extend(_snapshot_sources(snapshot))
    return sources


# Directory values are interpolated into LLM prompts unescaped. A field is a
# short label (department, title, city), so anything longer is
# misconfiguration or abuse.
_MAX_PROFILE_VALUE_CHARS = 256


def _sanitize_profile_value(value: str) -> str:
    """Collapse non-printable characters (controls, zero-width and format
    chars, exotic spaces) to spaces, squeeze whitespace runs, and cap length.
    Directory values are interpolated into the system prompt, so a value must
    not be able to inject new prompt lines or blow up the token budget."""
    cleaned = "".join(ch if ch.isprintable() else " " for ch in value)
    cleaned = " ".join(cleaned.split())
    return cleaned[:_MAX_PROFILE_VALUE_CHARS]


def _resolve_profile(email: str) -> dict[str, tuple[str, str]]:
    """Resolve the directory profile for ``email`` from the captured claim
    sources. Returns ``{placeholder_key: (label, value)}`` in field order,
    values sanitized for prompt interpolation."""
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
            sanitized = _sanitize_profile_value(value)
            if sanitized:
                resolved[placeholder_key] = (label, sanitized)
    return resolved


class IdpProfileViews(NamedTuple):
    # {label: value} for the "Organization Profile" prompt block.
    fields: dict[str, str]
    # {placeholder_key: value} for `{{user.<key>}}` substitution.
    placeholders: dict[str, str]


def get_idp_profile(email: str) -> IdpProfileViews:
    """Both derived views of the directory profile from one Redis read.
    Resolving once serves callers that need both views without a second
    round-trip. Best-effort: returns empty views when the feature is disabled,
    nothing is captured, or Redis is unavailable. Callers must treat the
    profile as optional."""
    if not IDP_PROFILE_ENRICHMENT_ENABLED:
        return IdpProfileViews({}, {})
    try:
        profile = _resolve_profile(email)
        return IdpProfileViews(
            fields={label: value for label, value in profile.values()},
            placeholders={key: value for key, (_, value) in profile.items()},
        )
    except Exception:
        logger.warning(
            "Failed to load IdP profile for %s (prompt continues without it)",
            email,
            exc_info=True,
        )
        return IdpProfileViews({}, {})


def get_idp_profile_fields(email: str) -> dict[str, str]:
    """Directory profile of the user (country, department, ...) from the
    captured IdP login snapshots, as ordered ``{label: value}`` pairs for the auto
    "Organization Profile" prompt block. Best-effort like ``get_idp_profile``."""
    return get_idp_profile(email).fields


def get_idp_profile_placeholder_values(email: str) -> dict[str, str]:
    """Directory profile of the user keyed by ``{{user.<key>}}`` placeholder
    key (snake_case, e.g. ``department``/``job_title``/``city``) for
    author-controlled placeholder substitution in agent prompts. Only
    populated fields are included. Best-effort like ``get_idp_profile``."""
    return get_idp_profile(email).placeholders


async def get_captured_oauth_claims(email: str) -> dict[str, Any] | None:
    """Return the most recent captured claims snapshot for ``email``, or None."""
    redis = await get_async_redis_connection()
    # redis-py types hash commands as a sync-or-async union. This is the async client.
    raw_map = await cast(
        Awaitable[dict[Any, Any]],
        redis.hgetall(_idp_claims_key(get_current_tenant_id(), email)),
    )
    if not raw_map:
        return None
    snapshots = _sorted_snapshots(list(raw_map.values()))
    return snapshots[0] if snapshots else None
