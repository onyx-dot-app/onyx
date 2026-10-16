"""Each YouTrack permission sync check maps the gateway's answer onto a
validation outcome: a token user without Override Visibility Restrictions, or
a users listing without emails. The group sync runs them before it yields
any group."""

from unittest.mock import MagicMock, create_autospec, patch

import pytest

from ee.onyx.external_permissions.youtrack import group_sync
from ee.onyx.external_permissions.youtrack.capability_checks import (
    build_youtrack_doc_permission_sync_checks,
    build_youtrack_group_sync_checks,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.youtrack.models import (
    YouTrackAssignedRole,
    YouTrackProject,
    YouTrackRole,
    YouTrackUser,
)
from onyx.connectors.youtrack.source_operations import YouTrackSourceOperations

_CONFIG = {"base_url": "https://example.youtrack.cloud"}
_ME = YouTrackUser(id="1-1", email="me@example.com")


def _check(checks: list[CapabilityCheck], prefix: str) -> CapabilityCheck:
    return next(check for check in checks if check.check_id.startswith(prefix))


def _context(ops: MagicMock) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.YOUTRACK,
        credential_json={},
        connector_specific_config=_CONFIG,
        source_operations=ops,
    )


def _ops(*permissions: str) -> MagicMock:
    ops = create_autospec(YouTrackSourceOperations, instance=True)
    ops.get_me.return_value = _ME
    ops.list_projects.return_value = [
        YouTrackProject.model_validate({"id": "0-1", "shortName": "ABC", "name": "A"})
    ]
    ops.list_roles.return_value = [
        YouTrackRole.model_validate(
            {
                "id": "r",
                "permissions": [{"id": f"JetBrains.YouTrack.{p}"} for p in permissions],
            }
        )
    ]
    ops.list_assigned_roles.return_value = [
        YouTrackAssignedRole.model_validate(
            {
                "role": {"id": "r"},
                "holder": {"$type": "User", "id": "1-1"},
                "scope": {"$type": "GlobalScope"},
            }
        )
    ]
    ops.list_organizations.return_value = []
    return ops


@pytest.mark.parametrize(
    "checks",
    [build_youtrack_doc_permission_sync_checks(), build_youtrack_group_sync_checks()],
    ids=["doc sync", "group sync"],
)
def test_a_token_user_without_override_fails_and_names_the_project(
    checks: list[CapabilityCheck],
) -> None:
    check = _check(checks, "youtrack_reads_restricted")

    with pytest.raises(InsufficientPermissionsError, match="ABC"):
        check.run(_context(_ops("READ_ISSUE", "READ_COMMENT")))
    check.run(_context(_ops("READ_ISSUE", "READ_COMMENT", "READ_HIDDEN_STUFF")))


def test_a_users_listing_without_any_email_fails() -> None:
    check = _check(build_youtrack_group_sync_checks(), "youtrack_user_emails")
    ops = _ops()
    ops.list_users.return_value = [
        YouTrackUser(id="1-1"),
        YouTrackUser(id="1-2", email="banned@example.com", banned=True),
    ]

    with pytest.raises(InsufficientPermissionsError, match="emails"):
        check.run(_context(ops))

    ops.list_users.return_value = [YouTrackUser(id="1-1"), _ME]
    check.run(_context(ops))


def test_group_sync_validates_the_token_before_yielding_any_group() -> None:
    connector = MagicMock()
    connector.validate_perm_sync.side_effect = InsufficientPermissionsError("no")

    with (
        patch.object(group_sync, "youtrack_connector", return_value=connector),
        patch.object(group_sync, "project_groups") as project_groups,
    ):
        with pytest.raises(InsufficientPermissionsError):
            next(group_sync.youtrack_group_sync("tenant", MagicMock()))

    project_groups.assert_not_called()
