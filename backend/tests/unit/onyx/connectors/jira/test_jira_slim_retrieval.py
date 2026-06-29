from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from jira.resources import Issue

from onyx.access.models import ExternalAccess
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.models import SlimDocument


def _make_issue(key: str, project_key: str = "TEST") -> MagicMock:
    issue = MagicMock(spec=Issue)
    issue.key = key
    issue.fields = MagicMock()
    issue.fields.project = MagicMock()
    issue.fields.project.key = project_key
    issue.fields.project.name = "Test Project"
    issue.fields.parent = None
    return issue


def _stop_after_first_page(
    checkpoint: JiraConnectorCheckpoint, *_args: Any, **_kwargs: Any
) -> None:
    checkpoint.has_more = False


def _slim_docs(result: Any) -> list[SlimDocument]:
    docs: list[SlimDocument] = []
    for batch in result:
        docs.extend(d for d in batch if isinstance(d, SlimDocument))
    return docs


def test_retrieve_all_slim_docs_skips_permission_resolution(
    jira_connector: JiraConnector,
) -> None:
    """The ID-only path (used by pruning) must not call the admin-gated per-project
    permission endpoint, and must leave external_access unset."""
    with (
        patch(
            "onyx.connectors.jira.connector._perform_jql_search",
            return_value=[_make_issue("TEST-1"), _make_issue("TEST-2")],
        ),
        patch.object(JiraConnector, "_get_project_permissions") as mock_get_permissions,
        patch.object(
            JiraConnector, "_yield_project_hierarchy_node", return_value=iter([])
        ),
        patch.object(
            JiraConnector,
            "_yield_parent_hierarchy_node_if_epic",
            return_value=iter([]),
        ),
        patch.object(
            JiraConnector, "_yield_epic_hierarchy_node", return_value=iter([])
        ),
        patch.object(JiraConnector, "_is_epic", return_value=False),
        patch.object(
            JiraConnector, "_get_parent_hierarchy_raw_node_id", return_value=None
        ),
        patch.object(
            JiraConnector,
            "update_checkpoint_for_next_run",
            side_effect=_stop_after_first_page,
        ),
    ):
        docs = _slim_docs(jira_connector.retrieve_all_slim_docs())

    assert [d.id for d in docs] == [
        "https://jira.example.com/browse/TEST-1",
        "https://jira.example.com/browse/TEST-2",
    ]
    assert all(d.external_access is None for d in docs)
    mock_get_permissions.assert_not_called()


def test_retrieve_all_slim_docs_perm_sync_resolves_permissions(
    jira_connector: JiraConnector,
) -> None:
    """The perm-sync path must still resolve external_access per document."""
    external_access = ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids=set(),
        is_public=True,
    )
    with (
        patch(
            "onyx.connectors.jira.connector._perform_jql_search",
            return_value=[_make_issue("TEST-1")],
        ),
        patch.object(
            JiraConnector,
            "_get_project_permissions",
            return_value=external_access,
        ) as mock_get_permissions,
        patch.object(
            JiraConnector, "_yield_project_hierarchy_node", return_value=iter([])
        ),
        patch.object(
            JiraConnector,
            "_yield_parent_hierarchy_node_if_epic",
            return_value=iter([]),
        ),
        patch.object(
            JiraConnector, "_yield_epic_hierarchy_node", return_value=iter([])
        ),
        patch.object(JiraConnector, "_is_epic", return_value=False),
        patch.object(
            JiraConnector, "_get_parent_hierarchy_raw_node_id", return_value=None
        ),
        patch.object(
            JiraConnector,
            "update_checkpoint_for_next_run",
            side_effect=_stop_after_first_page,
        ),
    ):
        docs = _slim_docs(jira_connector.retrieve_all_slim_docs_perm_sync())

    assert [d.id for d in docs] == ["https://jira.example.com/browse/TEST-1"]
    assert all(d.external_access is external_access for d in docs)
    mock_get_permissions.assert_called_once_with("TEST", add_prefix=False)
