"""The sso_provider store must round-trip encrypted secrets, enforce the
slug name contract, preserve secrets on partial update, and keep
disable-not-delete semantics."""

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
        provider_type=SSOProviderType.GOOGLE,
        client_id="client-id",
        client_secret="super-secret",
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
    # secret decrypts to the original and masks by default
    assert fetched.client_secret is not None
    assert fetched.client_secret.get_value(apply_mask=False) == "super-secret"
    assert fetched.client_secret.get_value(apply_mask=True) != "super-secret"


def test_invalid_name_rejected(db_session: Session) -> None:
    with pytest.raises(ValueError):
        create_sso_provider(
            db_session,
            name="Not A Slug!",
            display_name="X",
            provider_type=SSOProviderType.GOOGLE,
            client_id="cid",
            client_secret="s",
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
            openid_config_url=None,
        )


def test_partial_update_preserves_secret(
    db_session: Session, provider_name: str
) -> None:
    created = _create(db_session, provider_name)

    updated = update_sso_provider(
        db_session, created.id, display_name="Renamed", client_secret=None
    )
    assert updated.display_name == "Renamed"
    assert updated.client_secret is not None
    assert updated.client_secret.get_value(apply_mask=False) == "super-secret"


def test_disable_keeps_row_and_filters(db_session: Session, provider_name: str) -> None:
    created = _create(db_session, provider_name)

    set_sso_provider_enabled(db_session, created.id, enabled=False)

    all_names = {p.name for p in fetch_sso_providers(db_session)}
    enabled_names = {p.name for p in fetch_sso_providers(db_session, enabled_only=True)}
    assert provider_name in all_names
    assert provider_name not in enabled_names
