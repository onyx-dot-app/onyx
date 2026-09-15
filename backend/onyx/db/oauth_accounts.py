"""Which stored IdP link may act for a user outside the login flow."""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from onyx.configs.app_configs import OAUTH_ENABLED, OPENID_CONFIG_URL
from onyx.db.models import OAuthAccount, User
from onyx.db.sso_provider import fetch_sso_providers

# oauth_name values written by the env-credential logins. Provider rows write
# their own name.
_ENV_GOOGLE_PROVIDER: str = "google"
_ENV_OIDC_PROVIDER: str = "openid"


def configured_provider_names(db_session: Session) -> set[str]:
    """oauth_name values whose tokens this deployment can still refresh.

    Same rule as the refresher: any provider row, enabled or not, since a
    disabled provider still serves its open sessions, plus the env logins when
    env credentials exist. A rowless link on any other name is dead.
    """
    names: set[str] = {provider.name for provider in fetch_sso_providers(db_session)}
    if OAUTH_ENABLED:
        names.add(_ENV_GOOGLE_PROVIDER)
        if OPENID_CONFIG_URL:
            names.add(_ENV_OIDC_PROVIDER)
    return names


def select_live_oauth_token(
    links: Sequence[OAuthAccount], configured_names: set[str]
) -> str | None:
    """Access token of the newest link on a provider still configured here.

    A user can hold several links: one per re-issued subject after an IdP
    client change, and one per provider from legacy email association. A link
    nobody can refresh never leaves, so it is skipped even if it is the only
    one. The relationship has no order, so the latest expiry picks among the
    rest. A link with no expiry ranks lowest. Ties keep row order.
    """
    candidates: list[OAuthAccount] = [
        link for link in links if link.oauth_name in configured_names
    ]
    if not candidates:
        return None
    live: OAuthAccount = max(candidates, key=lambda link: link.expires_at or 0)
    return live.access_token


def get_live_oauth_token(user: User, db_session: Session) -> str | None:
    """Token a pass-through tool may forward for `user`, or None.

    Needs fully loaded links: a `load_only` collection lazy-loads each row.
    """
    return select_live_oauth_token(
        user.oauth_accounts, configured_provider_names(db_session)
    )
