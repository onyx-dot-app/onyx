"""Renaming a user group keeps its connectors once the group has re-synced."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ee.onyx.db.user_group import mark_user_group_as_synced, rename_user_group
from onyx.db.enums import ConnectorManageRole
from onyx.db.models import (
    ConnectorCredentialPair,
    UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def group_with_cc_pair(
    db_session: Session,
) -> Generator[tuple[UserGroup, ConnectorCredentialPair], None, None]:
    cc_pair = make_cc_pair(db_session)
    group = UserGroup(name=f"rename-test-{uuid4().hex[:12]}", is_up_to_date=True)
    db_session.add(group)
    db_session.flush()
    db_session.add(
        UserGroup__ConnectorCredentialPair(
            user_group_id=group.id,
            cc_pair_id=cc_pair.id,
            is_current=True,
            role=ConnectorManageRole.EDITOR,
        )
    )
    db_session.commit()
    yield group, cc_pair

    db_session.execute(
        delete(UserGroup__ConnectorCredentialPair).where(
            UserGroup__ConnectorCredentialPair.user_group_id == group.id
        )
    )
    db_session.execute(delete(UserGroup).where(UserGroup.id == group.id))
    db_session.commit()
    cleanup_cc_pair(db_session, cc_pair)


@pytest.mark.usefixtures("tenant_context")
def test_rename_keeps_cc_pairs_after_sync(
    db_session: Session,
    group_with_cc_pair: tuple[UserGroup, ConnectorCredentialPair],
) -> None:
    # Precondition.
    group, cc_pair = group_with_cc_pair

    # Under test: rename, then the sync's completion step.
    renamed = rename_user_group(
        db_session, user_group_id=group.id, new_name=f"{group.name}-renamed"
    )
    mark_user_group_as_synced(db_session, renamed)

    # Postcondition.
    rows = db_session.scalars(
        select(UserGroup__ConnectorCredentialPair).where(
            UserGroup__ConnectorCredentialPair.user_group_id == group.id
        )
    ).all()
    assert [(row.cc_pair_id, row.is_current) for row in rows] == [(cc_pair.id, True)]
