"""The manage-access rows carry each group's member and manager counts: the
fixed Admin row counts the admins, a stored row its group, an empty group zero."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.server.documents.cc_pair import get_cc_pair_manage_access
from onyx.db.enums import AccessType, ConnectorManageRole
from onyx.db.models import (
    User__UserGroup,
    UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

pytestmark = pytest.mark.usefixtures("tenant_context")


def _group(db_session: Session, members: int, managers: int) -> UserGroup:
    group = UserGroup(name=f"ma-count-{uuid4().hex[:12]}")
    db_session.add(group)
    db_session.flush()
    for index in range(members):
        user = create_test_user(db_session, "ma-count-member")
        db_session.add(
            User__UserGroup(
                user_id=user.id, user_group_id=group.id, is_manager=index < managers
            )
        )
    db_session.commit()
    return group


def test_rows_carry_member_and_manager_counts(db_session: Session) -> None:
    staffed = _group(db_session, members=3, managers=1)
    empty = _group(db_session, members=0, managers=0)
    admin = create_test_user(db_session, "ma-count-admin", is_admin=True)
    cc_pair = make_cc_pair(db_session)
    cc_pair.access_type = AccessType.PRIVATE
    for group, role in (
        (staffed, ConnectorManageRole.OPERATOR),
        (empty, ConnectorManageRole.EDITOR),
    ):
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group.id, cc_pair_id=cc_pair.id, role=role
            )
        )
    db_session.commit()

    rows = get_cc_pair_manage_access(cc_pair.id, admin, db_session)

    by_group = {row.group_id: row for row in rows}
    assert (by_group[staffed.id].member_count, by_group[staffed.id].manager_count) == (
        3,
        1,
    )
    assert (by_group[empty.id].member_count, by_group[empty.id].manager_count) == (
        0,
        0,
    )
    admin_row = next(row for row in rows if row.is_fixed and row.group_name == "Admin")
    # The admin joined the default Admin group, so it counts at least them.
    assert admin_row.member_count >= 1
