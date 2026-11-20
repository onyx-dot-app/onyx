"""Which groups the share and group access pickers offer
(``GET /user-groups/minimal``)."""

from collections.abc import Generator

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ee.onyx.server.user_group.api import list_minimal_user_groups
from onyx.db.enums import Permission
from onyx.db.models import User, User__UserGroup, UserGroup
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_group,
)


@pytest.fixture
def groups(db_session: Session) -> Generator[list[UserGroup], None, None]:
    made = [make_group(db_session), make_group(db_session)]
    db_session.commit()
    try:
        yield made
    finally:
        db_session.rollback()
        ids = [group.id for group in made]
        db_session.execute(
            delete(User__UserGroup).where(User__UserGroup.user_group_id.in_(ids))
        )
        db_session.execute(delete(UserGroup).where(UserGroup.id.in_(ids)))
        db_session.commit()


def _offered(user: User, db_session: Session, groups: list[UserGroup]) -> set[int]:
    wanted = {group.id for group in groups}
    return {
        group.id
        for group in list_minimal_user_groups(False, user, db_session)
        if group.id in wanted
    }


@pytest.mark.parametrize(
    "permission", [None, Permission.MANAGE_ACTIONS, Permission.MANAGE_PLUGINS]
)
def test_an_organization_wide_manager_picks_from_every_group(
    db_session: Session,
    make_test_user: MakeTestUser,
    groups: list[UserGroup],
    permission: Permission | None,
) -> None:
    mine, other = groups
    user = make_test_user(f"minimal-groups-{permission}")
    add_user_to_group(db_session, user, mine)
    if permission is not None:
        user.effective_permissions = [permission.value]
    db_session.commit()

    expected = {mine.id} if permission is None else {mine.id, other.id}
    assert _offered(user, db_session, groups) == expected
