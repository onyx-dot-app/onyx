"""Unit tests for retrieve_all_slim_docs_perm_sync method."""

from datetime import datetime
from datetime import timezone
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

from jira import JIRA

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import SlimDocument
from onyx.configs.app_configs import JIRA_SLIM_PAGE_SIZE


class TestRetrieveAllSlimDocsPermSync:
    """Test retrieve_all_slim_docs_perm_sync method."""

    def test_retrieve_all_slim_docs_basic(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test basic retrieve_all_slim_docs_perm_sync functionality."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue1 = create_mock_issue(key="ITSM-1", summary="Issue 1")
        mock_issue2 = create_mock_issue(key="ITSM-2", summary="Issue 2")

        jira_client = cast(JIRA, mock_jira_client)
        search_issues_mock = cast(MagicMock, jira_client.search_issues)
        search_issues_mock.side_effect = [[mock_issue1, mock_issue2], []]

        with patch(
            "onyx.connectors.jira.utils.get_jira_project_key_from_issue"
        ) as mock_get_key, patch(
            "onyx.connectors.jira.access.get_project_permissions"
        ) as mock_perms, patch(
            "onyx.connectors.jira.utils.best_effort_get_field_from_issue"
        ) as mock_get_field, patch(
            "onyx.connectors.jira.utils.build_jira_url"
        ) as mock_build_url:
            mock_get_key.return_value = jsm_project_key
            mock_perms.return_value = {"read": ["user@example.com"]}
            mock_get_field.side_effect = ["ITSM-1", "ITSM-2"]
            mock_build_url.side_effect = [
                f"{jira_base_url}/browse/ITSM-1",
                f"{jira_base_url}/browse/ITSM-2",
            ]

            # Mock update_checkpoint_for_next_run to set has_more=False after first batch
            with patch.object(connector, 'update_checkpoint_for_next_run') as mock_update:
                def update_side_effect(checkpoint, *args, **kwargs):
                    checkpoint.has_more = False
                mock_update.side_effect = update_side_effect

                results = list(connector.retrieve_all_slim_docs_perm_sync())

        assert len(results) > 0
        assert all(isinstance(batch, list) for batch in results)
        assert all(
            isinstance(doc, SlimDocument) for batch in results for doc in batch
        )

    def test_retrieve_all_slim_docs_with_custom_time_range(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test retrieve_all_slim_docs_perm_sync with custom time range."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Issue 1")
        start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

        jira_client = cast(JIRA, mock_jira_client)
        search_issues_mock = cast(MagicMock, jira_client.search_issues)
        search_issues_mock.side_effect = [[mock_issue], []]

        with patch(
            "onyx.connectors.jira.utils.get_jira_project_key_from_issue"
        ) as mock_get_key, patch(
            "onyx.connectors.jira.access.get_project_permissions"
        ) as mock_perms, patch(
            "onyx.connectors.jira.utils.best_effort_get_field_from_issue"
        ) as mock_get_field, patch(
            "onyx.connectors.jira.utils.build_jira_url"
        ) as mock_build_url:
            mock_get_key.return_value = jsm_project_key
            mock_perms.return_value = {"read": ["user@example.com"]}
            mock_get_field.return_value = "ITSM-1"
            mock_build_url.return_value = f"{jira_base_url}/browse/ITSM-1"

            with patch.object(connector, 'update_checkpoint_for_next_run') as mock_update:
                def update_side_effect(checkpoint, *args, **kwargs):
                    checkpoint.has_more = False
                mock_update.side_effect = update_side_effect

                results = list(connector.retrieve_all_slim_docs_perm_sync(start, end))

        assert len(results) > 0

    def test_retrieve_all_slim_docs_skips_issues_without_project_key(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test that issues without project key are skipped."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Issue 1")
        # Remove project field so get_jira_project_key_from_issue returns None
        delattr(mock_issue.fields, 'project')

        with patch(
            "onyx.connectors.jira.connector._perform_jql_search"
        ) as mock_search:
            def search_generator(*args, **kwargs):
                yield mock_issue
            mock_search.return_value = search_generator()

            with patch.object(connector, 'update_checkpoint_for_next_run') as mock_update:
                def update_side_effect(checkpoint, *args, **kwargs):
                    checkpoint.has_more = False
                mock_update.side_effect = update_side_effect

                results = list(connector.retrieve_all_slim_docs_perm_sync())

        # Should skip issue without project key - no batches should be yielded
        # The issue is skipped in the loop (continue at line 291), so no slim docs are added
        # When has_more becomes False, the final batch check (line 314-315) only yields
        # if slim_doc_batch is not empty. Since we skip, no batch is created.
        total_docs = sum(len(batch) for batch in results)
        assert total_docs == 0

    def test_retrieve_all_slim_docs_skips_issues_without_key(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test that issues without key field are skipped."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Issue 1")

        jira_client = cast(JIRA, mock_jira_client)
        search_issues_mock = cast(MagicMock, jira_client.search_issues)
        search_issues_mock.side_effect = [[mock_issue], []]

        with patch(
            "onyx.connectors.jira.utils.get_jira_project_key_from_issue"
        ) as mock_get_key, patch(
            "onyx.connectors.jira.utils.best_effort_get_field_from_issue"
        ) as mock_get_field:
            mock_get_key.return_value = jsm_project_key
            mock_get_field.return_value = None  # No key field

            with patch.object(connector, 'update_checkpoint_for_next_run') as mock_update:
                def update_side_effect(checkpoint, *args, **kwargs):
                    checkpoint.has_more = False
                mock_update.side_effect = update_side_effect

                results = list(connector.retrieve_all_slim_docs_perm_sync())

        # Should skip issue without key
        assert len(results) == 0 or all(len(batch) == 0 for batch in results)

    def test_retrieve_all_slim_docs_batches_correctly(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test that slim docs are batched correctly."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        # Create more issues than batch size
        mock_issues = [
            create_mock_issue(key=f"ITSM-{i}", summary=f"Issue {i}")
            for i in range(JIRA_SLIM_PAGE_SIZE + 5)
        ]

        jira_client = cast(JIRA, mock_jira_client)
        search_issues_mock = cast(MagicMock, jira_client.search_issues)
        search_issues_mock.side_effect = [mock_issues, []]

        with patch(
            "onyx.connectors.jira.utils.get_jira_project_key_from_issue"
        ) as mock_get_key, patch(
            "onyx.connectors.jira.access.get_project_permissions"
        ) as mock_perms, patch(
            "onyx.connectors.jira.utils.best_effort_get_field_from_issue"
        ) as mock_get_field, patch(
            "onyx.connectors.jira.utils.build_jira_url"
        ) as mock_build_url:
            mock_get_key.return_value = jsm_project_key
            mock_perms.return_value = {"read": ["user@example.com"]}
            mock_get_field.side_effect = [f"ITSM-{i}" for i in range(len(mock_issues))]
            mock_build_url.side_effect = [
                f"{jira_base_url}/browse/ITSM-{i}" for i in range(len(mock_issues))
            ]

            with patch.object(connector, 'update_checkpoint_for_next_run') as mock_update:
                def update_side_effect(checkpoint, *args, **kwargs):
                    checkpoint.has_more = False
                mock_update.side_effect = update_side_effect

                results = list(connector.retrieve_all_slim_docs_perm_sync())

        # Should have at least one batch
        assert len(results) > 0
        # Each batch should be <= batch size
        assert all(len(batch) <= JIRA_SLIM_PAGE_SIZE for batch in results)

    def test_retrieve_all_slim_docs_uses_permissions_cache(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test that permissions are cached when retrieving slim docs."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue1 = create_mock_issue(key="ITSM-1", summary="Issue 1")
        mock_issue2 = create_mock_issue(key="ITSM-2", summary="Issue 2")
        # Ensure both issues have project.key set so get_jira_project_key_from_issue works
        from types import SimpleNamespace
        project = SimpleNamespace(key=jsm_project_key, name="ITSM Project")
        mock_issue1.fields.project = project
        mock_issue2.fields.project = project

        jira_client = mock_jira_client
        search_issues_mock = jira_client.search_issues
        search_issues_mock.side_effect = [[mock_issue1, mock_issue2], []]

        from onyx.access.models import ExternalAccess

        with patch(
            "onyx.connectors.jira_service_management.connector.get_project_permissions"
        ) as mock_perms, patch(
            "onyx.connectors.jira.utils.best_effort_get_field_from_issue"
        ) as mock_get_field, patch(
            "onyx.connectors.jira.utils.build_jira_url"
        ) as mock_build_url, patch("onyx.configs.app_configs.JIRA_SLIM_PAGE_SIZE", 2):
            mock_perms.return_value = ExternalAccess(
                external_user_emails={"user@example.com"},
                external_user_group_ids=set(),
                is_public=False,
            )
            mock_get_field.side_effect = ["ITSM-1", "ITSM-2"]
            mock_build_url.side_effect = [
                f"{jira_base_url}/browse/ITSM-1",
                f"{jira_base_url}/browse/ITSM-2",
            ]

            list(connector.retrieve_all_slim_docs_perm_sync())

        # Should only call get_project_permissions once per project key (cached)
        # The method is called via _get_project_permissions which caches
        # Since both issues have the same project_key, it should only be called once
        assert mock_perms.call_count == 1
        assert jsm_project_key in connector._project_permissions_cache
