"""The access rule of an integration (``onyx.db.integration_access``), on
real Postgres rows."""

from collections.abc import Generator
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.auth.users import get_anonymous_user
from onyx.db.enums import PluginInstallationPolicy, SkillSharePermission
from onyx.db.integration_access import (
    UserIntegrationState,
    accessible_integration_ids,
    load_user_integration_states,
    user_can_use_integration,
)
from onyx.db.models import (
    Integration,
    Integration__User,
    Integration__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
    UserIntegrationPreference,
)
from onyx.db.users import delete_user_from_db__no_commit
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_group,
)
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    make_mcp_integration,
)

NOT_AVAILABLE = PluginInstallationPolicy.NOT_AVAILABLE
AVAILABLE = PluginInstallationPolicy.AVAILABLE
DEFAULT = PluginInstallationPolicy.DEFAULT
REQUIRED = PluginInstallationPolicy.REQUIRED


@pytest.fixture
def groups(db_session: Session) -> Generator[list[UserGroup], None, None]:
    """Two groups, deleted after the test."""
    made = [make_group(db_session), make_group(db_session)]
    db_session.commit()
    try:
        yield made
    finally:
        db_session.rollback()
        group_ids = [group.id for group in made]
        db_session.execute(
            delete(User__UserGroup).where(User__UserGroup.user_group_id.in_(group_ids))
        )
        db_session.execute(delete(UserGroup).where(UserGroup.id.in_(group_ids)))
        db_session.commit()


def _integration(
    db_session: Session,
    *,
    owner: User | None = None,
    policy: PluginInstallationPolicy = NOT_AVAILABLE,
    enabled: bool = True,
) -> Integration:
    integration, _ = make_mcp_integration(db_session)
    integration.owner_user_id = owner.id if owner is not None else None
    integration.installation_policy = policy
    integration.enabled = enabled
    db_session.commit()
    return integration


def _share_with_user(db_session: Session, integration: Integration, user: User) -> None:
    db_session.add(Integration__User(integration_id=integration.id, user_id=user.id))
    db_session.commit()


def _group_row(
    db_session: Session,
    integration: Integration,
    group: UserGroup,
    *,
    shared: bool = False,
    policy: PluginInstallationPolicy | None = None,
) -> None:
    db_session.add(
        Integration__UserGroup(
            integration_id=integration.id,
            user_group_id=group.id,
            permission=SkillSharePermission.VIEWER if shared else None,
            installation_policy=policy,
        )
    )
    db_session.commit()


def _choose(
    db_session: Session, integration: Integration, user: User, enabled: bool
) -> None:
    db_session.add(
        UserIntegrationPreference(
            user_id=user.id, integration_id=integration.id, enabled=enabled
        )
    )
    db_session.commit()


def _state(
    db_session: Session, integration: Integration, user_id: UUID
) -> UserIntegrationState | None:
    states = load_user_integration_states([user_id], db_session, [integration.id])
    return states[0] if states else None


def _has_access(db_session: Session, integration: Integration, user: User) -> bool:
    """Each read of the rule gives the same answer."""
    in_states = _state(db_session, integration, user.id) is not None
    listed = integration.id in set(
        db_session.scalars(
            select(Integration.id).where(
                Integration.id.in_(accessible_integration_ids(user.id))
            )
        )
    )
    direct = user_can_use_integration(db_session, integration.id, user.id)
    assert in_states == listed == direct
    return in_states


def test_private_integration_is_for_its_owner_and_its_shares(
    db_session: Session, groups: list[UserGroup]
) -> None:
    owner = create_test_user(db_session, "access_owner")
    shared = create_test_user(db_session, "access_shared")
    member = create_test_user(db_session, "access_member")
    other = create_test_user(db_session, "access_other")
    add_user_to_group(db_session, member, groups[0])
    integration = _integration(db_session, owner=owner)
    _share_with_user(db_session, integration, shared)
    _group_row(db_session, integration, groups[0], shared=True)

    assert not _has_access(db_session, integration, other)
    for user, is_owner in ((owner, True), (shared, False), (member, False)):
        assert _has_access(db_session, integration, user)
        state = _state(db_session, integration, user.id)
        assert state is not None
        # The owner and a share get at least Available, which is off until
        # the user turns it on.
        assert state.installation_policy == AVAILABLE
        assert state.is_owner is is_owner
        assert not state.for_everyone
        assert (state.choice, state.turned_on, state.on) == (None, False, False)


def test_group_row_with_no_permission_gives_only_its_setting(
    db_session: Session, groups: list[UserGroup]
) -> None:
    member = create_test_user(db_session, "access_setting_member")
    add_user_to_group(db_session, member, groups[0])
    hidden = _integration(db_session)
    _group_row(db_session, hidden, groups[0], policy=NOT_AVAILABLE)
    opened = _integration(db_session)
    _group_row(db_session, opened, groups[0], policy=DEFAULT)

    assert not _has_access(db_session, hidden, member)
    state = _state(db_session, opened, member.id)
    assert state is not None
    assert (state.installation_policy, state.for_everyone) == (DEFAULT, False)
    assert state.on


def test_most_open_setting_of_the_groups_wins(
    db_session: Session, groups: list[UserGroup]
) -> None:
    both = create_test_user(db_session, "access_both")
    first_only = create_test_user(db_session, "access_first")
    no_group = create_test_user(db_session, "access_no_group")
    add_user_to_group(db_session, both, groups[0])
    add_user_to_group(db_session, both, groups[1])
    add_user_to_group(db_session, first_only, groups[0])

    integration = _integration(db_session, policy=AVAILABLE)
    _group_row(db_session, integration, groups[0], policy=NOT_AVAILABLE)
    _group_row(db_session, integration, groups[1], policy=REQUIRED)

    # Each group of the user gives its own setting, so the company one does
    # not count for a user whose only group is Not available.
    assert not _has_access(db_session, integration, first_only)
    state = _state(db_session, integration, both.id)
    assert state is not None and state.installation_policy == REQUIRED
    state = _state(db_session, integration, no_group.id)
    assert state is not None and state.installation_policy == AVAILABLE


