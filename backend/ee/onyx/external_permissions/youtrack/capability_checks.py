"""Named permission sync checks for YouTrack. Both syncs need a token whose
user reads every issue in scope, restricted ones included, or those issues
stay private. They also read role assignments and groups, which YouTrack shows
only to administrators, and the group sync needs users' emails."""

from ee.onyx.external_permissions.youtrack.access import (
    GroupMembers,
    ProjectReaders,
    RoleGrants,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.youtrack.capability_checks import (
    PROBE_PAGE_SIZE,
    REQUIRED_FIELDS,
    config_from_context,
    gateway_from_context,
    probe,
    scoped_issue_query,
)
from onyx.connectors.youtrack.config import YouTrackConnectorConfig
from onyx.connectors.youtrack.connector import active_projects
from onyx.connectors.youtrack.models import YouTrackUser
from onyx.connectors.youtrack.source_operations import YouTrackSourceOperations

_ADMIN_REMEDIATION: str = (
    "Use a permanent token of a System Admin, or of a user with Low-level Admin "
    "Read plus Read Issue, Read Issue Comment and Override Visibility "
    "Restrictions in every project to sync."
)


class _RestrictedIssuesCheck(CapabilityCheck[YouTrackConnectorConfig]):
    config_class = YouTrackConnectorConfig

    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            # One id for both capabilities, so the runner reads roles once.
            check_id="youtrack_reads_restricted",
            display_name="The token's user reads every issue, restricted ones too",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            remediation=_ADMIN_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: YouTrackSourceOperations = gateway_from_context(context)
        projects: list[str] = config_from_context(context).projects or []

        def projects_without_override() -> list[str]:
            me: YouTrackUser = gateway.get_me()
            grants = RoleGrants(
                gateway.list_roles(),
                gateway.list_assigned_roles(),
                gateway.list_organizations(),
            )
            members = GroupMembers(gateway)
            lacking: list[str] = []
            for project in active_projects(gateway, projects):
                access: ProjectReaders = grants.project_readers(project.id, members)
                if me.id not in access.overriders:
                    lacking.append(project.short_name)
            return lacking

        lacking: list[str] = probe(
            projects_without_override, "Role assignments could not be read."
        )
        if lacking:
            raise InsufficientPermissionsError(
                "The token's user cannot read restricted issues in "
                f"{', '.join(lacking)}. {_ADMIN_REMEDIATION}"
            )


class _IssueVisibilityCheck(CapabilityCheck[YouTrackConnectorConfig]):
    config_class = YouTrackConnectorConfig

    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id="youtrack_issue_visibility",
            display_name="Issue visibility settings are readable",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            remediation="Give the token's user Read Issue in every project to sync.",
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: YouTrackSourceOperations = gateway_from_context(context)

        def read_first_issue_access() -> None:
            query: str | None = scoped_issue_query(context)
            if query is not None:
                next(
                    gateway.iterate_issue_access(
                        query=query, page_size=PROBE_PAGE_SIZE
                    ),
                    None,
                )

        probe(read_first_issue_access, "The token cannot read issue visibility.")


class _UserEmailsCheck(CapabilityCheck[YouTrackConnectorConfig]):
    config_class = YouTrackConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="youtrack_user_emails",
            display_name="Users' emails are readable",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            remediation=_ADMIN_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        users: list[YouTrackUser] = probe(
            gateway_from_context(context).list_users,
            "The token cannot list users.",
        )
        active: list[YouTrackUser] = [
            user for user in users if not user.banned and not user.guest
        ]
        # One user without an email is ordinary. None at all means YouTrack
        # hides them from this token, and every group would be empty.
        if active and not any(user.email for user in active):
            raise InsufficientPermissionsError(
                f"YouTrack shows no user emails to this token. {_ADMIN_REMEDIATION}"
            )


def build_youtrack_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _RestrictedIssuesCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _IssueVisibilityCheck(CredentialCapability.DOC_PERMISSION_SYNC),
    ]


def build_youtrack_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _RestrictedIssuesCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _IssueVisibilityCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _UserEmailsCheck(),
    ]
