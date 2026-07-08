import re
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider

# The name becomes the login URL path segment and the oauth_name stored on
# linked login accounts, so it must be a stable, URL-safe slug.
_PROVIDER_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


class _ProviderConfig(BaseModel):
    # Reject unknown keys so a config built for a different provider type (or a
    # typo) fails loudly on write instead of being stored and mis-read later.
    model_config = ConfigDict(extra="forbid")


class GoogleProviderConfig(_ProviderConfig):
    client_id: str
    client_secret: str


class OIDCProviderConfig(_ProviderConfig):
    client_id: str
    client_secret: str
    openid_config_url: str


class SAMLProviderConfig(_ProviderConfig):
    """SAML provider config: the IdP metadata a SAML login needs. No login flow
    consumes it yet, so a SAML row validates and stores but cannot drive a
    login."""

    idp_entity_id: str
    idp_sso_url: str
    idp_x509_cert: str
    sp_entity_id: str
    email_attribute: str | None = None


# provider_type selects the config shape. A new auth method adds a model here.
_CONFIG_MODEL_BY_TYPE: dict[SSOProviderType, type[_ProviderConfig]] = {
    SSOProviderType.GOOGLE_OAUTH: GoogleProviderConfig,
    SSOProviderType.OIDC: OIDCProviderConfig,
    SSOProviderType.SAML: SAMLProviderConfig,
}


def validate_sso_config(
    provider_type: SSOProviderType, config: dict[str, Any]
) -> dict[str, Any]:
    """Validate a raw config against its provider type and return the normalized
    dict for storage. Raises ValueError on a missing or unknown field so callers
    see one exception type regardless of the provider."""
    try:
        return _CONFIG_MODEL_BY_TYPE[provider_type].model_validate(config).model_dump()
    except ValidationError as e:
        raise ValueError(f"invalid {provider_type.value} provider config: {e}") from e


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
    config: dict[str, Any],
    allowed_email_domains: list[str],
) -> SSOProvider:
    validate_sso_provider_name(name)
    provider = SSOProvider(
        name=name,
        display_name=display_name,
        provider_type=provider_type,
        config=validate_sso_config(provider_type, config),
        allowed_email_domains=_normalize_domains(allowed_email_domains),
    )
    db_session.add(provider)
    db_session.commit()
    return provider


def update_sso_provider(
    db_session: Session,
    provider_id: int,
    display_name: str | None = None,
    config: dict[str, Any] | None = None,
    allowed_email_domains: list[str] | None = None,
) -> SSOProvider:
    """Partial update. Name and provider_type are immutable: linked login
    accounts and the login URL reference the name, and the type fixes the config
    shape. A None field is left unchanged, so the config (and its secrets) is
    only rewritten when a new one is supplied."""
    provider = db_session.get(SSOProvider, provider_id)
    if provider is None:
        raise ValueError(f"SSO provider {provider_id} does not exist")

    if display_name is not None:
        provider.display_name = display_name
    if config is not None:
        provider.config = validate_sso_config(  # ty: ignore[invalid-assignment]
            provider.provider_type, config
        )
    if allowed_email_domains is not None:
        provider.allowed_email_domains = _normalize_domains(allowed_email_domains)

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
