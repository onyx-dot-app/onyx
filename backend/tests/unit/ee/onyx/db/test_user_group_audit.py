"""Unit tests for user.group_change audit emission from update_user_group.

The emit is guarded on an actual membership delta, so a pure cc_pair update
must emit nothing while an add/remove of users must emit exactly one event.
"""

import json
import logging
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from ee.onyx.db.user_group import update_user_group
from ee.onyx.server.user_group.models import UserGroupUpdate
from onyx.db.models import UserRole


def _audit_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name.startswith("onyx.audit")
    ]


def _make_db_session(
    existing_user_ids: list[Any], existing_cc_pair_ids: list[int]
) -> MagicMock:
    group = MagicMock()
    group.users = [MagicMock(id=uid) for uid in existing_user_ids]
    group.cc_pairs = [MagicMock(id=cid) for cid in existing_cc_pair_ids]
    db_session = MagicMock()
    db_session.scalar.return_value = group
    # No users are removed in these cases, so the removed-users lookup is empty.
    db_session.scalars.return_value.unique.return_value = []
    return db_session


@patch("ee.onyx.db.user_group.recompute_user_permissions__no_commit")
@patch("ee.onyx.db.user_group._add_user__user_group_relationships__no_commit")
@patch("ee.onyx.db.user_group.fetch_user_by_id", return_value=MagicMock())
@patch("ee.onyx.db.user_group._check_user_group_is_modifiable")
def test_update_user_group_emits_on_membership_change(
    _modifiable: MagicMock,
    _fetch: MagicMock,
    _add_rel: MagicMock,
    _recompute: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    existing = uuid4()
    added = uuid4()
    db_session = _make_db_session([existing], [10])
    admin = MagicMock(id="admin-1", email="admin@example.com", role=UserRole.ADMIN)

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        update_user_group(
            db_session=db_session,
            user=admin,
            user_group_id=7,
            user_group_update=UserGroupUpdate(
                user_ids=[existing, added], cc_pair_ids=[10]
            ),
        )

    events = _audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "user.group_change"
    assert events[0]["outcome"] == "success"
    assert events[0]["resource_id"] == "7"
    assert events[0]["actor"]["email"] == "admin@example.com"
    assert events[0]["extra"]["added_user_ids"] == [str(added)]
    assert events[0]["extra"]["removed_user_ids"] == []


@patch("ee.onyx.db.user_group.recompute_user_permissions__no_commit")
@patch("ee.onyx.db.user_group._add_user_group__cc_pair_relationships__no_commit")
@patch(
    "ee.onyx.db.user_group._mark_user_group__cc_pair_relationships_outdated__no_commit"
)
@patch("ee.onyx.db.user_group._check_user_group_is_modifiable")
def test_update_user_group_cc_pair_only_emits_nothing(
    _modifiable: MagicMock,
    _mark: MagicMock,
    _add_cc: MagicMock,
    _recompute: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    existing = uuid4()
    db_session = _make_db_session([existing], [10])
    admin = MagicMock(id="admin-1", email="admin@example.com", role=UserRole.ADMIN)

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        update_user_group(
            db_session=db_session,
            user=admin,
            user_group_id=7,
            # Same members, different cc_pairs -> no membership delta.
            user_group_update=UserGroupUpdate(
                user_ids=[existing], cc_pair_ids=[10, 11]
            ),
        )

    assert _audit_events(caplog) == []
