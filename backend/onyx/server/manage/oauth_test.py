"""Admin "OAuth Test" API.

Exposes the claims snapshot captured at OAuth/OIDC login time (see
onyx/auth/oauth_claims_capture.py) so admins can inspect which user fields
the IdP actually releases about a user, and debug the directory-profile
enrichment. To refresh the snapshot the admin simply goes through the login
flow again.
"""

from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel

from onyx.auth.oauth_claims_capture import get_captured_oauth_claims
from onyx.auth.oauth_claims_capture import get_idp_profile_fields
from onyx.auth.users import current_curator_or_admin_user
from onyx.configs.app_configs import IDP_PROFILE_ENRICHMENT_ENABLED
from onyx.db.models import User

router = APIRouter(prefix="/admin/oauth-test")


class OAuthClaimsSnapshot(BaseModel):
    found: bool
    email: str
    enrichment_enabled: bool = IDP_PROFILE_ENRICHMENT_ENABLED
    captured_at: str | None = None
    oauth_name: str | None = None
    id_token_claims: dict[str, Any] | None = None
    userinfo: dict[str, Any] | None = None
    # Directory profile fetched from the provider API (e.g. Microsoft Graph
    # for Entra ID); None when the provider has no directory API integration.
    directory_profile: dict[str, Any] | None = None
    directory_source: str | None = None
    # The resolved profile actually used for prompt enrichment / placeholders
    # (claim-mapped across all captured sources), as {label: value}.
    resolved_profile: dict[str, str] | None = None
    token_meta: dict[str, Any] | None = None


@router.get("/claims")
async def get_oauth_login_claims(
    email: str | None = None,
    user: User = Depends(current_curator_or_admin_user),
) -> OAuthClaimsSnapshot:
    """Last captured IdP claims for the given user (defaults to the caller).

    Claims are captured on every OAuth/OIDC login (when
    IDP_PROFILE_ENRICHMENT_ENABLED); if nothing is found the user has not
    logged in through the IdP since capture was enabled.
    """
    target_email = email or user.email
    snapshot = await get_captured_oauth_claims(target_email)
    if snapshot is None:
        return OAuthClaimsSnapshot(found=False, email=target_email)

    return OAuthClaimsSnapshot(
        found=True,
        email=snapshot.get("email", target_email),
        captured_at=snapshot.get("captured_at"),
        oauth_name=snapshot.get("oauth_name"),
        id_token_claims=snapshot.get("id_token_claims") or {},
        userinfo=snapshot.get("userinfo") or {},
        directory_profile=snapshot.get("directory_profile"),
        directory_source=snapshot.get("directory_source"),
        resolved_profile=get_idp_profile_fields(target_email),
        token_meta=snapshot.get("token_meta") or {},
    )
