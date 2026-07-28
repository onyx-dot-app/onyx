"""LIMITED service accounts hold chat scope derived from their role, not
from groups, so any recompute converges them to it instead of wiping it."""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import AccountType
from onyx.db.permissions import recompute_user_permissions__no_commit
from tests.external_dependency_unit.conftest import create_test_user


def test_recompute_derives_limited_key_scope(db_session: Session) -> None:
    limited_key_user = create_test_user(
        db_session,
        "limited_key",
        role=UserRole.LIMITED,
        account_type=AccountType.SERVICE_ACCOUNT,
    )
    assert limited_key_user.effective_permissions == []

    recompute_user_permissions__no_commit(limited_key_user.id, db_session)
    db_session.commit()

    db_session.refresh(limited_key_user)
    assert limited_key_user.effective_permissions == ["write:chat"]


def test_recompute_batch_handles_mixed_users(db_session: Session) -> None:
    limited_key_user = create_test_user(
        db_session,
        "limited_key",
        role=UserRole.LIMITED,
        account_type=AccountType.SERVICE_ACCOUNT,
    )
    standard_user = create_test_user(db_session, "standard")
    standard_user.effective_permissions = ["basic"]
    db_session.commit()

    user_ids: list[UUID] = [limited_key_user.id, standard_user.id]
    recompute_user_permissions__no_commit(user_ids, db_session)
    db_session.commit()

    db_session.refresh(limited_key_user)
    db_session.refresh(standard_user)
    assert limited_key_user.effective_permissions == ["write:chat"]
    # standard user is in no groups, so a recompute clears the stale grant
    assert standard_user.effective_permissions == []
