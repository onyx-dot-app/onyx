"""With auto-link off, a login whose subject matches no link but whose email
matches a row linked under the same provider rewrites that link: the IdP behind
the provider re-issued its subjects (a new Entra app registration does this).
A link under another provider still rejects the login.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi_users import exceptions
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import onyx.auth.users as users_module
from onyx.auth.users import UserManager
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.models import OAuthAccount, User
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_PROVIDER = "oidc"
_ROTATED_TOKEN = "rotated-access-token"


def _attach_link(db_session: Session, user: User, oauth_name: str) -> str:
    account_id = f"sub-{uuid4().hex}"
    db_session.add(
        OAuthAccount(
            user_id=user.id,
            oauth_name=oauth_name,
            account_id=account_id,
            account_email=user.email,
            access_token="stale-access-token",
            refresh_token="",
        )
    )
    db_session.commit()
    return account_id


def _links(db_session: Session, user: User) -> list[tuple[str, str, str]]:
    db_session.expire_all()
    rows = db_session.scalars(
        select(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
    )
    return [(row.oauth_name, row.account_id, row.access_token) for row in rows]


def _teardown(db_session: Session, user: User) -> None:
    db_session.execute(
        delete(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
    )
    delete_test_user(db_session, user)
    db_session.commit()


async def _login(
    user_email: str, account_id: str, monkeypatch: pytest.MonkeyPatch
) -> User:
    monkeypatch.setattr(users_module, "MULTI_TENANT", False)
    async with get_async_session_context_manager() as session:
        manager = UserManager(SQLAlchemyUserDatabase(session, User, OAuthAccount))
        return await manager.oauth_callback(
            oauth_name=_PROVIDER,
            access_token=_ROTATED_TOKEN,
            account_id=account_id,
            account_email=user_email,
            associate_by_email=False,
            is_verified_by_default=True,
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_same_provider_new_subject_rewrites_link(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = create_test_user(db_session, "relink_same_provider")
    _attach_link(db_session, user, _PROVIDER)
    new_subject = f"sub-{uuid4().hex}"
    try:
        result = await _login(user.email, new_subject, monkeypatch)

        assert result.id == user.id
        # Rewritten, not appended.
        assert _links(db_session, user) == [(_PROVIDER, new_subject, _ROTATED_TOKEN)]
    finally:
        _teardown(db_session, user)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_other_provider_link_still_rejects(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = create_test_user(db_session, "relink_other_provider")
    other_subject = _attach_link(db_session, user, "okta")
    try:
        with pytest.raises(exceptions.UserAlreadyExists):
            await _login(user.email, f"sub-{uuid4().hex}", monkeypatch)

        assert _links(db_session, user) == [
            ("okta", other_subject, "stale-access-token")
        ]
    finally:
        _teardown(db_session, user)
