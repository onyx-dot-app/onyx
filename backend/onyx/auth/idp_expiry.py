"""Effective IdP session-expiry tracking for a login account.

The global security setting is the default. An OAuth2 SSO provider row can
override it for the accounts that sign in through that provider."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from onyx.db.models import SSOProvider, User
from onyx.db.sso_provider import (
    fetch_sso_providers_by_names,
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


def _any_provider_tracks(providers: list[SSOProvider], names: list[str]) -> bool:
    """Whether any of `names` tracks. A name with no row follows the global setting."""
    configs = {provider.name: sso_provider_config(provider) for provider in providers}
    return any(tracks_external_idp_expiry(configs.get(name)) for name in names)


async def account_tracks_external_idp_expiry(
    db_session: AsyncSession, oauth_name: str
) -> bool:
    """The switch for one login account, by the provider name it links to."""
    providers = await fetch_sso_providers_by_names_async(db_session, [oauth_name])
    return _any_provider_tracks(providers, [oauth_name])


def _linked_provider_names(user: User) -> list[str]:
    return [account.oauth_name for account in user.oauth_accounts]


def user_tracks_external_idp_expiry(db_session: Session, user: User) -> bool:
    """A user follows the IdP expiry when any linked provider does. Users with
    no linked account (password, SAML, JWT) follow the global setting."""
    names = _linked_provider_names(user)
    if not names:
        return get_security_settings().track_external_idp_expiry
    return _any_provider_tracks(fetch_sso_providers_by_names(db_session, names), names)


async def user_tracks_external_idp_expiry_async(
    db_session: AsyncSession, user: User
) -> bool:
    """Async twin of user_tracks_external_idp_expiry."""
    names = _linked_provider_names(user)
    if not names:
        return get_security_settings().track_external_idp_expiry
    providers = await fetch_sso_providers_by_names_async(db_session, names)
    return _any_provider_tracks(providers, names)
