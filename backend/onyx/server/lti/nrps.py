"""LTI Advantage Names and Role Provisioning Service (NRPS) client.

NRPS is the LTI 1.3 standards endpoint for course rosters. We obtain an access
token from the platform via the OAuth2 client_credentials flow using an RFC 7521
client-assertion JWT (signed with the same key served at /auth/lti/jwks), then
GET the per-course membership endpoint that the launch JWT hands us.

See https://www.imsglobal.org/spec/lti-nrps/v2p0.
"""

import time
import uuid

import httpx
import jwt as pyjwt
from pydantic import BaseModel

from onyx.configs.lti_configs import LTI_AUTH_TOKEN_URL
from onyx.configs.lti_configs import LTI_CLIENT_ID
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_shared_redis_client
from onyx.server.lti.jwks import get_private_key
from onyx.server.lti.jwks import get_signing_kid
from onyx.utils.logger import setup_logger


logger = setup_logger()

NRPS_MEMBERSHIP_SCOPE = (
    "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly"
)
_NRPS_MEMBERSHIP_ACCEPT = "application/vnd.ims.lti-nrps.v2.membershipcontainer+json"
_CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

# Redis cache for the platform access token (keyed by scope; the token is
# platform-wide, not per-course). Refreshed ~30s before the platform's expiry.
_TOKEN_REDIS_PREFIX = "lti_nrps_token:"
_TOKEN_EXPIRY_SAFETY_SECONDS = 30
_CLIENT_ASSERTION_TTL_SECONDS = 300
# Defensive bound so a misbehaving / hostile platform can't page us forever.
_MAX_NRPS_PAGES = 100


class NrpsMember(BaseModel):
    email: str | None = None
    name: str | None = None
    roles: list[str] = []
    # Active / Inactive / Deleted per the NRPS spec; defaults to Active when omitted.
    status: str = "Active"

    def is_active(self) -> bool:
        return self.status.strip().casefold() == "active"


class NrpsRoster(BaseModel):
    members: list[NrpsMember] = []
    # Canvas course title from the membership container's `context` object, if present.
    context_title: str | None = None

    def active_member_emails(self) -> set[str]:
        return {
            member.email
            for member in self.members
            if member.email and member.is_active()
        }


def _token_cache_key(scope: str) -> str:
    return f"{_TOKEN_REDIS_PREFIX}{scope}"


def _build_client_assertion() -> str:
    if not LTI_CLIENT_ID or not LTI_AUTH_TOKEN_URL:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "LTI client_id / token endpoint not configured for NRPS",
        )

    now = int(time.time())
    payload = {
        "iss": LTI_CLIENT_ID,
        "sub": LTI_CLIENT_ID,
        "aud": LTI_AUTH_TOKEN_URL,
        "iat": now,
        "exp": now + _CLIENT_ASSERTION_TTL_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return pyjwt.encode(
        payload,
        get_private_key(),
        algorithm="RS256",
        headers={"kid": get_signing_kid()},
    )


def mint_lti_service_token(scope: str = NRPS_MEMBERSHIP_SCOPE) -> str:
    """Return a platform access token for the given scope, cached in Redis.

    Uses the OAuth2 client_credentials grant with a signed client assertion.
    """
    redis_client = get_shared_redis_client()
    cache_key = _token_cache_key(scope)

    cached = redis_client.get(cache_key)
    if cached:
        return cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)

    if not LTI_AUTH_TOKEN_URL:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "LTI_AUTH_TOKEN_URL is not configured; cannot mint NRPS token",
        )

    form = {
        "grant_type": "client_credentials",
        "client_assertion_type": _CLIENT_ASSERTION_TYPE,
        "client_assertion": _build_client_assertion(),
        "scope": scope,
    }

    try:
        with httpx.Client() as client:
            resp = client.post(LTI_AUTH_TOKEN_URL, data=form)
            resp.raise_for_status()
            token_data = resp.json()
    except httpx.HTTPStatusError as e:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"LTI platform rejected NRPS token request: {e.response.text}",
            status_code_override=e.response.status_code,
        ) from e
    except (httpx.RequestError, ValueError) as e:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"Failed to obtain LTI NRPS access token: {e}",
        ) from e

    access_token = (
        token_data.get("access_token") if isinstance(token_data, dict) else None
    )
    if not access_token:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "LTI platform token response did not contain an access_token",
        )

    expires_in = int(token_data.get("expires_in", 3600))
    cache_ttl = max(expires_in - _TOKEN_EXPIRY_SAFETY_SECONDS, 1)
    redis_client.set(cache_key, str(access_token), ex=cache_ttl)
    return str(access_token)


def _parse_members(payload: object) -> list[NrpsMember]:
    if not isinstance(payload, dict):
        return []
    raw_members = payload.get("members")
    if not isinstance(raw_members, list):
        return []

    members: list[NrpsMember] = []
    for raw_member in raw_members:
        if not isinstance(raw_member, dict):
            continue
        raw_roles = raw_member.get("roles")
        roles = [str(role) for role in raw_roles] if isinstance(raw_roles, list) else []
        members.append(
            NrpsMember(
                email=(
                    str(raw_member["email"]).strip().lower()
                    if raw_member.get("email")
                    else None
                ),
                name=str(raw_member["name"]) if raw_member.get("name") else None,
                roles=roles,
                status=str(raw_member.get("status") or "Active"),
            )
        )
    return members


def _parse_context_title(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    context = payload.get("context")
    if not isinstance(context, dict):
        return None
    title = context.get("title")
    return str(title) if title else None


def fetch_nrps_roster(nrps_url: str) -> NrpsRoster:
    """Fetch the full (paginated) NRPS roster for a course.

    Follows the RFC 5988 `Link: <...>; rel="next"` header for pagination. Raises
    OnyxError on platform failure (e.g. 403 when the Developer Key was not
    granted the NRPS scope).
    """
    token = mint_lti_service_token(NRPS_MEMBERSHIP_SCOPE)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": _NRPS_MEMBERSHIP_ACCEPT,
    }

    members: list[NrpsMember] = []
    context_title: str | None = None
    next_url: str | None = nrps_url
    pages_fetched = 0

    try:
        with httpx.Client() as client:
            while next_url and pages_fetched < _MAX_NRPS_PAGES:
                resp = client.get(next_url, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
                members.extend(_parse_members(payload))
                context_title = context_title or _parse_context_title(payload)
                pages_fetched += 1
                next_url = resp.links.get("next", {}).get("url")
    except httpx.HTTPStatusError as e:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"NRPS roster request failed (is the NRPS scope granted on the "
            f"Developer Key?): {e.response.text}",
            status_code_override=e.response.status_code,
        ) from e
    except (httpx.RequestError, ValueError) as e:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"Failed to fetch NRPS roster: {e}",
        ) from e

    if next_url and pages_fetched >= _MAX_NRPS_PAGES:
        logger.warning(
            "NRPS roster for %s exceeded %d pages; truncating roster",
            nrps_url,
            _MAX_NRPS_PAGES,
        )

    return NrpsRoster(members=members, context_title=context_title)
