"""Audit coverage for the SCIM group write surface.

The delta guard is the whole risk. IdPs re-``PUT`` a group's full state on routine
reconciliation, so an ungated emit would fire on every no-op sync and drown the
real changes. A dedup window would be worse than a guard, because it would also
hide a real change that landed inside the window.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.server.scim.api import create_group, delete_group, replace_group
from ee.onyx.server.scim.models import (
    ScimGroupMember,
    ScimGroupResource,
)
from ee.onyx.server.scim.providers.base import get_default_provider
from onyx.db.models import ScimToken, User, UserGroup
from onyx.utils.audit import AuditAction
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_EMIT = "ee.onyx.server.scim.api.emit_audit_event"


def _resource(name: str, *members: User) -> ScimGroupResource:
    return ScimGroupResource(
        displayName=name,
        members=[ScimGroupMember(value=str(m.id)) for m in members],
    )


def _create(db_session: Session, token: ScimToken, resource: ScimGroupResource) -> int:
    """The route returns a serialized JSON response, so read the row back by name."""
    create_group(resource, token, get_default_provider(), db_session)
    group = db_session.scalar(
        select(UserGroup).where(UserGroup.name == resource.displayName)
    )
    assert group is not None
    return group.id


def _calls(emit: MagicMock, action: AuditAction) -> list[dict[str, Any]]:
    return [
        call.kwargs["extra"] for call in emit.call_args_list if call.args[0] is action
    ]


@pytest.fixture
def token(db_session: Session) -> ScimToken:
    scim_token = ScimToken(
        name="okta-prod",
        hashed_token=uuid4().hex,
        token_display="onyx_scim_****abcd",
        created_by_id=create_test_user(db_session, "scim_audit_owner").id,
    )
    db_session.add(scim_token)
    db_session.commit()
    return scim_token


@pytest.fixture
def member_factory(
    db_session: Session,
) -> Callable[[], User]:
    def _create() -> User:
        return create_test_user(
            db_session, "scim_audit_member", assign_default_group=False
        )

    return _create


def test_create_group_records_the_name_and_actor(
    db_session: Session, token: ScimToken, member_factory: Callable[[], User]
) -> None:
    member = member_factory()
    name = f"scim-audit-{uuid4().hex[:12]}"

    with patch(_EMIT) as emit:
        create_group(_resource(name, member), token, get_default_provider(), db_session)

    calls = [
        c for c in emit.call_args_list if c.args[0] is AuditAction.USER_GROUP_CREATE
    ]
    assert len(calls) == 1
    extra = calls[0].kwargs["extra"]
    assert extra["name"] == name
    assert extra["user_ids"] == [str(member.id)]
    assert extra["source"] == "scim"
    assert extra["scim_token_name"] == "okta-prod"
    actor = calls[0].kwargs["actor"]
    assert actor.api_key_id == f"scim_token:{token.id}"
    assert actor.auth_type == "scim"

    delete_test_user(db_session, member)


def test_replace_group_with_no_changes_emits_nothing(
    db_session: Session, token: ScimToken, member_factory: Callable[[], User]
) -> None:
    """The reconciliation case: an IdP re-PUTs the same state on a schedule."""
    member = member_factory()
    name = f"scim-audit-{uuid4().hex[:12]}"
    group_id = _create(db_session, token, _resource(name, member))

    with patch(_EMIT) as emit:
        replace_group(
            str(group_id),
            _resource(name, member),
            token,
            get_default_provider(),
            db_session,
        )

    assert emit.call_args_list == []
    delete_test_user(db_session, member)


def test_replace_group_reports_the_rename_and_the_membership_delta(
    db_session: Session, token: ScimToken, member_factory: Callable[[], User]
) -> None:
    """One PUT can do both, which is what an IdP actually sends. The rename must
    report the pre-rename name — update_group renames in place, so a naive read
    would report the new name twice."""
    kept, dropped, joined = member_factory(), member_factory(), member_factory()
    original = f"scim-audit-{uuid4().hex[:12]}"
    renamed = f"scim-audit-{uuid4().hex[:12]}"
    group_id = _create(db_session, token, _resource(original, kept, dropped))

    with patch(_EMIT) as emit:
        replace_group(
            str(group_id),
            _resource(renamed, kept, joined),
            token,
            get_default_provider(),
            db_session,
        )

    renames = _calls(emit, AuditAction.USER_GROUP_RENAME)
    assert len(renames) == 1
    assert renames[0]["previous_name"] == original
    assert renames[0]["new_name"] == renamed

    changes = _calls(emit, AuditAction.USER_GROUP_CHANGE)
    assert len(changes) == 1
    assert changes[0]["added_user_ids"] == [str(joined.id)]
    assert changes[0]["removed_user_ids"] == [str(dropped.id)]
    assert changes[0]["source"] == "scim"

    delete_test_user(db_session, kept, dropped, joined)


def test_delete_group_records_who_lost_access(
    db_session: Session, token: ScimToken, member_factory: Callable[[], User]
) -> None:
    member = member_factory()
    name = f"scim-audit-{uuid4().hex[:12]}"
    group_id = _create(db_session, token, _resource(name, member))

    with patch(_EMIT) as emit:
        delete_group(str(group_id), token, db_session)

    calls = [
        c for c in emit.call_args_list if c.args[0] is AuditAction.USER_GROUP_DELETE
    ]
    assert len(calls) == 1
    # The row is gone by the time the emit runs, so the id must be captured first.
    assert calls[0].kwargs["resource_id"] == group_id
    extra = calls[0].kwargs["extra"]
    assert extra["name"] == name
    assert extra["member_ids"] == [str(member.id)]

    delete_test_user(db_session, member)
