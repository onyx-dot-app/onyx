"""One group per team the token can see, named by the team id the doc sync
writes on its issues, plus the workspace members group a public team's
issues also carry. A restricted sub-team's issues name the parent team as
well, so its own group holds only the people added to it, guests included."""

from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.linear.connector import linear_connector
from onyx.connectors.linear.access import (
    complete_workspace_users,
    member_emails,
    workspace_members_group_id,
)
from onyx.connectors.linear.models import LinearUser, WorkspaceUsers
from onyx.connectors.linear.source_operations import LinearSourceOperations
from onyx.db.models import ConnectorCredentialPair


def linear_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    yield from team_groups(linear_connector(cc_pair).ops)


def team_groups(
    ops: LinearSourceOperations,
) -> Generator[ExternalUserGroup, None, None]:
    workspace: WorkspaceUsers = ops.list_workspace_users()
    users: list[LinearUser] = complete_workspace_users(workspace)
    # Bare ids: the source prefix is added when the groups are stored, which
    # is how they meet the ids the doc sync writes on an issue.
    yield ExternalUserGroup(
        id=workspace_members_group_id(workspace.organization_id),
        user_emails=sorted(member_emails(user for user in users if not user.guest)),
    )
    for team in ops.list_teams():
        members: set[str] = member_emails(ops.list_team_members(team_id=team.id))
        if members:
            yield ExternalUserGroup(id=team.id, user_emails=sorted(members))
