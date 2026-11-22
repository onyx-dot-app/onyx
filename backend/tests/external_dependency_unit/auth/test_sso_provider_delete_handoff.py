"""Deleting a provider hands its users to the providers that remain. A row linked
to the old provider rejects a second provider's login, and once the old provider
is deleted the same login claims the row by email instead of creating a new one.
A renamed row stays closed until an admin opens the renamed-account claim
window, and a login whose provider was deleted mid-flight writes no link.
"""

from uuid import uuid4

import pytest
from fastapi_users import exceptions
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import onyx.auth.users as users_module
from onyx.auth.users import UserManager
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.enums import SSOProviderType
from onyx.db.models import OAuthAccount, SSOProvider, User
from onyx.db.sso_provider import (
    count_sso_provider_links,
    create_sso_provider,
    delete_sso_provider_links__no_commit,
    delete_sso_provider_row__no_commit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.store import _build_env_defaults
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_OIDC_CONFIG = {
    "client_id": "client-id",
    "client_secret": "client-secret",
    "openid_config_url": "https://idp.example.com/.well-known/openid-configuration",
}


def _delete_provider(db_session: Session, provider_id: int) -> None:
    name = delete_sso_provider_row__no_commit(db_session, provider_id)
    delete_sso_provider_links__no_commit(db_session, name)
    db_session.commit()


def _create_provider(db_session: Session, prefix: str) -> SSOProvider:
    return create_sso_provider(
        db_session,
        name=f"{prefix}-{uuid4().hex[:8]}",
        display_name=prefix,
        provider_type=SSOProviderType.OIDC,
        config=dict(_OIDC_CONFIG),
        allowed_email_domains=[],
    )


def _attach_link(db_session: Session, user: User, oauth_name: str) -> None:
    db_session.add(
        OAuthAccount(
            user_id=user.id,
            oauth_name=oauth_name,
            account_id=f"sub-{uuid4().hex}",
            account_email=user.email,
            access_token="old-access-token",
            refresh_token="",
        )
    )
    db_session.commit()


def _link_names(db_session: Session, user: User) -> list[str]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(OAuthAccount.__table__.c.oauth_name).where(
                OAuthAccount.__table__.c.user_id == user.id
            )
        )
    )


async def _login(
    oauth_name: str,
    user_email: str,
    account_id: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    renamed_claim_open: bool = False,
    sso_provider_id: int | None = None,
) -> User:
    monkeypatch.setattr(users_module, "MULTI_TENANT", False)
    settings = _build_env_defaults().model_copy(
        update={"allow_renamed_account_claim": renamed_claim_open}
    )
    monkeypatch.setattr(users_module, "get_security_settings", lambda: settings)
    async with get_async_session_context_manager() as session:
        manager: UserManager = UserManager(
            SQLAlchemyUserDatabase(session, User, OAuthAccount)
        )
        return await manager.oauth_callback(
            oauth_name=oauth_name,
            access_token="new-access-token",
            account_id=account_id,
            account_email=user_email,
            associate_by_email=False,
            is_verified_by_default=True,
            sso_provider_id=sso_provider_id,
        )


def _cleanup(db_session: Session, users: list[User], provider_names: list[str]) -> None:
    db_session.rollback()
    db_session.execute(
        delete(OAuthAccount).where(
            OAuthAccount.__table__.c.user_id.in_([user.id for user in users])
        )
    )
    db_session.execute(delete(SSOProvider).where(SSOProvider.name.in_(provider_names)))
    for user in users:
        delete_test_user(db_session, user)
    db_session.commit()


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_deleting_old_provider_lets_new_provider_claim_the_account(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_provider = _create_provider(db_session, "old-idp")
    new_provider = _create_provider(db_session, "new-idp")
    old_name, new_name = old_provider.name, new_provider.name
    user: User = create_test_user(db_session, "sso_delete_handoff")
    bystander: User = create_test_user(db_session, "sso_delete_bystander")
    _attach_link(db_session, user, old_name)
    _attach_link(db_session, bystander, new_name)
    new_subject = f"sub-{uuid4().hex}"
    try:
        with pytest.raises(exceptions.UserAlreadyExists):
            await _login(new_name, user.email, new_subject, monkeypatch)

        _delete_provider(db_session, old_provider.id)

        assert _link_names(db_session, user) == []
        # Only the deleted provider's links go.
        assert _link_names(db_session, bystander) == [new_name]

        result: User = await _login(new_name, user.email, new_subject, monkeypatch)

        assert result.id == user.id
        assert _link_names(db_session, user) == [new_name]
    finally:
        _cleanup(db_session, [user, bystander], [old_name, new_name])


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_renamed_user_claims_only_through_the_admin_window(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_provider = _create_provider(db_session, "old-idp")
    new_provider = _create_provider(db_session, "new-idp")
    old_name, new_name = old_provider.name, new_provider.name
    user: User = create_test_user(db_session, "sso_delete_renamed")
    user.prior_emails = ["before-rename@example.com"]
    db_session.commit()
    _attach_link(db_session, user, old_name)
    new_subject = f"sub-{uuid4().hex}"
    try:
        counts = count_sso_provider_links(db_session, old_name)
        assert (counts.linked_users, counts.renamed_users) == (1, 1)

        _delete_provider(db_session, old_provider.id)

        with pytest.raises(exceptions.UserAlreadyExists):
            await _login(new_name, user.email, new_subject, monkeypatch)

        result: User = await _login(
            new_name, user.email, new_subject, monkeypatch, renamed_claim_open=True
        )

        assert result.id == user.id
        assert _link_names(db_session, user) == [new_name]
        db_session.expire_all()
        assert db_session.get(User, user.id) is not None
        assert user.prior_emails == ["before-rename@example.com"]
    finally:
        _cleanup(db_session, [user], [old_name, new_name])


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_login_for_a_deleted_provider_writes_no_link(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The callback resolved the provider before the delete finished, so its
    write phase must notice the row is gone instead of linking it again."""
    provider = _create_provider(db_session, "gone-idp")
    name, provider_id = provider.name, provider.id
    user: User = create_test_user(db_session, "sso_delete_inflight")
    try:
        _delete_provider(db_session, provider_id)

        with pytest.raises(OnyxError) as excinfo:
            await _login(
                name,
                user.email,
                f"sub-{uuid4().hex}",
                monkeypatch,
                sso_provider_id=provider_id,
            )

        assert excinfo.value.error_code is OnyxErrorCode.NOT_FOUND
        assert _link_names(db_session, user) == []
    finally:
        _cleanup(db_session, [user], [name])
