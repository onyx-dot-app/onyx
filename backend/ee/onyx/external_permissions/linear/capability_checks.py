"""Named permission sync checks for Linear. Permission sync needs a workspace
member rather than a guest, since a guest's token lists only the guest's own
teams and cannot name the workspace's members, and a users listing Linear
cuts short would leave people out of the workspace group."""

from ee.onyx.external_permissions.linear.access import complete_workspace_users
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    NothingToCheckError,
)
from onyx.connectors.linear.capability_checks import (
    DOCS_LINK,
    ISSUES_CHECK_ID,
    PROBE_PAGE_SIZE,
    SIGN_IN_CHECK_ID,
    gateway_from_context,
    member_need,
    probe,
    scoped_issue_filter,
)
from onyx.connectors.linear.config import LinearConnectorConfig
from onyx.connectors.linear.models import (
    IssueAccessPage,
    LinearTeam,
    LinearUser,
    LinearViewer,
    WorkspaceUsers,
)

_GUEST_REMEDIATION: str = (
    "Connect as a workspace member who belongs to every private team to index."
)
# One row for the member check of both sync capabilities: the same probe.
_MEMBER_ROW_ID: str = "linear_workspace_member"
_DOC_SYNC_MEMBER_CHECK_ID: str = (
    f"{_MEMBER_ROW_ID}_{CredentialCapability.DOC_PERMISSION_SYNC.value}"
)
_GROUP_SYNC_MEMBER_CHECK_ID: str = (
    f"{_MEMBER_ROW_ID}_{CredentialCapability.EXTERNAL_GROUP_SYNC.value}"
)
_ISSUE_ACCESS_CHECK_ID: str = "linear_issue_access"
_WORKSPACE_USERS_CHECK_ID: str = "linear_workspace_users"
_TEAM_MEMBERS_CHECK_ID: str = "linear_team_members"
# check_id to the checks it runs after. Each capability's checks follow its
# own member check.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    _DOC_SYNC_MEMBER_CHECK_ID: (SIGN_IN_CHECK_ID,),
    _GROUP_SYNC_MEMBER_CHECK_ID: (SIGN_IN_CHECK_ID,),
    _ISSUE_ACCESS_CHECK_ID: (ISSUES_CHECK_ID,),
    _WORKSPACE_USERS_CHECK_ID: (_GROUP_SYNC_MEMBER_CHECK_ID,),
    _TEAM_MEMBERS_CHECK_ID: (_WORKSPACE_USERS_CHECK_ID,),
}


class _LinearSyncCheck(CapabilityCheck[LinearConnectorConfig]):
    def __init__(
        self,
        *,
        capability: CredentialCapability,
        check_id: str,
        display_name: str,
        remediation: str,
        row_id: str | None = None,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            depends_on=_DEPENDS_ON.get(check_id, ()),
            requires_connector_instance=False,
            remediation=remediation,
            docs_link=DOCS_LINK,
            row_id=row_id,
        )


class _WorkspaceMemberCheck(_LinearSyncCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id=f"{_MEMBER_ROW_ID}_{capability.value}",
            display_name="Read account role",
            remediation=_GUEST_REMEDIATION,
            row_id=_MEMBER_ROW_ID,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        viewer: LinearViewer = probe(
            gateway_from_context(context).get_viewer,
            "Linear did not answer for the token.",
            context,
        )
        if viewer.guest:
            raise InsufficientPermissionsError(
                f"The connected Linear user is a guest. {_GUEST_REMEDIATION}",
                summary="Connected user is a guest",
                description=(
                    "A guest's token sees only the guest's own teams and cannot "
                    f"name the workspace's members.\n{member_need(context)}"
                ),
            )
        return CheckOutput(summary="Connected user is a workspace member")


class _IssueAccessCheck(_LinearSyncCheck):
    config_class = LinearConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=_ISSUE_ACCESS_CHECK_ID,
            display_name="Read issue sharing",
            remediation="Grant the credential read access to issues and teams.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        pages = gateway.iterate_issue_access(
            issue_filter=scoped_issue_filter(context), page_size=PROBE_PAGE_SIZE
        )
        failed: str = "The credential cannot read issue access."
        page: IssueAccessPage | None = probe(lambda: next(pages, None), failed, context)
        if page is None or not page.issues:
            # Sample issues FAILS an empty scope; reaching here empty means
            # the issues changed between the two reads.
            raise InconclusiveValidationError(
                "Linear returned no issue in scope, so Onyx cannot read who may "
                "see one.",
                summary="No issue to read sharing of",
                description=(
                    "Linear returned no issue in the selected scope.\nRe-run the "
                    "checks."
                ),
            )
        issue_id: str = page.issues[0].id
        probe(lambda: gateway.get_issue_share(issue_id=issue_id), failed, context)
        return CheckOutput(
            summary=f"Read access of one {page.issues[0].team.key} issue"
        )


class _WorkspaceUsersCheck(_LinearSyncCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id=_WORKSPACE_USERS_CHECK_ID,
            display_name="List workspace users",
            remediation=_GUEST_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        workspace: WorkspaceUsers = probe(
            gateway_from_context(context).list_workspace_users,
            "The credential cannot list the workspace's users.",
            context,
        )
        try:
            complete_workspace_users(workspace)
        except ConnectorValidationError as e:
            raise ConnectorValidationError(
                e.message,
                summary=(
                    f"Listed {len(workspace.users)} of {workspace.user_count} users"
                ),
                description=(
                    "The connected user cannot see every workspace user.\n"
                    f"{member_need(context)}"
                ),
            ) from e
        if workspace.user_count == 1:
            return CheckOutput(summary="Listed the only workspace user")
        return CheckOutput(summary=f"Listed all {workspace.user_count} workspace users")


class _TeamMembersCheck(_LinearSyncCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id=_TEAM_MEMBERS_CHECK_ID,
            display_name="List team members",
            remediation="Grant the credential read access to teams.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        failed: str = "The credential cannot read team memberships."
        teams: list[LinearTeam] = probe(gateway.list_teams, failed, context)
        if not teams:
            raise NothingToCheckError(
                "The connected Linear user sees no team, so there is no team "
                "membership to read.",
                summary="No teams to test",
                description="The connected user sees no team.",
            )
        team: LinearTeam = teams[0]
        members: list[LinearUser] = probe(
            lambda: gateway.list_team_members(team_id=team.id), failed, context
        )
        noun: str = "member" if len(members) == 1 else "members"
        return CheckOutput(summary=f"Read {len(members)} {noun} of team {team.key}")


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
