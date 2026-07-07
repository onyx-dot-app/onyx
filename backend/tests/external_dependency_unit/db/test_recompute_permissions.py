"""LIMITED service accounts hold a direct write:chat grant (set by the
API-key code, not derived from groups), so group-based recomputes must
leave them untouched while still recomputing everyone else."""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import AccountType
from onyx.db.permissions import recompute_user_permissions__no_commit
from tests.external_dependency_unit.conftest import create_test_user


def test_recompute_skips_limited_service_account(db_session: Session) -> None:
    limited_key_user = create_test_user(
        db_session,
        "limited_key",
        role=UserRole.LIMITED,
        account_type=AccountType.SERVICE_ACCOUNT,
    )
    limited_key_user.effective_permissions = ["write:chat"]
    db_session.commit()

    recompute_user_permissions__no_commit(limited_key_user.id, db_session)
    db_session.commit()

    db_session.refresh(limited_key_user)
    assert limited_key_user.effective_permissions == ["write:chat"]


def test_recompute_still_updates_other_users_in_batch(db_session: Session) -> None:
    limited_key_user = create_test_user(
        db_session,
        "limited_key",
        role=UserRole.LIMITED,
        account_type=AccountType.SERVICE_ACCOUNT,
    )
    limited_key_user.effective_permissions = ["write:chat"]
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
