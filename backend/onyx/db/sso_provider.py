import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider

# The name becomes the login URL path segment and the oauth_name stored on
# linked login accounts, so it must be a stable, URL-safe slug.
_PROVIDER_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def validate_sso_provider_name(name: str) -> None:
    if not _PROVIDER_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Provider name must be a lowercase slug (a-z, 0-9, inner hyphens)"
        )


def _normalize_domains(domains: list[str]) -> list[str]:
    return sorted({domain.strip().lower() for domain in domains if domain.strip()})


def fetch_sso_providers(
    db_session: Session, enabled_only: bool = False
) -> list[SSOProvider]:
    stmt = select(SSOProvider).order_by(SSOProvider.id)
    if enabled_only:
        stmt = stmt.where(SSOProvider.enabled.is_(True))
    return list(db_session.scalars(stmt).all())


def fetch_sso_provider_by_name(
    db_session: Session, name: str, enabled_only: bool = False
) -> SSOProvider | None:
    """The login route must pass enabled_only=True so a disabled provider can
    never resolve into an authorization flow. The admin API leaves it False to
    read a disabled row for re-enabling."""
    stmt = select(SSOProvider).where(SSOProvider.name == name)
    if enabled_only:
        stmt = stmt.where(SSOProvider.enabled.is_(True))
    return db_session.scalars(stmt).first()


def create_sso_provider(
    db_session: Session,
    name: str,
    display_name: str,
    provider_type: SSOProviderType,
    client_id: str,
    client_secret: str,
    allowed_email_domains: list[str],
    openid_config_url: str | None = None,
) -> SSOProvider:
    validate_sso_provider_name(name)
    if provider_type == SSOProviderType.OIDC and not openid_config_url:
        raise ValueError("OIDC providers require an openid_config_url")
    if provider_type != SSOProviderType.OIDC and openid_config_url:
        raise ValueError("openid_config_url only applies to OIDC providers")

    provider = SSOProvider(
        name=name,
        display_name=display_name,
        provider_type=provider_type,
        client_id=client_id,
        client_secret=client_secret,
        openid_config_url=openid_config_url,
        allowed_email_domains=_normalize_domains(allowed_email_domains),
    )
    db_session.add(provider)
    db_session.commit()
    return provider


def update_sso_provider(
    db_session: Session,
    provider_id: int,
    display_name: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    allowed_email_domains: list[str] | None = None,
    openid_config_url: str | None = None,
) -> SSOProvider:
    """Partial update. The provider name is immutable because linked login
    accounts and the login URL reference it. A None field is left unchanged,
    so a secret is only rewritten when a new one is supplied."""
    provider = db_session.get(SSOProvider, provider_id)
    if provider is None:
        raise ValueError(f"SSO provider {provider_id} does not exist")

    if display_name is not None:
        provider.display_name = display_name
    if client_id is not None:
        provider.client_id = client_id
    if client_secret is not None:
        provider.client_secret = client_secret  # ty: ignore[invalid-assignment]
    if allowed_email_domains is not None:
        provider.allowed_email_domains = _normalize_domains(allowed_email_domains)
    if openid_config_url is not None:
        if provider.provider_type != SSOProviderType.OIDC:
            raise ValueError("openid_config_url only applies to OIDC providers")
        provider.openid_config_url = openid_config_url

    db_session.commit()
    return provider


def set_sso_provider_enabled(
    db_session: Session, provider_id: int, enabled: bool
) -> SSOProvider:
    """Providers are disabled, never hard-deleted, so linked login accounts
    survive a re-enable."""
    provider = db_session.get(SSOProvider, provider_id)
    if provider is None:
        raise ValueError(f"SSO provider {provider_id} does not exist")
    provider.enabled = enabled
    db_session.commit()
    return provider
