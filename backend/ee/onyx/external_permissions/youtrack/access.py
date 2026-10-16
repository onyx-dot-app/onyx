"""Who may read a YouTrack issue.

Project roles set the outer limit: a reader holds both Read Issue and Read
Issue Comment in the project, since the indexed text carries comments. An
issue's "Visible to" list can only narrow that set, so a restricted issue
names one synthetic group per visibility entry, each computed in group sync as
that entry's members who are project readers. (A ∪ B) ∩ R = (A ∩ R) ∪ (B ∩ R),
so the union of those groups is the intersection YouTrack enforces. Holders of
Override Visibility Restrictions and the reporter read restricted issues too.
Helpdesk projects skip the intersection, since a ticket's visibility names
everyone who may read it.
"""

import hashlib
from collections import defaultdict
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from ee.onyx.external_permissions.youtrack.models import (
    ProjectReaders,
    VisibilityEntries,
)
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.youtrack.models import (
    USER_HOLDER_TYPE,
    ScopeType,
    YouTrackAssignedRole,
    YouTrackIssueAccess,
    YouTrackOrganization,
    YouTrackPermission,
    YouTrackRole,
)
from onyx.connectors.youtrack.source_operations import YouTrackSourceOperations
from onyx.utils.logger import setup_logger

logger = setup_logger()

READ_ISSUE: str = "READ_ISSUE"
READ_COMMENT: str = "READ_COMMENT"
OVERRIDE_VISIBILITY: str = "READ_HIDDEN_STUFF"
_READER_PERMISSIONS: frozenset[str] = frozenset({READ_ISSUE, READ_COMMENT})


def instance_key(base_url: str) -> str:
    """Scopes group ids to one YouTrack, whose database ids repeat across
    instances. Only the scheme and host are case-insensitive, since a Server
    context path is not."""
    parts = urlsplit(base_url.rstrip("/"))
    normalized: str = urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, "", "")
    )
    return hashlib.sha256(normalized.encode()).hexdigest()[:12]


def project_group_id(instance: str, project_id: str) -> str:
    return f"{instance}:project:{project_id}"


def override_group_id(instance: str, project_id: str) -> str:
    return f"{instance}:override:{project_id}"


def visibility_group_id(instance: str, project_id: str, group_id: str) -> str:
    return f"{instance}:group:{project_id}:{group_id}"


def user_group_id(instance: str, project_id: str, user_id: str) -> str:
    """One user, if they can read the project. A group rather than an email
    so losing project access takes effect at the next group sync."""
    return f"{instance}:user:{project_id}:{user_id}"


def project_access(instance: str, project_id: str) -> ExternalAccess:
    return ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={project_group_id(instance, project_id)},
        is_public=False,
    )


def project_node_access(base_url: str, project_id: str) -> ExternalAccess:
    """Node permissions are stored as given, unlike document permissions, so
    the group id carries the source prefix its members are stored under."""
    return ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={
            build_ext_group_name_for_onyx(
                project_group_id(instance_key(base_url), project_id),
                DocumentSource.YOUTRACK,
            )
        },
        is_public=False,
    )


def visibility_entries(issue: YouTrackIssueAccess) -> VisibilityEntries | None:
    """None for an unrestricted issue, which every project reader sees."""
    visibility = issue.visibility
    if visibility is None or not visibility.is_restricted:
        return None
    user_ids: set[str] = {user.id for user in visibility.permitted_users}
    if issue.reporter is not None:
        user_ids.add(issue.reporter.id)
    return VisibilityEntries(
        group_ids={group.id for group in visibility.permitted_groups},
        user_ids=user_ids,
    )


def issue_access(base_url: str, issue: YouTrackIssueAccess) -> ExternalAccess:
    instance: str = instance_key(base_url)
    project_id: str = issue.project.id
    entries: VisibilityEntries | None = visibility_entries(issue)
    if entries is None:
        return project_access(instance, project_id)
    groups: set[str] = {override_group_id(instance, project_id)}
    groups |= {
        visibility_group_id(instance, project_id, group_id)
        for group_id in entries.group_ids
    }
    groups |= {
        user_group_id(instance, project_id, user_id) for user_id in entries.user_ids
    }
    return ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids=groups,
        is_public=False,
    )


def _permission_key(permission: YouTrackPermission) -> str:
    """The bare key, e.g. READ_ISSUE, whether or not the API prefixes it."""
    return (permission.key or permission.id).rsplit(".", 1)[-1]


class RoleGrants:
    """Every role assignment, indexed so one project's grants are its own,
    those of the organizations it belongs to, and the global ones."""

    def __init__(
        self,
        roles: list[YouTrackRole],
        assignments: list[YouTrackAssignedRole],
        organizations: list[YouTrackOrganization],
    ) -> None:
        self._role_permissions: dict[str, set[str]] = {
            role.id: {_permission_key(p) for p in role.permissions} for role in roles
        }
        self._organizations_by_project: defaultdict[str, set[str]] = defaultdict(set)
        for organization in organizations:
            for project in organization.projects:
                self._organizations_by_project[project.id].add(organization.id)
        self._global: list[YouTrackAssignedRole] = []
        self._by_scope_id: defaultdict[str, list[YouTrackAssignedRole]] = defaultdict(
            list
        )
        for assignment in assignments:
            scope = assignment.scope
            if scope.type == ScopeType.GLOBAL:
                self._global.append(assignment)
            elif scope.type == ScopeType.PROJECT and scope.project is not None:
                self._by_scope_id[scope.project.id].append(assignment)
            elif (
                scope.type == ScopeType.ORGANIZATION and scope.organization is not None
            ):
                self._by_scope_id[scope.organization.id].append(assignment)
            else:
                logger.warning("Skipping YouTrack role grant in scope %s", scope.type)

    def _grants(self, project_id: str) -> list[YouTrackAssignedRole]:
        grants: list[YouTrackAssignedRole] = [
            *self._global,
            *self._by_scope_id[project_id],
        ]
        for organization_id in self._organizations_by_project[project_id]:
            grants.extend(self._by_scope_id[organization_id])
        return grants

    def project_readers(
        self, project_id: str, group_members: Callable[[str], set[str]]
    ) -> ProjectReaders:
        permissions: defaultdict[str, set[str]] = defaultdict(set)
        for grant in self._grants(project_id):
            granted: set[str] = self._role_permissions.get(grant.role.id, set())
            if not granted & (_READER_PERMISSIONS | {OVERRIDE_VISIBILITY}):
                continue
            holder = grant.holder
            holders: set[str] = (
                {holder.id}
                if holder.type == USER_HOLDER_TYPE
                else group_members(holder.id)
            )
            for user_id in holders:
                permissions[user_id] |= granted
        readers: set[str] = {
            user_id
            for user_id, granted in permissions.items()
            if _READER_PERMISSIONS <= granted
        }
        return ProjectReaders(
            readers=readers,
            overriders={
                user_id
                for user_id in readers
                if OVERRIDE_VISIBILITY in permissions[user_id]
            },
        )


class GroupMembers:
    """Transitive group members, each group read once per sync."""

    def __init__(self, ops: YouTrackSourceOperations) -> None:
        self._ops = ops
        self._members: dict[str, set[str]] = {}

    def __call__(self, group_id: str) -> set[str]:
        if group_id not in self._members:
            self._members[group_id] = self._ops.list_group_user_ids(group_id=group_id)
        return self._members[group_id]
