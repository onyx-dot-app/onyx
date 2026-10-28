"""Auto-discovering coverage harness for source operations.

For every registered gateway, every (operation, variant) unit must be exercised,
per capability tag, by a capability check of that capability -- unless the
operation carries an ``untested`` reason. A per-connector session that registers
a gateway is picked up here automatically; it cannot forget to wire the test.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake.models import (
    AzureDataLakePath,
    AzureDataLakePathPage,
    AzureRoleAssignment,
    AzureRoleDefinition,
    AzureStorageAccountPage,
    AzureStorageAccountResource,
    AzureSubscription,
    AzureSubscriptionPage,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.confluence.source_operations import (
    ConfluenceRestSpacePermissionsNotAvailableError,
    ConfluenceSpacePermissionsVariant,
)
from onyx.connectors.github.models import (
    GitHubGitTree,
    GitHubIssue,
    GitHubOrganizationRef,
    GitHubPullRequest,
    GitHubRepository,
    GitHubTokenInfo,
    GitHubTokenKind,
    GitHubTreeEntry,
)
from onyx.connectors.github.source_operations import GitHubApiError
from onyx.connectors.google_drive.models import (
    GDriveMimeType,
    GoogleDriveAuth,
    GoogleGroupMember,
)
from onyx.connectors.google_utils.shared_constants import GoogleCredentialKind
from onyx.connectors.jira.models import JiraGroupPage
from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    DriveDeltaPage,
)
from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.entra import EntraGroup, EntraPage
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.microsoft_utils.models import (
    SharepointPrincipal,
    SharepointRoleAssignment,
)
from onyx.connectors.microsoft_utils.sharepoint_principals import (
    SharepointPrincipalType,
)
from onyx.connectors.sharepoint.models import (
    SharepointDrive,
    SitePagesPage,
    SiteUrlListing,
)
from onyx.connectors.slack.source_operations import (
    SlackAuthTestResponse,
    SlackChannelMembersPage,
    SlackChannelsPage,
    SlackTeamsPage,
    SlackUsersPage,
)
from onyx.connectors.source_operations import (
    SourceOperations,
    registered_source_operations,
)
from onyx.connectors.youtrack.models import (
    YouTrackAssignedRole,
    YouTrackIssue,
    YouTrackIssueAccess,
    YouTrackProject,
    YouTrackRole,
    YouTrackUser,
)
from tests.unit.onyx.connectors.source_operation_harnesses import (
    compute_uncovered_units,
    import_all_source_operation_gateways,
)

import_all_source_operation_gateways()


def _configure_confluence_spy(spy: MagicMock) -> None:
    """A DC 9.1+ site whose REST space-permissions endpoint is missing: the
    checks try REST and then fall back to JSON-RPC, so both DC units run."""

    def get_space_permissions(
        *, variant: ConfluenceSpacePermissionsVariant, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        if variant == ConfluenceSpacePermissionsVariant.DC_REST:
            raise ConfluenceRestSpacePermissionsNotAvailableError("coverage spy")
        return []

    spy.get_server_version.return_value = (9, 1)
    spy.get_space_permissions.side_effect = get_space_permissions


def _configure_confluence_rest_spy(spy: MagicMock) -> None:
    """A DC 9.1+ site whose REST space-permissions endpoint answers: the
    anonymous-access check reads the anonymous endpoint, as permission sync
    does on such a site."""
    spy.get_server_version.return_value = (9, 1)
    spy.get_space_permissions.return_value = []
    spy.get_anonymous_space_permissions.return_value = []


def _configure_slack_spy(spy: MagicMock) -> None:
    """A Grid org with one workspace, where the bot sees one channel with one
    member and one user, so the checks that read an item after they find one
    run."""
    spy.check_auth.return_value = SlackAuthTestResponse(ok=True, enterprise_id="E1")
    spy.list_teams.side_effect = lambda **_kwargs: iter(
        [SlackTeamsPage(teams=[{"id": "T1", "name": "Acme"}])]
    )
    spy.list_users.side_effect = lambda **_kwargs: iter(
        [SlackUsersPage(members=[{"id": "U1"}])]
    )
    spy.list_channels.side_effect = lambda **_kwargs: iter(
        [SlackChannelsPage(channels=[{"id": "C1", "name": "general"}])]
    )
    spy.list_channel_members.side_effect = lambda **_kwargs: iter(
        [SlackChannelMembersPage(members=["U1"])]
    )


def _configure_google_drive_spy(spy: MagicMock) -> None:
    """A service account whose primary admin sees a Google Doc, a small
    upload, a shared drive file and a folder whose permissions come only by
    id, and one shared drive, organized through a group."""
    admin = "admin@example.com"
    sample = [
        {"id": "doc", "name": "doc", "mimeType": GDriveMimeType.DOC.value},
        {"id": "pdf", "name": "pdf", "mimeType": "application/pdf", "size": "10"},
        {"id": "shared", "name": "shared", "permissionIds": ["permission"]},
    ]
    spy.authenticate.return_value = GoogleDriveAuth(
        kind=GoogleCredentialKind.SERVICE_ACCOUNT, primary_admin_email=admin
    )
    spy.list_files.side_effect = lambda **_kwargs: iter(sample)
    spy.list_drives.side_effect = lambda **_kwargs: iter(["drive"])
    spy.list_drive_members.side_effect = lambda **_kwargs: iter(
        [{"emailAddress": "team@example.com", "type": "group", "role": "organizer"}]
    )
    spy.list_group_members.side_effect = lambda **_kwargs: iter(
        [GoogleGroupMember(email="organizer@example.com", type="USER")]
    )
    spy.list_user_emails.side_effect = lambda **_kwargs: iter([admin])
    spy.can_list_drive.return_value = True
    spy.list_folders_with_permissions.side_effect = lambda **_kwargs: iter(
        [{"id": "folder", "name": "folder", "permissionIds": ["permission"]}]
    )
    spy.list_file_permissions.side_effect = lambda **_kwargs: iter(
        [{"id": "permission"}]
    )


def _configure_jira_site(spy: MagicMock) -> None:
    """A project that grants Browse Projects to a role with one user, and a
    group with one member, so the permission checks reach every read."""
    spy.list_projects.return_value = [{"key": "AS"}]
    spy.get_project_permission_scheme.return_value = {
        "permissions": [
            {
                "permission": "BROWSE_PROJECTS",
                "holder": {"type": "projectRole", "value": "10003"},
            }
        ]
    }
    spy.get_project_role.return_value = {
        "actors": [{"actorUser": {"accountId": "a1", "name": "a1"}}]
    }
    spy.list_groups.return_value = JiraGroupPage(group_names=["devs"], total=1)
    spy.get_group_members_page.return_value = {"values": [{"name": "a1"}]}


def _configure_jira_cloud_spy(spy: MagicMock) -> None:
    """A Cloud credential: the checks search with enhanced search and bulk
    fetch."""
    _configure_jira_site(spy)
    spy._is_cloud.return_value = True


def _configure_jira_server_spy(spy: MagicMock) -> None:
    """A Data Center credential: the checks search with the v2 search."""
    _configure_jira_site(spy)
    spy._is_cloud.return_value = False


def _configure_sharepoint_spy(spy: MagicMock) -> None:
    """A tenant with one site holding one library, one small file in a folder
    and one page, whose permissions name a site group and an Entra group, so
    the read checks reach the item-level and group-level operations."""
    site_url: str = "https://contoso.sharepoint.com/sites/eng"
    spy.get_auth_method.return_value = MicrosoftAuthMethod.CERTIFICATE
    spy.list_site_urls.return_value = SiteUrlListing(
        site_urls=[site_url], complete=True
    )
    spy.get_site_id.return_value = "site-id"
    spy.list_drives.return_value = [
        SharepointDrive(
            id="drive-id",
            name="Documents",
            web_url=f"{site_url}/Documents",
            list_id="list-id",
        )
    ]
    item = {
        "id": "item-id",
        "name": "a.pdf",
        "webUrl": f"{site_url}/Documents/Plans/a.pdf",
        "size": 10,
        "file": {"mimeType": "application/pdf"},
        "parentReference": {"driveId": "drive-id", "path": "/drives/d/root:/Plans"},
    }
    spy.get_delta_page.return_value = DriveDeltaFetchResult(
        page=DriveDeltaPage.model_validate({"value": [item]})
    )
    spy.get_drive_item.return_value = DriveItemData.from_graph_json(item)
    spy.list_site_pages.return_value = SitePagesPage(
        pages=[{"id": "page-id", "webUrl": f"{site_url}/SitePages/Home.aspx"}]
    )
    spy.list_role_assignments.return_value = [
        SharepointRoleAssignment(
            member=SharepointPrincipal(
                principal_type=SharepointPrincipalType.SHAREPOINT_GROUP,
                login_name="Eng Members",
                title="Eng Members",
            ),
            role_type_kinds=[3],
        ),
        SharepointRoleAssignment(
            member=SharepointPrincipal(
                principal_type=SharepointPrincipalType.ENTRA_GROUP,
                login_name="Engineering",
                title="Engineering",
            ),
            role_type_kinds=[3],
        ),
    ]
    spy.find_entra_group_id.return_value = "group-id"
    spy.get_folder_unique_id.return_value = "folder-id"
    spy.get_list_item_id.return_value = 1
    spy.list_entra_groups.return_value = EntraPage(
        items=[EntraGroup(id="group-id", displayName="Engineering")]
    )


def _github_repository(name: str, visibility: str) -> GitHubRepository:
    return GitHubRepository(
        id=len(name),
        name=name,
        full_name=f"acme/{name}",
        html_url=f"https://github.com/acme/{name}",
        default_branch="main",
        visibility=visibility,
        organization=GitHubOrganizationRef(id=1, login="acme"),
        raw_data={},
    )


def _configure_github_spy(spy: MagicMock) -> None:
    """An organization with a private repository that has a pull request, an
    issue and a README, and an internal repository. Each group has one
    member."""
    repositories = [
        _github_repository("docs", "private"),
        _github_repository("handbook", "internal"),
    ]
    spy.get_token_info.return_value = GitHubTokenInfo(
        login="octocat", kind=GitHubTokenKind.CLASSIC, scopes=["repo", "read:org"]
    )
    spy.list_organization_repositories.return_value = repositories
    spy.list_user_repositories.return_value = repositories
    spy.get_repository.return_value = repositories[0]
    spy.list_pull_requests.return_value = [
        GitHubPullRequest(
            number=1, title="PR", state="open", html_url="https://github.com/pr/1"
        )
    ]
    spy.list_issues.return_value = [
        GitHubIssue(
            number=2,
            title="Issue",
            state="open",
            html_url="https://github.com/issue/2",
            updated_at="2024-01-01T00:00:00Z",
            repo_full_name="acme/docs",
        )
    ]
    spy.get_git_tree.return_value = GitHubGitTree(
        entries=[GitHubTreeEntry(path="README.md", type="blob", size=10)]
    )
    spy.list_repository_collaborators.return_value = ["octocat"]
    spy.list_organization_members.return_value = ["octocat"]


def _configure_github_user_owner_spy(spy: MagicMock) -> None:
    """The same repositories, owned by a user: the checks list them with the
    user listing."""
    _configure_github_spy(spy)
    spy.get_organization.side_effect = GitHubApiError(
        "404 Not Found", status_code=404, github_message="Not Found"
    )


def _configure_youtrack_spy(spy: MagicMock) -> None:
    """One project whose readers come through a group, holding one issue, so
    the checks reach the group listing and the comment read."""
    project = {"id": "0-1", "shortName": "ABC", "name": "Alpha"}
    issue = {"id": "2-1", "idReadable": "ABC-1", "created": 1, "updated": 1}
    spy.get_me.return_value = YouTrackUser(id="1-1")
    spy.list_projects.return_value = [YouTrackProject.model_validate(project)]
    spy.list_assigned_roles.return_value = [
        YouTrackAssignedRole.model_validate(
            {
                "role": {"id": "r"},
                "holder": {"$type": "UserGroup", "id": "g"},
                "scope": {"$type": "GlobalScope"},
            }
        )
    ]
    spy.list_roles.return_value = [
        YouTrackRole.model_validate(
            {"id": "r", "permissions": [{"id": "JetBrains.YouTrack.READ_ISSUE"}]}
        )
    ]
    spy.list_group_user_ids.return_value = {"1-1"}
    spy.list_users.return_value = [YouTrackUser(id="1-1", email="a@example.com")]
    spy.iterate_issues.side_effect = lambda **_kwargs: iter(
        [[YouTrackIssue.model_validate({**issue, "project": project})]]
    )
    spy.iterate_issue_access.side_effect = lambda **_kwargs: iter(
        [[YouTrackIssueAccess.model_validate({"id": "2-1", "project": project})]]
    )


def _configure_azure_datalake_spy(spy: MagicMock) -> None:
    """A container holding one file, so the read check reaches the download,
    in an account that Azure Resource Manager lists with one role assignment,
    in a tenant with one group."""
    spy.list_subscriptions.return_value = AzureSubscriptionPage(
        subscriptions=[AzureSubscription(subscription_id="sub")]
    )
    spy.list_storage_accounts.return_value = AzureStorageAccountPage(
        accounts=[
            AzureStorageAccountResource(
                id="/subscriptions/sub/resourceGroups/rg/providers/"
                "Microsoft.Storage/storageAccounts/onyxtest",
                name="onyxtest",
            )
        ]
    )
    spy.list_role_assignments.return_value = [
        AzureRoleAssignment(
            id="assignment",
            principal_id="user",
            principal_type="User",
            role_definition_id="/providers/Microsoft.Authorization/roleDefinitions/r",
            scope="/subscriptions/sub",
        )
    ]
    spy.get_role_definition.return_value = AzureRoleDefinition(id="r")
    spy.list_deny_assignments.return_value = []
    spy.list_groups.return_value = EntraPage[EntraGroup](items=[EntraGroup(id="group")])
    spy.list_paths_page.return_value = AzureDataLakePathPage(
        paths=[
            AzureDataLakePath(
                name="docs/readme.txt",
                is_directory=False,
                last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
                content_length=10,
            )
        ],
        continuation_token=None,
    )


def _configure_asana_spy(spy: MagicMock) -> None:
    """One project holding one task with a comment and a creator, so the
    tasks sample reaches the comment and user reads."""
    workspace = {"gid": "1", "name": "Acme"}
    project = {"gid": "2", "name": "Roadmap", "archived": False, "workspace": workspace}
    spy.get_me.return_value = {"gid": "u", "workspaces": [workspace]}
    spy.get_workspace.return_value = workspace
    spy.get_team.return_value = {"gid": "3", "name": "Eng", "organization": workspace}
    spy.get_project.return_value = project
    spy.iterate_projects.side_effect = lambda **_kwargs: iter([project])
    spy.iterate_project_tasks.side_effect = lambda **_kwargs: iter(
        [{"gid": "4", "name": "Task", "created_by": {"gid": "u"}}]
    )
    spy.iterate_task_stories.side_effect = lambda **_kwargs: iter(
        [{"gid": "5", "resource_subtype": "comment_added"}]
    )


# A unit is covered when the checks exercise it under any one configuration:
# a source whose credential picks the API family needs one per family.
_SPY_CONFIGURATIONS: dict[DocumentSource, list[Callable[[MagicMock], None]]] = {
    DocumentSource.ASANA: [_configure_asana_spy],
    DocumentSource.CONFLUENCE: [
        _configure_confluence_spy,
        _configure_confluence_rest_spy,
    ],
    DocumentSource.GOOGLE_DRIVE: [_configure_google_drive_spy],
    DocumentSource.JIRA: [_configure_jira_cloud_spy, _configure_jira_server_spy],
    DocumentSource.SHAREPOINT: [_configure_sharepoint_spy],
    DocumentSource.GITHUB: [_configure_github_spy, _configure_github_user_owner_spy],
    DocumentSource.SLACK: [_configure_slack_spy],
    DocumentSource.YOUTRACK: [_configure_youtrack_spy],
    DocumentSource.AZURE_DATALAKE: [_configure_azure_datalake_spy],
}

# The connector config the checks read, per source (default: empty). Every
# spy configuration runs with every config listed here.
_CONNECTOR_CONFIGS: dict[DocumentSource, list[dict[str, Any]]] = {
    # The team filter applies only without project IDs, and the workspace
    # listing only without them too.
    DocumentSource.ASANA: [
        {"asana_workspace_id": "1", "asana_project_ids": "2"},
        {"asana_workspace_id": "1", "asana_team_id": "3"},
    ],
    DocumentSource.GITHUB: [
        {
            "repo_owner": "acme",
            "include_issues": True,
            "include_files": True,
            "branch": "main",
        },
        {"repo_owner": "acme", "repositories": "docs"},
    ],
    DocumentSource.YOUTRACK: [
        {"base_url": "https://example.youtrack.cloud", "projects": ["ABC"]}
    ],
    # The root page check reads a page only when a root page is set.
    DocumentSource.NOTION: [{"root_page_id": "17ab3186873d418fb899c3f6a43f68de"}],
    # The selected-scope checks read teams and projects only when some are set.
    DocumentSource.LINEAR: [{"team_keys": ["ENG"], "projects": ["Roadmap"]}],
    DocumentSource.AZURE_DATALAKE: [
        {"account_name": "onyxtest", "container_name": "docs", "path_prefix": "docs"}
    ],
}


@pytest.mark.usefixtures("enable_ee")
@pytest.mark.parametrize(
    "gateway_class",
    list(registered_source_operations().values()),
    ids=lambda gateway_class: gateway_class.source.value,
)
def test_every_operation_unit_is_exercised_by_a_check(
    gateway_class: type[SourceOperations],
) -> None:
    """Verifies check coverage of every non-exempt (operation, variant) unit.

    Runs with EE enabled: perm-sync checks live only in the EE registries, so
    perm-sync-tagged units are coverable only when EE resolution is on.
    """
    # Precondition.
    checks = get_capability_checks(gateway_class.source)

    # Under test.
    configurations = _SPY_CONFIGURATIONS.get(gateway_class.source) or [None]
    connector_configs = _CONNECTOR_CONFIGS.get(gateway_class.source) or [None]
    uncovered = set.intersection(
        *(
            set(
                compute_uncovered_units(
                    gateway_class, checks, configure_spy, connector_config
                )
            )
            for configure_spy in configurations
            for connector_config in connector_configs
        )
    )

    # Postcondition.
    assert not uncovered, (
        f"{gateway_class.source.value} has operation units no capability "
        f"check exercises: {uncovered}. Add a check composing them "
        '(variant-bearing operations must be invoked with variant="<name>") '
        'or annotate the operation untested="<reason>".'
    )
