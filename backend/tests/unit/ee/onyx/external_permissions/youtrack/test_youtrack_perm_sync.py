"""YouTrack permission sync: a restricted issue's readers are its visibility
entries intersected with the project's readers, plus Override Visibility
Restrictions holders and the reporter. The doc sync names synthetic groups
and the group sync fills each one with that intersection."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.youtrack.access import (
    instance_key,
    issue_access,
    override_group_id,
    project_group_id,
    user_group_id,
    visibility_group_id,
)
from ee.onyx.external_permissions.youtrack.group_sync import project_groups
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import HierarchyNode, SlimDocument
from onyx.connectors.youtrack.connector import YouTrackConnector
from onyx.connectors.youtrack.models import (
    YouTrackAssignedRole,
    YouTrackIssueAccess,
    YouTrackOrganization,
    YouTrackProject,
    YouTrackRole,
    YouTrackUser,
)

_BASE_URL = "https://example.youtrack.cloud"
_INSTANCE = instance_key(_BASE_URL)
_PROJECT: dict[str, Any] = {"id": "0-1", "shortName": "ABC", "name": "Alpha"}
_OTHER_PROJECT: dict[str, Any] = {"id": "0-2", "shortName": "XYZ", "name": "Other"}

_USERS: dict[str, dict[str, Any]] = {
    "dev": {"id": "1-1", "email": "Dev@Example.com"},
    "lead": {"id": "1-2", "email": "lead@example.com"},
    "outsider": {"id": "1-3", "email": "outsider@example.com"},
    "banned": {"id": "1-4", "email": "banned@example.com", "banned": True},
    "admin": {"id": "1-5", "email": "admin@example.com"},
    "observer": {"id": "1-6", "email": "observer@example.com"},
    "org": {"id": "1-7", "email": "org@example.com"},
    "guest": {"id": "1-9", "login": "guest", "guest": True},
}
_GROUPS: dict[str, set[str]] = {
    "devs": {"1-1", "1-4"},
    "contractors": {"1-1", "1-3"},
    "org-team": {"1-7"},
    "all-users": {u["id"] for u in _USERS.values()},
}


def _role(role_id: str, *keys: str) -> dict[str, Any]:
    return {"id": role_id, "permissions": [{"id": f"p-{k}", "key": k} for k in keys]}


def _grant(role_id: str, holder: str, scope: dict[str, Any]) -> dict[str, Any]:
    holder_type = "UserGroup" if holder in _GROUPS else "User"
    return {
        "role": {"id": role_id},
        "holder": {"$type": holder_type, "id": holder},
        "scope": scope,
    }


_PROJECT_SCOPE: dict[str, Any] = {"$type": "ProjectScope", "project": {"id": "0-1"}}
_ROLES = [
    _role("developer", "READ_ISSUE", "READ_COMMENT", "CREATE_ISSUE"),
    _role("observer", "READ_ISSUE"),
    _role("admin", "READ_ISSUE", "READ_COMMENT", "READ_HIDDEN_STUFF"),
    _role("reporter", "CREATE_ISSUE"),
]
_GRANTS = [
    _grant("developer", "devs", _PROJECT_SCOPE),
    _grant("developer", "1-2", _PROJECT_SCOPE),
    _grant("observer", "1-6", _PROJECT_SCOPE),
    _grant("admin", "1-5", {"$type": "GlobalScope"}),
    _grant(
        "developer",
        "org-team",
        {"$type": "OrganizationScope", "organization": {"id": "org-1"}},
    ),
    _grant("reporter", "all-users", _PROJECT_SCOPE),
]


def _access(
    issue_id: str, visibility: dict[str, Any] | None, reporter: str | None
) -> YouTrackIssueAccess:
    return YouTrackIssueAccess.model_validate(
        {
            "id": issue_id,
            "project": _PROJECT,
            "reporter": {"id": reporter} if reporter else None,
            "visibility": visibility,
        }
    )


_OPEN_ISSUE = _access("2-1", {"$type": "UnlimitedVisibility"}, "1-1")
_RESTRICTED_ISSUE = _access(
    "2-2",
    {
        "$type": "LimitedVisibility",
        "permittedGroups": [{"id": "contractors"}],
        "permittedUsers": [{"id": "1-3"}, {"id": "1-2"}],
    },
    "1-6",
)


def _connector(
    projects: list[str] | None = None,
) -> tuple[YouTrackConnector, MagicMock]:
    connector = YouTrackConnector(base_url=_BASE_URL, projects=projects)
    ops = MagicMock()
    ops.list_users.return_value = [
        YouTrackUser.model_validate(u) for u in _USERS.values()
    ]
    ops.list_group_user_ids.side_effect = lambda group_id: _GROUPS[group_id]
    ops.list_roles.return_value = [YouTrackRole.model_validate(r) for r in _ROLES]
    ops.list_assigned_roles.return_value = [
        YouTrackAssignedRole.model_validate(g) for g in _GRANTS
    ]
    ops.list_organizations.return_value = [
        YouTrackOrganization.model_validate(
            {"id": "org-1", "projects": [{"id": "0-1"}]}
        )
    ]
    ops.list_projects.return_value = [
        YouTrackProject.model_validate(_PROJECT),
        YouTrackProject.model_validate({**_OTHER_PROJECT, "archived": True}),
    ]
    ops.iterate_issue_access.side_effect = lambda **_kwargs: iter(
        [[_OPEN_ISSUE, _RESTRICTED_ISSUE]]
    )
    connector._ops = ops
    return connector, ops


def test_unrestricted_issue_names_its_project_group() -> None:
    access = issue_access(_BASE_URL, _OPEN_ISSUE)
    assert access.external_user_group_ids == {project_group_id(_INSTANCE, "0-1")}
    assert not access.external_user_emails
    assert not access.is_public


def test_restricted_issue_names_one_group_per_entry_plus_override_and_reporter() -> (
    None
):
    access = issue_access(_BASE_URL, _RESTRICTED_ISSUE)
    assert access.external_user_group_ids == {
        override_group_id(_INSTANCE, "0-1"),
        visibility_group_id(_INSTANCE, "0-1", "contractors"),
        user_group_id(_INSTANCE, "0-1", "1-3"),
        user_group_id(_INSTANCE, "0-1", "1-2"),
        user_group_id(_INSTANCE, "0-1", "1-6"),
    }


def test_group_sync_intersects_visibility_entries_with_project_readers() -> None:
    connector, _ = _connector()
    groups: dict[str, ExternalUserGroup] = {g.id: g for g in project_groups(connector)}

    readers = groups[project_group_id(_INSTANCE, "0-1")]
    # Banned and Read-Issue-only users drop out, emails are lowercased, and the
    # organization grant counts. Create Issue alone grants nothing.
    assert readers.user_emails == [
        "admin@example.com",
        "dev@example.com",
        "lead@example.com",
        "org@example.com",
    ]
    assert not readers.gives_anyone_access
    assert groups[override_group_id(_INSTANCE, "0-1")].user_emails == [
        "admin@example.com"
    ]
    # The outsider is in the visibility group but cannot read the project.
    assert groups[visibility_group_id(_INSTANCE, "0-1", "contractors")].user_emails == [
        "dev@example.com"
    ]
    assert groups[user_group_id(_INSTANCE, "0-1", "1-2")].user_emails == [
        "lead@example.com"
    ]
    assert user_group_id(_INSTANCE, "0-1", "1-3") not in groups
    # A reporter who lacks Read Issue Comment cannot see the indexed comments.
    assert user_group_id(_INSTANCE, "0-1", "1-6") not in groups
    assert project_group_id(_INSTANCE, "0-2") not in groups


def test_all_users_grant_lists_registered_users_and_never_goes_public() -> None:
    connector, ops = _connector()
    ops.list_assigned_roles.return_value = [
        YouTrackAssignedRole.model_validate(
            _grant("developer", "all-users", _PROJECT_SCOPE)
        )
    ]
    groups: dict[str, ExternalUserGroup] = {g.id: g for g in project_groups(connector)}
    readers = groups[project_group_id(_INSTANCE, "0-1")]
    assert not readers.gives_anyone_access
    assert "outsider@example.com" in readers.user_emails


def test_helpdesk_visibility_entries_grant_access_without_a_role() -> None:
    """Customers and CC'd users hold no role in a helpdesk project, yet read the
    tickets whose visibility names them."""
    connector, ops = _connector()
    ops.list_projects.return_value = [
        YouTrackProject.model_validate({**_PROJECT, "projectType": {"id": "HELPDESK"}})
    ]
    groups: dict[str, ExternalUserGroup] = {g.id: g for g in project_groups(connector)}

    assert groups[visibility_group_id(_INSTANCE, "0-1", "contractors")].user_emails == [
        "dev@example.com",
        "outsider@example.com",
    ]
    assert groups[user_group_id(_INSTANCE, "0-1", "1-3")].user_emails == [
        "outsider@example.com"
    ]
    # The reporter reads their own ticket with no role too.
    assert groups[user_group_id(_INSTANCE, "0-1", "1-6")].user_emails == [
        "observer@example.com"
    ]
    # The project's own readers group still requires a role.
    assert "outsider@example.com" not in (
        groups[project_group_id(_INSTANCE, "0-1")].user_emails
    )


def test_customers_never_read_through_a_role() -> None:
    """A role granted to All Users names helpdesk customers too, but YouTrack
    shows them only tickets whose visibility names them."""
    connector, ops = _connector()
    ops.list_users.return_value = [
        YouTrackUser.model_validate(u) for u in _USERS.values()
    ] + [
        YouTrackUser.model_validate(
            {"id": "1-8", "email": "cust@example.com", "userType": {"id": "REPORTER"}}
        )
    ]
    ops.list_group_user_ids.side_effect = lambda group_id: (
        _GROUPS[group_id] | ({"1-8"} if group_id == "all-users" else set())
    )
    ops.list_assigned_roles.return_value = [
        YouTrackAssignedRole.model_validate(
            _grant("developer", "all-users", _PROJECT_SCOPE)
        )
    ]
    groups: dict[str, ExternalUserGroup] = {g.id: g for g in project_groups(connector)}

    assert (
        "cust@example.com" not in groups[project_group_id(_INSTANCE, "0-1")].user_emails
    )


def test_perm_sync_walk_yields_the_project_node_once_with_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.connectors.youtrack.access.global_version.is_ee_version", lambda: True
    )
    connector, _ = _connector()
    (batch,) = list(connector.retrieve_all_slim_docs_perm_sync())

    node, *docs = batch
    assert isinstance(node, HierarchyNode)
    assert node.external_access is not None
    # Stored as given, so it must match the prefixed id of the group's rows.
    assert node.external_access.external_user_group_ids == {
        build_ext_group_name_for_onyx(
            project_group_id(_INSTANCE, "0-1"), DocumentSource.YOUTRACK
        )
    }
    assert [d.id for d in docs if isinstance(d, SlimDocument)] == [
        f"{_BASE_URL}/api/issues/2-1",
        f"{_BASE_URL}/api/issues/2-2",
    ]


def test_instance_key_keeps_the_context_path_case() -> None:
    """Two Servers behind one host differ only by context path, which is case
    sensitive, so their group ids must not collide."""
    assert instance_key("https://Host.example.com/youtrack/") == instance_key(
        "https://host.example.com/youtrack"
    )
    assert instance_key("https://host.example.com/YouTrack") != instance_key(
        "https://host.example.com/youtrack"
    )


def test_group_sync_stops_at_the_job_deadline_during_the_issue_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ee.onyx.external_permissions.youtrack.group_sync.PERMISSION_SYNC_TIMEOUT", -1
    )
    connector, _ = _connector()
    with pytest.raises(RuntimeError, match="timeout"):
        list(project_groups(connector))
