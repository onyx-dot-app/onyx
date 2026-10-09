"""One group per team the token can see, named by the team id the doc sync
writes on its issues, plus the workspace members group a public team's
issues also carry. A restricted sub-team's issues name the parent team as
well, so its own group holds only the people added to it, guests included."""

from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.linear.connector import linear_connector
from onyx.connectors.linear.access import workspace_members_group_id
from onyx.connectors.linear.connector import LinearConnector
from onyx.connectors.linear.models import WorkspaceMembers
from onyx.db.models import ConnectorCredentialPair


def linear_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    yield from team_groups(linear_connector(cc_pair))


def team_groups(connector: LinearConnector) -> Generator[ExternalUserGroup, None, None]:
    # Bare ids: the source prefix is added when the groups are stored, which
    # is how they meet the ids the doc sync writes on an issue.
    workspace: WorkspaceMembers = connector.workspace_members()
    yield ExternalUserGroup(
        id=workspace_members_group_id(workspace.organization_id),
        user_emails=sorted(workspace.emails),
    )
    for team in connector.list_teams():
        members: set[str] = connector.team_member_emails(team.id)
        if members:
            yield ExternalUserGroup(id=team.id, user_emails=sorted(members))
