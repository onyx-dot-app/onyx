"""Private skill ownership survives user deletion without automatic succession."""

from contextlib import nullcontext
from unittest.mock import AsyncMock, patch

import pytest
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ee.onyx.server.tenants.team_membership_api import leave_organization
from onyx.auth.users import UserManager
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.models import User, User__UserGroup
from onyx.db.skill import transfer_skill_ownership
from onyx.db.users import delete_user_from_db__no_commit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.models import UserByEmail
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.craft.db_helpers import make_skill, make_user


def test_owner_must_transfer_private_skills_before_deletion(
    db_session: Session,
) -> None:
    owner = make_user(db_session, standard_account=True)
    successor = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id)

    with pytest.raises(OnyxError) as exc:
        delete_user_from_db__no_commit(owner, db_session)
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    assert skill.author_user_id == owner.id
    assert db_session.get(User, owner.id) is owner

    transfer_skill_ownership(
        skill=skill, new_owner_user_id=successor.id, db_session=db_session
    )
    delete_user_from_db__no_commit(owner, db_session)
    assert db_session.get(User, owner.id) is None
    assert skill.author_user_id == successor.id


def test_database_rejects_deletion_that_would_orphan_private_skill(
    db_session: Session,
) -> None:
    owner = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id)
    with pytest.raises(IntegrityError, match="ck_private_skill_has_owner"):
        with db_session.begin_nested():
            db_session.execute(
                delete(User__UserGroup).where(User__UserGroup.user_id == owner.id)
            )
            db_session.execute(delete(User).where(User.__table__.c.id == owner.id))
    assert db_session.get(User, owner.id) is owner
    db_session.refresh(skill)
    assert skill.author_user_id == owner.id


def test_public_skill_keeps_existing_admin_recovery_behavior(
    db_session: Session,
) -> None:
    owner = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id, is_public=True)
    delete_user_from_db__no_commit(owner, db_session)
    db_session.refresh(skill)
    assert skill.author_user_id is None


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("concurrent_assignment", [False, True])
async def test_auth_deletion_uses_same_private_ownership_guard(
    db_session: Session,
    concurrent_assignment: bool,
) -> None:
    owner = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id)
    db_session.commit()
    owner_id = owner.id
    try:
        async with get_async_session_context_manager(
            get_current_tenant_id()
        ) as session:
            async_owner = await session.get(User, owner_id)
            assert async_owner is not None
            manager = UserManager(SQLAlchemyUserDatabase(session, User))
            # Simulate ownership being assigned after the precheck has passed.
            precheck = (
                patch.object(session.sync_session, "scalar", return_value=None)
                if concurrent_assignment
                else nullcontext()
            )
            with precheck, pytest.raises(OnyxError) as exc:
                await manager.delete(async_owner)
            assert exc.value.error_code == OnyxErrorCode.CONFLICT
            assert "Transfer or delete" in exc.value.detail
            await session.rollback()
        assert db_session.get(User, owner_id) is not None
    finally:
        db_session.delete(skill)
        db_session.flush()
        delete_user_from_db__no_commit(owner, db_session)
        db_session.commit()


@pytest.mark.asyncio(loop_scope="module")
async def test_last_admin_guard_runs_before_remote_deletion(
    db_session: Session,
) -> None:
    owner = make_user(db_session, is_admin=True)
    make_skill(db_session, author_user_id=owner.id)
    with (
        patch(
            "ee.onyx.server.tenants.team_membership_api.get_user_count",
            AsyncMock(return_value=1),
        ),
        patch(
            "ee.onyx.server.tenants.team_membership_api.delete_user_from_control_plane",
            AsyncMock(),
        ) as remote,
    ):
        with pytest.raises(OnyxError) as exc:
            await leave_organization(
                UserByEmail(user_email=owner.email), owner, db_session
            )
        assert exc.value.error_code == OnyxErrorCode.CONFLICT
        remote.assert_not_called()


@pytest.mark.asyncio(loop_scope="module")
async def test_auth_deletion_cleans_up_group_membership(db_session: Session) -> None:
    user = make_user(db_session, standard_account=True)
    user_id = user.id
    db_session.commit()
    assert (
        db_session.scalar(
            select(User__UserGroup).where(User__UserGroup.user_id == user_id)
        )
        is not None
    )
    try:
        async with get_async_session_context_manager(
            get_current_tenant_id()
        ) as session:
            async_user = await session.get(User, user_id)
            assert async_user is not None
            manager = UserManager(SQLAlchemyUserDatabase(session, User))
            await manager.delete(async_user)
        db_session.expire_all()
        assert db_session.get(User, user_id) is None
        assert (
            db_session.scalar(
                select(User__UserGroup).where(User__UserGroup.user_id == user_id)
            )
            is None
        )
    finally:
        remaining_user = db_session.get(User, user_id)
        if remaining_user is not None:
            delete_user_from_db__no_commit(remaining_user, db_session)
            db_session.commit()
