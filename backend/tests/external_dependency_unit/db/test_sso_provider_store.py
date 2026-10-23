"""The sso_provider store must round-trip the encrypted per-type config,
enforce the slug name contract, validate config against provider_type, preserve
config on partial update, keep links through a disable, and import the legacy
SAML config only once so a deleted import stays deleted."""

import json
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

import onyx.db.sso_provider as sso_provider_module
from onyx.configs.constants import KV_LEGACY_SAML_IMPORTED_KEY
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.db.sso_provider import (
    create_sso_provider,
    delete_sso_provider_links__no_commit,
    delete_sso_provider_row__no_commit,
    fetch_sso_provider_by_name,
    fetch_sso_providers,
    seed_saml_provider_from_conf_dir,
    set_sso_provider_enabled,
    update_sso_provider,
    validate_sso_provider_name,
)
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError

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


def _delete_provider(db_session: Session, provider_id: int) -> None:
    name = delete_sso_provider_row__no_commit(db_session, provider_id)
    delete_sso_provider_links__no_commit(db_session, name)
    db_session.commit()


@pytest.fixture()
def provider_name(db_session: Session) -> Generator[str, None, None]:
    name = f"{_NAME_PREFIX}-{uuid4().hex[:8]}"
    yield name
    db_session.execute(delete(SSOProvider).where(SSOProvider.name.like(f"{name}%")))
    db_session.commit()


def _create(db_session: Session, name: str, **overrides: object) -> SSOProvider:
    kwargs: dict = {
        "name": name,
        "display_name": "Company A",
        "provider_type": SSOProviderType.GOOGLE_OAUTH,
        "config": dict(_GOOGLE_CONFIG),
        "allowed_email_domains": ["CompanyA.com ", "companya.com"],
    }
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
        "pkce_enabled": False,
        "scopes": [],
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
        "pkce_enabled": False,
        "scopes": [],
    }


def test_disable_keeps_row_and_filters(db_session: Session, provider_name: str) -> None:
    created = _create(db_session, provider_name)

    set_sso_provider_enabled(db_session, created.id, enabled=False)

    all_names = {p.name for p in fetch_sso_providers(db_session)}
    enabled_names = {p.name for p in fetch_sso_providers(db_session, enabled_only=True)}
    assert provider_name in all_names
    assert provider_name not in enabled_names


def _forget_legacy_saml_import() -> None:
    try:
        get_kv_store().delete(KV_LEGACY_SAML_IMPORTED_KEY)
    except KvKeyNotFoundError:
        return


@pytest.mark.usefixtures("tenant_context")
def test_legacy_saml_import_does_not_restore_a_deleted_row(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not any(
        provider.provider_type is SSOProviderType.SAML
        for provider in fetch_sso_providers(db_session)
    ), "needs a database with no SAML provider"
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "idp": {
                    "entityId": _SAML_CONFIG["idp_entity_id"],
                    "singleSignOnService": {"url": _SAML_CONFIG["idp_sso_url"]},
                    "x509cert": _SAML_CONFIG["idp_x509_cert"],
                },
                "sp": {"entityId": _SAML_CONFIG["sp_entity_id"]},
            }
        )
    )
    monkeypatch.setenv("AUTH_TYPE", "saml")
    monkeypatch.setattr(sso_provider_module, "MULTI_TENANT", False)
    monkeypatch.setattr(sso_provider_module, "SAML_CONF_DIR", str(tmp_path))
    _forget_legacy_saml_import()
    try:
        seed_saml_provider_from_conf_dir(db_session)
        imported = fetch_sso_provider_by_name(db_session, "saml")
        assert imported is not None

        _delete_provider(db_session, imported.id)
        seed_saml_provider_from_conf_dir(db_session)

        assert fetch_sso_provider_by_name(db_session, "saml") is None
    finally:
        db_session.rollback()
        db_session.execute(delete(SSOProvider).where(SSOProvider.name == "saml"))
        db_session.commit()
        _forget_legacy_saml_import()
