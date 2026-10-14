"""Each Linear permission sync check maps the gateway's answer onto a
validation outcome: a guest token, a users listing cut short, or an
unreadable listing."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from ee.onyx.external_permissions.linear.capability_checks import (
    build_linear_doc_permission_sync_checks,
    build_linear_group_sync_checks,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
)
from onyx.connectors.linear.models import (
    IssueAccess,
    IssueAccessPage,
    IssueShare,
    LinearTeam,
    LinearViewer,
    WorkspaceUsers,
)
from onyx.connectors.linear.source_operations import LinearSourceOperations


def _check(checks: list[CapabilityCheck], check_id: str) -> CapabilityCheck:
    return next(check for check in checks if check.check_id == check_id)


def _context(
    ops: MagicMock, config: dict[str, Any] | None = None
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.LINEAR,
        credential_json={},
        connector_specific_config=config,
        source_operations=ops,
    )


def _ops() -> MagicMock:
    ops = create_autospec(LinearSourceOperations, instance=True)
    ops.get_viewer.return_value = LinearViewer(guest=False)
    return ops


@pytest.mark.parametrize(
    "checks, capability",
    [
        (
            build_linear_doc_permission_sync_checks(),
            CredentialCapability.DOC_PERMISSION_SYNC,
        ),
        (build_linear_group_sync_checks(), CredentialCapability.EXTERNAL_GROUP_SYNC),
    ],
    ids=["doc sync", "group sync"],
)
def test_a_guest_token_fails_both_permission_sync_capabilities(
    checks: list[CapabilityCheck], capability: CredentialCapability
) -> None:
    ops = _ops()
    ops.get_viewer.return_value = LinearViewer(guest=True)
    check = _check(checks, f"linear_workspace_member_{capability.value}")
    assert check.capability is capability

    with pytest.raises(InsufficientPermissionsError, match="guest"):
        check.run(_context(ops))


def test_the_issue_access_check_reads_a_page_and_one_share() -> None:
    ops = _ops()
    team = LinearTeam(id="t", key="T", visibility="public")
    share = IssueShare(parent_id=None, inherits=False, emails=set())
    ops.iterate_issue_access.return_value = iter(
        [
            IssueAccessPage(
                organization_id="o",
                issues=[IssueAccess(id="i1", team=team, share=share)],
            )
        ]
    )
    check = _check(build_linear_doc_permission_sync_checks(), "linear_issue_access")

    check.run(_context(ops, {}))

    ops.get_issue_share.assert_called_once_with(issue_id="i1")


def test_the_workspace_users_check_fails_a_listing_linear_cut_short() -> None:
    ops = _ops()
    ops.list_workspace_users.return_value = WorkspaceUsers(
        organization_id="o", user_count=5, users=[]
    )
    check = _check(build_linear_group_sync_checks(), "linear_workspace_users")

    with pytest.raises(ConnectorValidationError, match="listed 0 of the 5 users"):
        check.run(_context(ops))


def test_the_team_members_check_reads_the_first_teams_members() -> None:
    ops = _ops()
    ops.list_teams.return_value = [LinearTeam(id="t", key="T", visibility="public")]
    check = _check(build_linear_group_sync_checks(), "linear_team_members")

    check.run(_context(ops))

    ops.list_team_members.assert_called_once_with(team_id="t")
