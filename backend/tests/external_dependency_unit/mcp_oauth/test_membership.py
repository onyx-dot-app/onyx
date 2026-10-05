from collections.abc import Generator
from contextlib import contextmanager

import pytest
from sqlalchemy import Engine, Table, select
from sqlalchemy.orm import Session

from onyx.db import mcp_oauth
from onyx.db.models import UserTenantMapping, UserTenantMappingOAuthAccount
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


@pytest.fixture
def catalog(
    migration_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> Generator[Session, None, None]:
    for table in (UserTenantMapping.__table__, UserTenantMappingOAuthAccount.__table__):
        assert isinstance(table, Table)
        table.create(migration_database)

    @contextmanager
    def catalog_session() -> Generator[Session, None, None]:
        with Session(migration_database) as session:
            yield session

    monkeypatch.setattr(mcp_oauth, "get_catalog_session", catalog_session)
    monkeypatch.setattr(mcp_oauth, "MULTI_TENANT", True)
    with Session(migration_database) as session:
        yield session


def test_other_members_do_not_validate_retired_owner(catalog: Session) -> None:
    catalog.add_all(
        [
            UserTenantMapping(
                email="owner@example.com", tenant_id="tenant_a", active=False
            ),
            UserTenantMapping(
                email="other@example.com", tenant_id="tenant_a", active=True
            ),
            UserTenantMapping(
                email="owner@example.com", tenant_id="tenant_b", active=True
            ),
        ]
    )
    catalog.commit()
    assert mcp_oauth.mcp_oauth_tenant_has_members("tenant_a") is True
    assert (
        mcp_oauth.mcp_oauth_owner_is_member("tenant_a", "owner@example.com", [])
        is False
    )
    assert (
        mcp_oauth.mcp_oauth_owner_is_member("tenant_b", "OWNER@example.com", []) is True
    )
    assert mcp_oauth.mcp_oauth_tenant_has_members("nonexistent") is False
    catalog.expire_all()
    rows = list(catalog.scalars(select(UserTenantMapping)).all())
    assert len(rows) == 3
    assert sum(row.active for row in rows) == 2


def test_persisted_subject_survives_email_rename_but_not_membership_retirement(
    catalog: Session,
) -> None:
    owner = UserTenantMapping(
        email="old@example.com", tenant_id="tenant_a", active=True
    )
    catalog.add(owner)
    catalog.flush()
    catalog.add(
        UserTenantMappingOAuthAccount(
            email=owner.email,
            tenant_id=owner.tenant_id,
            oauth_name="oidc:company",
            account_id="stable-subject",
        )
    )
    catalog.commit()
    assert (
        mcp_oauth.mcp_oauth_owner_is_member(
            "tenant_a", "new@example.com", [("oidc:company", "stable-subject")]
        )
        is True
    )
    assert (
        mcp_oauth.mcp_oauth_owner_is_member(
            "tenant_b", "new@example.com", [("oidc:company", "stable-subject")]
        )
        is False
    )
    assert (
        mcp_oauth.mcp_oauth_owner_is_member(
            "tenant_a", "new@example.com", [("other-provider", "stable-subject")]
        )
        is False
    )
    owner.active = False
    catalog.commit()
    assert (
        mcp_oauth.mcp_oauth_owner_is_member(
            "tenant_a", "new@example.com", [("oidc:company", "stable-subject")]
        )
        is False
    )


def test_self_hosted_does_not_open_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_oauth, "MULTI_TENANT", False)

    def unexpected_catalog() -> None:
        raise AssertionError("Self-hosted membership must not query catalog tables")

    monkeypatch.setattr(mcp_oauth, "get_catalog_session", unexpected_catalog)
    assert (
        mcp_oauth.mcp_oauth_owner_is_member(
            POSTGRES_DEFAULT_SCHEMA, "owner@example.com", []
        )
        is True
    )
    assert mcp_oauth.mcp_oauth_tenant_has_members(POSTGRES_DEFAULT_SCHEMA) is True
    assert mcp_oauth.mcp_oauth_tenant_has_members("tenant_other") is False
