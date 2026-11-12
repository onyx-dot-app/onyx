"""A group membership change pushes skills to the users who joined or left
(R19): group shares and group install settings follow membership. Covers the
group API and SCIM sync."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ee.onyx.server.scim.api import patch_group, replace_group
from ee.onyx.server.scim.models import (
    ScimGroupMember,
    ScimGroupResource,
    ScimPatchOperation,
    ScimPatchRequest,
)
from ee.onyx.server.scim.providers.base import get_default_provider
from ee.onyx.server.user_group.api import (
    add_users,
    create_user_group,
    delete_user_group,
    patch_user_group,
)
from ee.onyx.server.user_group.models import (
    AddUsersToUserGroupRequest,
    UserGroupCreate,
    UserGroupUpdate,
)
from onyx.db.models import ScimToken, User, UserGroup
from tests.external_dependency_unit.conftest import create_test_user

pytestmark = pytest.mark.usefixtures("tenant_context")

_PUSH = "onyx.skills.push.push_skills_for_users"


@pytest.fixture
def pushes(monkeypatch: pytest.MonkeyPatch) -> list[set[UUID]]:
    calls: list[set[UUID]] = []
    monkeypatch.setattr(_PUSH, lambda user_ids, _db: calls.append(set(user_ids)))
    return calls


def _member(db_session: Session) -> User:
    return create_test_user(db_session, "membership_push")


def _group_id(db_session: Session, name: str) -> int:
    group_id = db_session.scalar(select(UserGroup.id).where(UserGroup.name == name))
    assert group_id is not None
    return group_id


def test_group_api_membership_changes_push(
    db_session: Session, pushes: list[set[UUID]]
) -> None:
    admin = create_test_user(db_session, "membership_push_admin", is_admin=True)
    first, second, third = _member(db_session), _member(db_session), _member(db_session)
    name = f"push-{uuid4().hex[:12]}"

    create_user_group(
        UserGroupCreate(name=name, user_ids=[first.id, second.id], cc_pair_ids=[]),
        user=admin,
        db_session=db_session,
    )
    group_id = _group_id(db_session, name)
    db_session.execute(
        update(UserGroup).where(UserGroup.id == group_id).values(is_up_to_date=True)
    )
    db_session.commit()
    assert pushes[-1] == {first.id, second.id}

    patch_user_group(
        group_id,
        UserGroupUpdate(user_ids=[first.id, third.id]),
        user=admin,
        db_session=db_session,
    )
    assert pushes[-1] == {second.id, third.id}

    add_users(
        group_id,
        AddUsersToUserGroupRequest(user_ids=[second.id]),
        user=admin,
        db_session=db_session,
    )
    assert pushes[-1] == {second.id}

    delete_user_group(group_id, user=admin, db_session=db_session)
    assert pushes[-1] == {first.id, second.id, third.id}


def test_scim_membership_changes_push(
    db_session: Session, pushes: list[set[UUID]]
) -> None:
    token = ScimToken(
        name="membership-push",
        hashed_token=uuid4().hex,
        token_display="onyx_scim_****push",
        created_by_id=create_test_user(db_session, "membership_push_owner").id,
    )
    db_session.add(token)
    db_session.commit()
    first, second = _member(db_session), _member(db_session)
    name = f"push-scim-{uuid4().hex[:12]}"
    group = UserGroup(name=name, is_up_to_date=True)
    db_session.add(group)
    db_session.commit()
    provider = get_default_provider()

    replace_group(
        str(group.id),
        ScimGroupResource(
            displayName=name, members=[ScimGroupMember(value=str(first.id))]
        ),
        token,
        provider,
        db_session,
    )
    assert pushes[-1] == {first.id}

    patch_group(
        str(group.id),
        ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op="add",
                    path="members",
                    value=[{"value": str(second.id)}],
                ),
                ScimPatchOperation(op="remove", path=f'members[value eq "{first.id}"]'),
            ]
        ),
        token,
        provider,
        db_session,
    )
    assert pushes[-1] == {first.id, second.id}
