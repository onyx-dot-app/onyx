"""Effective IdP session-expiry tracking for a login account.

The global security setting is the default. An OAuth2 SSO provider row can
override it for the accounts that sign in through that provider."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from onyx.db.models import User
from onyx.db.sso_provider import (
    fetch_sso_providers_by_names_async,
    sso_provider_config,
)
from onyx.server.security.store import get_security_settings

# Key in the provider config blob, see `_OAuth2ProviderConfig`.
TRACK_EXTERNAL_IDP_EXPIRY_CONFIG_KEY = "track_external_idp_expiry"


def tracks_external_idp_expiry(config: dict[str, Any] | None) -> bool:
    """The provider config's own switch when set, else the global setting."""
    override = (config or {}).get(TRACK_EXTERNAL_IDP_EXPIRY_CONFIG_KEY)
    if isinstance(override, bool):
        return override
    return get_security_settings().track_external_idp_expiry


async def linked_idp_expiry_switches(
    db_session: AsyncSession, user: User
) -> dict[str, bool]:
    """The switch per linked login account, keyed by provider name. A name with
    no provider row (legacy env login) follows the global setting."""
    names = [account.oauth_name for account in user.oauth_accounts]
    if not names:
        return {}
    providers = await fetch_sso_providers_by_names_async(db_session, names)
    configs = {provider.name: sso_provider_config(provider) for provider in providers}
    return {name: tracks_external_idp_expiry(configs.get(name)) for name in names}


def session_follows_idp_expiry(switches: dict[str, bool]) -> bool:
    """On when any linked account's switch is on. Users with no linked account
    (password, SAML, JWT) follow the global setting."""
    if not switches:
        return get_security_settings().track_external_idp_expiry
    return any(switches.values())
