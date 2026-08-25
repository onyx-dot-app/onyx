"""A first OIDC login for an unknown email must create the user with a role.

The oauth signup path builds a user dict without `role` and relies on the
bound user_db adapter to assign it. `user.role` is NOT NULL with no default,
so binding the wrong adapter fails the INSERT (regression from #14193,
shipped in v4.6.2).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import delete
from sqlalchemy.orm import Session

import onyx.auth.users as users_module
from onyx.auth.schemas import UserRole
from onyx.auth.users import UserManager
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.models import OAuthAccount, User, User__UserGroup
from onyx.server.security.store import _build_env_defaults
from tests.external_dependency_unit.conftest import create_test_user

_OAUTH_NAME = "oidc"


def _user_by_email(db_session: Session, email: str) -> User | None:
    return (
        db_session.query(User)
        .filter(User.email == email)  # ty: ignore[invalid-argument-type]
        .first()
    )


def _delete_user_fully(db_session: Session, email: str) -> None:
    user = _user_by_email(db_session, email)
    if user is None:
        return
    db_session.execute(
        delete(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
    )
    db_session.execute(
        delete(User__UserGroup).where(User__UserGroup.user_id == user.id)
    )
    db_session.delete(user)
    db_session.commit()


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_new_oauth_user_is_created_with_role(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(users_module, "MULTI_TENANT", False)
    monkeypatch.setattr(users_module, "get_security_settings", _build_env_defaults)

    # An existing user keeps the first-user ADMIN promotion out of the picture.
    seed_user = create_test_user(db_session, "oauth_role_seed")
    new_email = f"oauth_role_new_{uuid4().hex[:8]}@example.com"

    try:
        async with get_async_session_context_manager() as injected_session:
            manager = UserManager(
                SQLAlchemyUserDatabase(injected_session, User, OAuthAccount)
            )
            created = await manager.oauth_callback(
                oauth_name=_OAUTH_NAME,
                access_token="test-access-token",
                account_id=f"entra-{uuid4().hex}",
                account_email=new_email,
                is_verified_by_default=True,
            )
            assert created.role == UserRole.BASIC

        db_session.expire_all()
        persisted = _user_by_email(db_session, new_email)
        assert persisted is not None
        assert persisted.role == UserRole.BASIC
    finally:
        _delete_user_fully(db_session, new_email)
        _delete_user_fully(db_session, seed_user.email)