def test_group_with_no_setting_gives_the_company_setting(
    db_session: Session, groups: list[UserGroup]
) -> None:
    member = create_test_user(db_session, "access_company_member")
    add_user_to_group(db_session, member, groups[0])
    add_user_to_group(db_session, member, groups[1])
    integration = _integration(db_session, policy=DEFAULT)
    _group_row(db_session, integration, groups[0], policy=NOT_AVAILABLE)

    state = _state(db_session, integration, member.id)
    assert state is not None and state.installation_policy == DEFAULT


def test_share_gives_at_least_available(
    db_session: Session, groups: list[UserGroup]
) -> None:
    shared = create_test_user(db_session, "access_floor")
    add_user_to_group(db_session, shared, groups[0])
    hidden = _integration(db_session, policy=AVAILABLE)
    _group_row(db_session, hidden, groups[0], policy=NOT_AVAILABLE)
    _share_with_user(db_session, hidden, shared)
    required = _integration(db_session, policy=REQUIRED)
    _share_with_user(db_session, required, shared)

    state = _state(db_session, hidden, shared.id)
    assert state is not None and state.installation_policy == AVAILABLE
    # The floor does not lower a more open setting.
    state = _state(db_session, required, shared.id)
    assert state is not None and state.installation_policy == REQUIRED


@pytest.mark.parametrize(
    ("policy", "choice", "turned_on"),
    [
        (REQUIRED, None, True),
        (REQUIRED, False, True),
        (DEFAULT, None, True),
        (DEFAULT, False, False),
        (DEFAULT, True, True),
        (AVAILABLE, None, False),
        (AVAILABLE, True, True),
        (AVAILABLE, False, False),
    ],
)
def test_choice_under_each_setting(
    db_session: Session,
    policy: PluginInstallationPolicy,
    choice: bool | None,
    turned_on: bool,
) -> None:
    user = create_test_user(db_session, "access_choice")
    integration = _integration(db_session, policy=policy)
    if choice is not None:
        _choose(db_session, integration, user, choice)

    state = _state(db_session, integration, user.id)
    assert state is not None
    assert state.installation_policy == policy and state.for_everyone
    assert (state.choice, state.turned_on, state.on) == (choice, turned_on, turned_on)


def test_no_access_is_off_and_keeps_the_choice(db_session: Session) -> None:
    user = create_test_user(db_session, "access_kept_choice")
    integration = _integration(db_session)
    _choose(db_session, integration, user, True)

    assert not _has_access(db_session, integration, user)

    integration.installation_policy = AVAILABLE
    db_session.commit()
    state = _state(db_session, integration, user.id)
    assert state is not None and state.choice is True and state.on


def test_turned_off_integration_keeps_access_and_is_not_on(
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "access_turned_off")
    integration = _integration(db_session, policy=REQUIRED, enabled=False)

    assert _has_access(db_session, integration, user)
    state = _state(db_session, integration, user.id)
    assert state is not None
    assert (state.turned_on, state.integration_enabled, state.on) == (
        True,
        False,
        False,
    )


def test_anonymous_user_gets_what_everyone_has(db_session: Session) -> None:
    anonymous = get_anonymous_user()
    owner = create_test_user(db_session, "access_anonymous_owner")
    private = _integration(db_session, owner=owner)
    for_all = _integration(db_session, policy=DEFAULT)

    assert not _has_access(db_session, private, anonymous)
    state = _state(db_session, for_all, anonymous.id)
    assert state is not None and state.for_everyone and state.on


def test_states_of_many_users_in_one_read(db_session: Session) -> None:
    owner = create_test_user(db_session, "access_many_owner")
    other = create_test_user(db_session, "access_many_other")
    private = _integration(db_session, owner=owner)
    for_all = _integration(db_session, policy=AVAILABLE)

    states = load_user_integration_states(
        [owner.id, other.id], db_session, [private.id, for_all.id]
    )

    assert {(state.user_id, state.integration_id) for state in states} == {
        (owner.id, private.id),
        (owner.id, for_all.id),
        (other.id, for_all.id),
    }
    assert load_user_integration_states([], db_session) == []
    assert load_user_integration_states([owner.id], db_session, []) == []


def test_user_delete_leaves_the_integration_with_no_owner(db_session: Session) -> None:
    """A user delete does not stop for a private integration that the user
    owns, as it does for a private skill. The integration stays private, with
    no owner and with its shares. The choice of the user goes."""
    owner = create_test_user(db_session, "access_deleted_owner")
    shared = create_test_user(db_session, "access_deleted_shared")
    integration = _integration(db_session, owner=owner)
    _share_with_user(db_session, integration, shared)
    _choose(db_session, integration, owner, True)
    owner_id = owner.id

    try:
        delete_user_from_db__no_commit(owner, db_session)
        db_session.commit()

        db_session.expire_all()
        assert db_session.get(User, owner_id) is None
        kept = db_session.get(Integration, integration.id)
        assert kept is not None
        assert kept.owner_user_id is None
        assert kept.installation_policy == NOT_AVAILABLE
        assert _has_access(db_session, kept, shared)
        assert (
            db_session.scalar(
                select(UserIntegrationPreference.user_id).where(
                    UserIntegrationPreference.integration_id == integration.id
                )
            )
            is None
        )
    finally:
        delete_integrations(db_session, [integration.id])
