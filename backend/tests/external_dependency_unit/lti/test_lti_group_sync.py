"""External-dependency unit tests for Canvas (LTI) course roster → UserGroup sync.

Runs against a real Postgres. The NRPS HTTP layer is exercised only via its pure
parsing helpers; the DB membership-diff logic is tested directly against the EE
user_group helpers.

NOTE: these run against a shared DB with no per-test teardown, so every course
context id and title is suffixed with a unique token to avoid colliding with
rows left by previous runs (UserGroup.name and lti_context_id are both unique).
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.db.user_group import add_user_to_lti_group_by_email
from ee.onyx.db.user_group import ensure_lti_user_group
from ee.onyx.db.user_group import fetch_lti_managed_user_groups
from ee.onyx.db.user_group import fetch_user_group
from ee.onyx.db.user_group import fetch_user_group_by_lti_context_id
from ee.onyx.db.user_group import sync_lti_group_membership_by_emails
from onyx.db.models import UserGroup
from onyx.server.lti.nrps import NrpsRoster
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import global_version
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture(autouse=True)
def _enable_ee() -> Generator[None, None, None]:
    prev = global_version._is_ee
    global_version.set_ee()
    fetch_versioned_implementation.cache_clear()
    yield
    global_version._is_ee = prev
    fetch_versioned_implementation.cache_clear()


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _mark_group_up_to_date(db_session: Session, user_group_id: int) -> None:
    """Simulate a completed Vespa sync so the group becomes modifiable.

    insert_user_group leaves is_up_to_date=False when a vector DB is enabled,
    which would otherwise block membership edits.
    """
    group = fetch_user_group(db_session, user_group_id)
    assert group is not None
    group.is_up_to_date = True
    db_session.commit()


def _member_emails(db_session: Session, user_group_id: int) -> set[str]:
    # Sessions use expire_on_commit=False, so the cached `users` relationship can
    # be stale after a membership change committed in another helper. Expire to
    # force a fresh read of the current membership.
    db_session.expire_all()
    group = fetch_user_group(db_session, user_group_id)
    assert group is not None
    return {user.email.lower() for user in group.users}


def test_ensure_creates_canvas_managed_group(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    context_id = _unique("ctx_create")
    title = _unique("BIO 101")
    group = ensure_lti_user_group(
        db_session=db_session,
        lti_context_id=context_id,
        course_title=title,
        nrps_url="https://canvas.example.edu/api/lti/courses/1/names_and_roles",
    )

    assert group.lti_context_id == context_id
    assert group.name == title
    assert group.lti_nrps_url is not None

    # It shows up in the Canvas-managed listing.
    managed = fetch_lti_managed_user_groups(db_session)
    assert any(g.lti_context_id == context_id for g in managed)

    # Idempotent: a second ensure returns the same group, no duplicate.
    again = ensure_lti_user_group(
        db_session=db_session,
        lti_context_id=context_id,
        course_title=title,
        nrps_url=None,
    )
    assert again.id == group.id


def test_launch_adds_user_as_sole_member(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    context_id = _unique("ctx_launch_sole")
    student = create_test_user(db_session, "lti_student")

    add_user_to_lti_group_by_email(
        db_session=db_session,
        lti_context_id=context_id,
        course_title=_unique("CHEM 200"),
        nrps_url="https://canvas.example.edu/nrps/2",
        user_email=student.email,
    )

    group = fetch_user_group_by_lti_context_id(db_session, context_id)
    assert group is not None
    assert _member_emails(db_session, group.id) == {student.email.lower()}


def test_second_launch_joins_existing_group(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    context_id = _unique("ctx_launch_two")
    title = _unique("HIST 101")
    first = create_test_user(db_session, "lti_first")
    second = create_test_user(db_session, "lti_second")

    add_user_to_lti_group_by_email(
        db_session=db_session,
        lti_context_id=context_id,
        course_title=title,
        nrps_url=None,
        user_email=first.email,
    )
    group = fetch_user_group_by_lti_context_id(db_session, context_id)
    assert group is not None
    _mark_group_up_to_date(db_session, group.id)

    add_user_to_lti_group_by_email(
        db_session=db_session,
        lti_context_id=context_id,
        course_title=title,
        nrps_url=None,
        user_email=second.email,
    )

    # Same group, both members, no duplicate group created.
    groups_for_context = db_session.scalars(
        select(UserGroup).where(UserGroup.lti_context_id == context_id)
    ).all()
    assert len(groups_for_context) == 1
    assert _member_emails(db_session, group.id) == {
        first.email.lower(),
        second.email.lower(),
    }


def test_sync_adds_and_skips_unknown_emails(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    context_id = _unique("ctx_sync_add")
    enrolled = create_test_user(db_session, "lti_enrolled")

    group = ensure_lti_user_group(
        db_session=db_session,
        lti_context_id=context_id,
        course_title=_unique("MATH 300"),
        nrps_url="https://canvas.example.edu/nrps/3",
    )
    _mark_group_up_to_date(db_session, group.id)

    # Roster references an Onyx user + an email with no Onyx account (skipped).
    sync_lti_group_membership_by_emails(
        db_session=db_session,
        user_group_id=group.id,
        emails={enrolled.email.lower(), "ghost@example.edu"},
    )

    assert _member_emails(db_session, group.id) == {enrolled.email.lower()}


def test_sync_removes_dropped_student(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    context_id = _unique("ctx_sync_remove")
    stays = create_test_user(db_session, "lti_stays")
    leaves = create_test_user(db_session, "lti_leaves")

    group = ensure_lti_user_group(
        db_session=db_session,
        lti_context_id=context_id,
        course_title=_unique("PHYS 100"),
        nrps_url="https://canvas.example.edu/nrps/4",
    )
    _mark_group_up_to_date(db_session, group.id)

    sync_lti_group_membership_by_emails(
        db_session=db_session,
        user_group_id=group.id,
        emails={stays.email.lower(), leaves.email.lower()},
    )
    assert _member_emails(db_session, group.id) == {
        stays.email.lower(),
        leaves.email.lower(),
    }

    # `leaves` drops the course -> next sync removes them.
    sync_lti_group_membership_by_emails(
        db_session=db_session,
        user_group_id=group.id,
        emails={stays.email.lower()},
    )
    assert _member_emails(db_session, group.id) == {stays.email.lower()}


def test_ensure_overwrites_renamed_group(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    context_id = _unique("ctx_rename")
    title = _unique("Original Title")
    group = ensure_lti_user_group(
        db_session=db_session,
        lti_context_id=context_id,
        course_title=title,
        nrps_url=None,
    )

    # Admin renames it by hand.
    group.name = _unique("Admin Renamed This")
    db_session.commit()

    # Canvas is the source of truth -> next ensure overwrites the name back.
    refreshed = ensure_lti_user_group(
        db_session=db_session,
        lti_context_id=context_id,
        course_title=title,
        nrps_url=None,
    )
    assert refreshed.id == group.id
    assert refreshed.name == title


def test_nrps_roster_active_member_filter() -> None:
    roster = NrpsRoster.model_validate(
        {
            "context_title": "BIO 101",
            "members": [
                {"email": "Active@Example.edu", "status": "Active", "roles": []},
                {"email": "inactive@example.edu", "status": "Inactive", "roles": []},
                {"email": "deleted@example.edu", "status": "Deleted", "roles": []},
                {"name": "No Email", "status": "Active", "roles": []},
            ],
        }
    )
    # Only active members that have an email survive the filter.
    active = {e.lower() for e in roster.active_member_emails()}
    assert active == {"active@example.edu"}
    assert roster.context_title == "BIO 101"
