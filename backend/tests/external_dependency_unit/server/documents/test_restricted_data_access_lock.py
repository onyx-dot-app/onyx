"""Concurrent data-access writes cannot remove the last group of a restricted pair."""

import contextvars
import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.cc_pair_data_access import (
    assert_restricted_cc_pairs_keep_a_group,
    fetch_data_access_groups_for_cc_pair,
    lock_cc_pairs_for_data_access__no_commit,
    remove_cc_pair_data_access__no_commit,
)
from ee.onyx.server.documents.cc_pair import set_cc_pair_data_access
from ee.onyx.server.documents.models import CCPairDataAccessUpdateRequest
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.models import UserGroup, UserGroup__CCPairDataAccess
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

pytestmark = pytest.mark.usefixtures("tenant_context")


def _group(db_session: Session) -> UserGroup:
    group = UserGroup(name=f"rda-{uuid4().hex[:12]}")
    db_session.add(group)
    db_session.flush()
    return group


def test_concurrent_removals_keep_one_group_on_a_restricted_pair(
    db_session: Session,
) -> None:
    """One writer removes the first group while a PUT sets only the first
    group. Without the lock, the PUT would remove the second group and both
    would commit."""
    admin = create_test_user(db_session, "rda-admin", is_admin=True)
    first = _group(db_session)
    second = _group(db_session)
    cc_pair = make_cc_pair(db_session)
    cc_pair.access_type = AccessType.SYNC_RESTRICTED
    for group in (first, second):
        db_session.add(
            UserGroup__CCPairDataAccess(cc_pair_id=cc_pair.id, user_group_id=group.id)
        )
    db_session.commit()

    errors: list[Exception] = []

    def _remove_second() -> None:
        with get_session_with_current_tenant() as other_session:
            try:
                set_cc_pair_data_access(
                    cc_pair.id,
                    CCPairDataAccessUpdateRequest(group_ids=[first.id]),
                    admin,
                    other_session,
                )
            except Exception as e:
                errors.append(e)

    try:
        with get_session_with_current_tenant() as holder:
            lock_cc_pairs_for_data_access__no_commit(holder, [cc_pair.id])
            remove_cc_pair_data_access__no_commit(
                holder, cc_pair_ids=[cc_pair.id], user_group_ids=[first.id]
            )
            assert_restricted_cc_pairs_keep_a_group(holder, [cc_pair.id])

            context = contextvars.copy_context()
            other = threading.Thread(target=context.run, args=(_remove_second,))
            other.start()
            time.sleep(1)
            # The other PUT waits for this transaction.
            assert other.is_alive()
            holder.commit()
        other.join(timeout=30)
        assert not other.is_alive()

        # The other PUT read the groups after this commit, so it kept one.
        assert errors == []
        db_session.expire_all()
        assert [
            group.id
            for group in fetch_data_access_groups_for_cc_pair(db_session, cc_pair.id)
        ] == [first.id]
    finally:
        db_session.rollback()
        cleanup_cc_pair(db_session, cc_pair)
