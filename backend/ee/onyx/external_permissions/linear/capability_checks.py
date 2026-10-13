"""Named permission sync checks for Linear. Permission sync needs a workspace
member rather than a guest, since a guest's token lists only the guest's own
teams and cannot name the workspace's members, and a users listing Linear
cuts short would leave people out of the workspace group."""

from ee.onyx.external_permissions.linear.access import complete_workspace_users
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.linear.capability_checks import (
    DOCS_LINK,
    PROBE_PAGE_SIZE,
    gateway_from_context,
    probe,
    scoped_issue_filter,
)
from onyx.connectors.linear.config import LinearConnectorConfig
from onyx.connectors.linear.models import LinearViewer, WorkspaceUsers

_GUEST_REMEDIATION: str = (
    "Connect as a workspace member who belongs to every private team to index."
)


class _WorkspaceMemberCheck(CapabilityCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id=f"linear_workspace_member_{capability.value}",
            display_name="The connected user is a workspace member",
            requires_connector_instance=False,
            remediation=_GUEST_REMEDIATION,
            docs_link=DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        viewer: LinearViewer = probe(
            gateway_from_context(context).get_viewer,
            "Linear did not answer for the token.",
        )
        if viewer.guest:
            raise InsufficientPermissionsError(
                f"The connected Linear user is a guest. {_GUEST_REMEDIATION}"
            )


class _IssueAccessCheck(CapabilityCheck[LinearConnectorConfig]):
    config_class = LinearConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="linear_issue_access",
            display_name="Issue teams and sharing are readable",
            requires_connector_instance=False,
            remediation="Grant the credential read access to issues and teams.",
            docs_link=DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = gateway_from_context(context)
        pages = gateway.iterate_issue_access(
            issue_filter=scoped_issue_filter(context), page_size=PROBE_PAGE_SIZE
        )

        def read_first_issue_and_its_share() -> None:
            page = next(pages, None)
            if page is None or not page.issues:
                return
            gateway.get_issue_share(issue_id=page.issues[0].id)

        probe(
            read_first_issue_and_its_share, "The credential cannot read issue access."
        )


class _WorkspaceUsersCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="linear_workspace_users",
            display_name="Workspace users are listable in full",
            requires_connector_instance=False,
            remediation=_GUEST_REMEDIATION,
            docs_link=DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        workspace: WorkspaceUsers = probe(
            gateway_from_context(context).list_workspace_users,
            "The credential cannot list the workspace's users.",
        )
        complete_workspace_users(workspace)


class _TeamMembersCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="linear_team_members",
            display_name="Team memberships are readable",
            requires_connector_instance=False,
            remediation="Grant the credential read access to teams.",
            docs_link=DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = gateway_from_context(context)

        def read_first_teams_members() -> None:
            teams = gateway.list_teams()
            if teams:
                gateway.list_team_members(team_id=teams[0].id)

        probe(read_first_teams_members, "The credential cannot read team memberships.")


def build_linear_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _WorkspaceMemberCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _IssueAccessCheck(),
    ]


def build_linear_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _WorkspaceMemberCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _WorkspaceUsersCheck(),
        _TeamMembersCheck(),
    ]
