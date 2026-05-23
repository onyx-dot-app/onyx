import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from pytest import LogCaptureFixture

from ee.onyx.external_permissions.jira.page_access import get_project_permissions
from onyx.connectors.jira.utils import JIRA_CLOUD_API_VERSION
from onyx.connectors.jira.utils import JIRA_SERVER_API_VERSION

PROJECT_KEY = "PROJ"


def _permission(holder: dict) -> SimpleNamespace:
    return SimpleNamespace(
        raw={
            "id": 1,
            "permission": "BROWSE_PROJECTS",
            "holder": holder,
        }
    )


def _project_permissions(*permissions: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(permissions=list(permissions))


def _jira_client(rest_api_version: str) -> MagicMock:
    jira_client = MagicMock()
    jira_client._options = {"rest_api_version": rest_api_version}
    return jira_client


def test_cloud_direct_user_holder_still_uses_account_id_shape() -> None:
    jira_client = _jira_client(JIRA_CLOUD_API_VERSION)
    jira_client.project_permissionscheme.return_value = _project_permissions(
        _permission(
            {
                "type": "user",
                "value": "cloud-account-id",
                "user": {
                    "accountId": "cloud-account-id",
                    "emailAddress": "cloud@example.com",
                    "displayName": "Cloud User",
                    "active": True,
                },
            }
        )
    )

    external_access = get_project_permissions(jira_client, PROJECT_KEY)

    assert external_access is not None
    assert external_access.external_user_emails == {"cloud@example.com"}
    assert external_access.external_user_group_ids == set()
    assert external_access.is_public is False


def test_dc_direct_user_holder_accepts_email_without_account_id() -> None:
    jira_client = _jira_client(JIRA_SERVER_API_VERSION)
    jira_client.project_permissionscheme.return_value = _project_permissions(
        _permission(
            {
                "type": "user",
                "parameter": "dc-user",
                "user": {
                    "name": "dc-user",
                    "key": "JIRAUSER10000",
                    "emailAddress": "dc-user@example.com",
                    "displayName": "DC User",
                    "active": True,
                },
            }
        )
    )

    external_access = get_project_permissions(jira_client, PROJECT_KEY)

    assert external_access is not None
    assert external_access.external_user_emails == {"dc-user@example.com"}
    assert external_access.external_user_group_ids == set()
    assert external_access.is_public is False


def test_direct_group_holders_preserve_value_and_parameter_shapes() -> None:
    jira_client = _jira_client(JIRA_SERVER_API_VERSION)
    jira_client.project_permissionscheme.return_value = _project_permissions(
        _permission({"type": "group", "value": "cloud-group"}),
        _permission({"type": "group", "parameter": "dc-group"}),
    )

    external_access = get_project_permissions(jira_client, PROJECT_KEY)

    assert external_access is not None
    assert external_access.external_user_emails == set()
    assert external_access.external_user_group_ids == {"cloud-group", "dc-group"}
    assert external_access.is_public is False


def test_project_role_preserves_cloud_account_id_and_group_name_paths() -> None:
    jira_client = _jira_client(JIRA_CLOUD_API_VERSION)
    jira_client.project_permissionscheme.return_value = _project_permissions(
        _permission({"type": "projectRole", "value": "10010"})
    )
    jira_client.project_role.return_value = SimpleNamespace(
        actors=[
            SimpleNamespace(actorGroup=SimpleNamespace(name="jira-users")),
            SimpleNamespace(
                actorUser=SimpleNamespace(accountId="cloud-account-id"),
            ),
        ]
    )
    jira_client.user.return_value = SimpleNamespace(
        accountType="atlassian",
        emailAddress="cloud-role-user@example.com",
    )

    external_access = get_project_permissions(jira_client, PROJECT_KEY)

    assert external_access is not None
    assert external_access.external_user_emails == {"cloud-role-user@example.com"}
    assert external_access.external_user_group_ids == {"jira-users"}
    jira_client.user.assert_called_once_with(id="cloud-account-id")


def test_project_role_dc_user_actor_uses_name_for_lookup() -> None:
    jira_client = _jira_client(JIRA_SERVER_API_VERSION)
    jira_client.project_permissionscheme.return_value = _project_permissions(
        _permission({"type": "projectRole", "parameter": "10010"})
    )
    jira_client.project_role.return_value = SimpleNamespace(
        actors=[
            SimpleNamespace(
                actorUser=SimpleNamespace(name="dc-user", key="JIRAUSER10000"),
            ),
        ]
    )
    jira_client.user.return_value = SimpleNamespace(
        emailAddress="dc-role-user@example.com",
    )

    external_access = get_project_permissions(jira_client, PROJECT_KEY)

    assert external_access is not None
    assert external_access.external_user_emails == {"dc-role-user@example.com"}
    assert external_access.external_user_group_ids == set()
    jira_client.user.assert_called_once_with(id="dc-user")


def test_project_role_group_actor_uses_raw_actor_group_fallback() -> None:
    jira_client = _jira_client(JIRA_SERVER_API_VERSION)
    jira_client.project_permissionscheme.return_value = _project_permissions(
        _permission({"type": "projectRole", "parameter": "10010"})
    )
    jira_client.project_role.return_value = SimpleNamespace(
        actors=[
            SimpleNamespace(raw={"actorGroup": {"name": "raw-dc-group"}}),
        ]
    )

    external_access = get_project_permissions(jira_client, PROJECT_KEY)

    assert external_access is not None
    assert external_access.external_user_emails == set()
    assert external_access.external_user_group_ids == {"raw-dc-group"}
    assert external_access.is_public is False


def test_dynamic_only_holders_remain_empty_private_access(
    caplog: LogCaptureFixture,
) -> None:
    jira_client = _jira_client(JIRA_SERVER_API_VERSION)
    jira_client.project_permissionscheme.return_value = _project_permissions(
        _permission({"type": "reporter"}),
        _permission({"type": "assignee"}),
    )

    with caplog.at_level(logging.WARNING):
        external_access = get_project_permissions(jira_client, PROJECT_KEY)

    assert external_access is not None
    assert external_access.external_user_emails == set()
    assert external_access.external_user_group_ids == set()
    assert external_access.is_public is False
    assert all(record.levelno < logging.ERROR for record in caplog.records)
