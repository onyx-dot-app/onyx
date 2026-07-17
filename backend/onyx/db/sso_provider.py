import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.configs.app_configs import SAML_CONF_DIR
from onyx.configs.app_configs import VALID_EMAIL_DOMAINS
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

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
    # Rows migrated from single-provider env config keep the redirect URI the
    # customer's IdP client already allowlists.
    legacy_callback: bool = False


class OIDCProviderConfig(_ProviderConfig):
    client_id: str
    client_secret: str
    openid_config_url: str
    legacy_callback: bool = False


class SAMLProviderConfig(_ProviderConfig):
    """Config for a SAML provider: the IdP metadata a SAML login validates
    against, plus optional SP signing material."""

    idp_entity_id: str
    idp_sso_url: str
    idp_x509_cert: str
    sp_entity_id: str
    # SP signing material, only needed when the deployment signs AuthnRequests
    # or decrypts assertions. Held in the encrypted config blob.
    sp_x509_cert: str | None = None
    sp_private_key: str | None = None
    # IdP attribute the email is read from. None falls back to the common keys
    # (email, mail, the Entra/ADFS claim URIs) the SAML callback already tries.
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


def sso_login_callback_uri(
    provider: SSOProvider, config: dict[str, Any], web_domain: str
) -> str:
    """The redirect URI this row's login flow sends, which is also the URL an
    operator must allowlist at the IdP. Rows migrated from single-provider env
    config keep the legacy URI their IdP client already allowlists."""
    if provider.provider_type is SSOProviderType.SAML:
        # Single issuer-resolved ACS for every SAML row.
        return f"{web_domain}/api/auth/saml/callback"
    if config.get("legacy_callback"):
        if provider.provider_type is SSOProviderType.GOOGLE_OAUTH:
            return f"{web_domain}/auth/oauth/callback"
        return f"{web_domain}/auth/oidc/callback"
    # The IdP redirects the browser, so route through /api to reach FastAPI.
    return f"{web_domain}/api/auth/oidc/{provider.name}/callback"


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


def seed_saml_provider_from_conf_dir(db_session: Session) -> None:
    """Import a legacy single-config SAML_CONF_DIR/settings.json into a provider
    row on api_server startup (the api_server has the mount; the migration job
    does not). Idempotent and safe under concurrent pods."""
    if MULTI_TENANT:
        logger.debug("Skipping legacy SAML seed because multi-tenant mode is enabled")
        return

    # This env read exists only to migrate legacy AUTH_TYPE=saml deployments
    # to a provider row.
    if (os.environ.get("AUTH_TYPE") or "").lower() != "saml":
        logger.debug("Skipping legacy SAML seed because auth type is not saml")
        return

    for provider in fetch_sso_providers(db_session):
        if provider.provider_type is SSOProviderType.SAML:
            logger.debug(
                "Skipping legacy SAML seed because a SAML provider already exists"
            )
            return

    settings_path = Path(SAML_CONF_DIR) / "settings.json"
    try:
        raw_settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except OSError as e:
        logger.debug(
            "Skipping legacy SAML seed because %s could not be read: %s",
            settings_path,
            e,
        )
        return
    except ValueError as e:
        logger.info(
            "Skipping legacy SAML seed because %s is invalid JSON: %s",
            settings_path,
            e,
        )
        return

    settings = raw_settings if isinstance(raw_settings, dict) else {}

    def get_nested_value(settings_dict: dict[str, Any], *keys: str) -> Any:
        value: Any = settings_dict
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

    idp_entity_id = get_nested_value(settings, "idp", "entityId")
    idp_sso_url = get_nested_value(settings, "idp", "singleSignOnService", "url")
    idp_x509_cert = get_nested_value(settings, "idp", "x509cert")
    sp_entity_id = get_nested_value(settings, "sp", "entityId")
    sp_x509_cert = get_nested_value(settings, "sp", "x509cert")

    sp_private_key: str | None = None
    sp_private_key_path = Path(SAML_CONF_DIR) / "certs" / "sp.key"
    try:
        sp_private_key = sp_private_key_path.read_text(encoding="utf-8")
    except OSError:
        sp_private_key = None

    required_values = (
        idp_entity_id,
        idp_sso_url,
        idp_x509_cert,
        sp_entity_id,
    )
    if not all(isinstance(value, str) and value for value in required_values):
        logger.info(
            "Skipping legacy SAML seed because %s is missing required IdP settings",
            settings_path,
        )
        return

    config: dict[str, Any] = {
        "idp_entity_id": idp_entity_id,
        "idp_sso_url": idp_sso_url,
        "idp_x509_cert": idp_x509_cert,
        "sp_entity_id": sp_entity_id,
    }
    if isinstance(sp_x509_cert, str) and sp_x509_cert:
        config["sp_x509_cert"] = sp_x509_cert
    if sp_private_key:
        config["sp_private_key"] = sp_private_key

    try:
        create_sso_provider(
            db_session,
            name="saml",
            display_name="SAML SSO",
            provider_type=SSOProviderType.SAML,
            config=config,
            allowed_email_domains=[domain.lower() for domain in VALID_EMAIL_DOMAINS],
        )
    except IntegrityError:
        db_session.rollback()
        logger.debug("Skipping legacy SAML seed because another pod created the row")
        return
