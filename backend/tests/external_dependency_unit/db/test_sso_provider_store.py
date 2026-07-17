"""The sso_provider store must round-trip the encrypted per-type config,
enforce the slug name contract, validate config against provider_type, preserve
config on partial update, and keep disable-not-delete semantics."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.db.sso_provider import create_sso_provider
from onyx.db.sso_provider import fetch_sso_provider_by_name
from onyx.db.sso_provider import fetch_sso_providers
from onyx.db.sso_provider import set_sso_provider_enabled
from onyx.db.sso_provider import update_sso_provider
from onyx.db.sso_provider import validate_sso_provider_name

_NAME_PREFIX = "testsso"
_GOOGLE_CONFIG = {"client_id": "client-id", "client_secret": "super-secret"}
_OIDC_CONFIG = {
    "client_id": "client-id",
    "client_secret": "super-secret",
    "openid_config_url": "https://idp.example.com/.well-known/openid-configuration",
}
_SAML_CONFIG = {
    "idp_entity_id": "https://idp.example.com/entity",
    "idp_sso_url": "https://idp.example.com/sso",
    "idp_x509_cert": "MIIC-fake-cert",
    "sp_entity_id": "https://onyx.example.com/saml",
}


@pytest.fixture()
def provider_name(db_session: Session) -> Generator[str, None, None]:
    name = f"{_NAME_PREFIX}-{uuid4().hex[:8]}"
    yield name
    db_session.execute(delete(SSOProvider).where(SSOProvider.name.like(f"{name}%")))
    db_session.commit()


def _create(db_session: Session, name: str, **overrides: object) -> SSOProvider:
    kwargs: dict = dict(
        name=name,
        display_name="Company A",
        provider_type=SSOProviderType.GOOGLE_OAUTH,
        config=dict(_GOOGLE_CONFIG),
        allowed_email_domains=["CompanyA.com ", "companya.com"],
    )
    kwargs.update(overrides)
    return create_sso_provider(db_session, **kwargs)


def test_create_and_fetch_roundtrip(db_session: Session, provider_name: str) -> None:
    created = _create(db_session, provider_name)

    fetched = fetch_sso_provider_by_name(db_session, provider_name)
    assert fetched is not None
    assert fetched.id == created.id
    # domains are deduped and lowercased
    assert fetched.allowed_email_domains == ["companya.com"]
    # config decrypts to the original and masks the secret by default
    assert fetched.config is not None
    assert fetched.config.get_value(apply_mask=False) == {
        **_GOOGLE_CONFIG,
        "legacy_callback": False,
    }
    assert fetched.config.get_value(apply_mask=True)["client_secret"] != "super-secret"


def test_invalid_name_rejected(db_session: Session) -> None:
    with pytest.raises(ValueError):
        create_sso_provider(
            db_session,
            name="Not A Slug!",
            display_name="X",
            provider_type=SSOProviderType.GOOGLE_OAUTH,
            config=dict(_GOOGLE_CONFIG),
            allowed_email_domains=[],
        )
    for bad in ("-leading", "trailing-", "UPPER", "with space"):
        with pytest.raises(ValueError):
            validate_sso_provider_name(bad)


def test_oidc_requires_config_url(db_session: Session, provider_name: str) -> None:
    with pytest.raises(ValueError):
        _create(
            db_session,
            provider_name,
            provider_type=SSOProviderType.OIDC,
            config=dict(_GOOGLE_CONFIG),  # missing openid_config_url
        )


def test_google_rejects_unknown_config_key(
    db_session: Session, provider_name: str
) -> None:
    with pytest.raises(ValueError):
        _create(
            db_session,
            provider_name,
            provider_type=SSOProviderType.GOOGLE_OAUTH,
            config=dict(_OIDC_CONFIG),  # openid_config_url not allowed for GOOGLE
        )


def test_saml_config_validates_and_roundtrips(
    db_session: Session, provider_name: str
) -> None:
    created = _create(
        db_session,
        provider_name,
        provider_type=SSOProviderType.SAML,
        config=dict(_SAML_CONFIG),
    )
    db_session.expire(created)

    fetched = fetch_sso_provider_by_name(db_session, provider_name)
    assert fetched is not None
    assert fetched.provider_type is SSOProviderType.SAML
    assert fetched.config is not None
    stored = fetched.config.get_value(apply_mask=False)
    assert stored["idp_entity_id"] == _SAML_CONFIG["idp_entity_id"]
    # optional field defaults to None and is persisted
    assert stored["email_attribute"] is None


def test_saml_missing_field_rejected(db_session: Session, provider_name: str) -> None:
    incomplete = {k: v for k, v in _SAML_CONFIG.items() if k != "idp_x509_cert"}
    with pytest.raises(ValueError):
        _create(
            db_session,
            provider_name,
            provider_type=SSOProviderType.SAML,
            config=incomplete,
        )


def test_provider_type_roundtrips_through_db(
    db_session: Session, provider_name: str
) -> None:
    created = _create(
        db_session,
        provider_name,
        provider_type=SSOProviderType.OIDC,
        config=dict(_OIDC_CONFIG),
    )
    db_session.expire(created)
    fetched = fetch_sso_provider_by_name(db_session, provider_name)
    assert fetched is not None
    assert fetched.provider_type is SSOProviderType.OIDC


def test_disabled_provider_hidden_from_enabled_only_by_name(
    db_session: Session, provider_name: str
) -> None:
    created = _create(db_session, provider_name)
    set_sso_provider_enabled(db_session, created.id, enabled=False)

    assert fetch_sso_provider_by_name(db_session, provider_name) is not None
    assert (
        fetch_sso_provider_by_name(db_session, provider_name, enabled_only=True) is None
    )


def test_partial_update_preserves_config(
    db_session: Session, provider_name: str
) -> None:
    created = _create(db_session, provider_name)

    updated = update_sso_provider(db_session, created.id, display_name="Renamed")
    assert updated.display_name == "Renamed"
    assert updated.config is not None
    assert updated.config.get_value(apply_mask=False) == {
        **_GOOGLE_CONFIG,
        "legacy_callback": False,
    }


def test_disable_keeps_row_and_filters(db_session: Session, provider_name: str) -> None:
    created = _create(db_session, provider_name)

    set_sso_provider_enabled(db_session, created.id, enabled=False)

    all_names = {p.name for p in fetch_sso_providers(db_session)}
    enabled_names = {p.name for p in fetch_sso_providers(db_session, enabled_only=True)}
    assert provider_name in all_names
    assert provider_name not in enabled_names
