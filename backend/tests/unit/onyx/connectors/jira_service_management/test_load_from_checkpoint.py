"""Unit tests for load_from_checkpoint methods in JSM connector."""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch


from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


class TestLoadFromCheckpoint:
    """Test load_from_checkpoint method."""

    def test_load_from_checkpoint_basic(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test basic load_from_checkpoint functionality."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue1 = create_mock_issue(key="ITSM-1", summary="Issue 1")
        mock_issue2 = create_mock_issue(key="ITSM-2", summary="Issue 2")

        jira_client = mock_jira_client
        search_issues_mock = jira_client.search_issues
        search_issues_mock.side_effect = [
            [mock_issue1, mock_issue2],
            [],
        ]

        start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

        with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
            outputs = load_everything_from_checkpoint_connector(connector, start, end)

        assert len(outputs) > 0
        assert len(outputs[0].items) > 0
        assert isinstance(outputs[0].items[0], Document)
        assert outputs[0].items[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT

    def test_load_from_checkpoint_with_date_error(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test load_from_checkpoint handles Atlassian date errors."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Test Issue")
        start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

        jira_client = mock_jira_client
        search_issues_mock = jira_client.search_issues
        search_issues_mock.side_effect = [[mock_issue], []]

        with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
            outputs = load_everything_from_checkpoint_connector(connector, start, end)
            assert len(outputs) > 0
            assert len(outputs[0].items) > 0

    def test_load_from_checkpoint_with_perm_sync(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test load_from_checkpoint_with_perm_sync method."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Issue 1")
        # Ensure the mock issue has a project field with name attribute
        from types import SimpleNamespace
        project = SimpleNamespace(key=jsm_project_key, name="ITSM Project")
        mock_issue.fields.project = project

        start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

        jira_client = mock_jira_client
        search_issues_mock = jira_client.search_issues
        search_issues_mock.side_effect = [[mock_issue], []]

        from onyx.access.models import ExternalAccess

        with patch(
            "onyx.connectors.jira_service_management.connector.get_project_permissions"
        ) as mock_perms, patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
            mock_perms.return_value = ExternalAccess(
                external_user_emails={"user@example.com"},
                external_user_group_ids=set(),
                is_public=False,
            )

            checkpoint = connector.build_dummy_checkpoint()
            gen = connector.load_from_checkpoint_with_perm_sync(start, end, checkpoint)
            documents = []
            try:
                while True:
                    doc = next(gen)
                    documents.append(doc)
            except StopIteration:
                pass

        assert len(documents) > 0
        assert isinstance(documents[0], Document)
        # Verify permissions were added - the document should have external_access set
        assert documents[0].external_access is not None
        assert "user@example.com" in documents[0].external_access.external_user_emails

    def test_load_from_checkpoint_with_perm_sync_date_error(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test load_from_checkpoint_with_perm_sync handles date errors."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Test Issue")
        start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

        jira_client = mock_jira_client
        search_issues_mock = jira_client.search_issues
        search_issues_mock.side_effect = [[mock_issue], []]

        # Ensure the mock issue has a project field
        from types import SimpleNamespace
        mock_issue.fields.project = SimpleNamespace(key=jsm_project_key)

        with patch(
            "onyx.connectors.jira.access.get_project_permissions"
        ) as mock_perms, patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
            mock_perms.return_value = {"read": ["user@example.com"]}

            checkpoint = connector.build_dummy_checkpoint()
            gen = connector.load_from_checkpoint_with_perm_sync(start, end, checkpoint)
            documents = []
            try:
                while True:
                    documents.append(next(gen))
            except StopIteration:
                pass

        assert len(documents) > 0

    def test_load_from_checkpoint_processes_documents(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test that _load_from_checkpoint processes documents correctly."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue1 = create_mock_issue(key="ITSM-1", summary="Issue 1")
        mock_issue2 = create_mock_issue(key="ITSM-2", summary="Issue 2")
        checkpoint = JiraConnectorCheckpoint(has_more=True, offset=0)

        # Ensure mock issues have project fields with name attribute
        from types import SimpleNamespace
        project = SimpleNamespace(key=jsm_project_key, name="ITSM Project")
        mock_issue1.fields.project = project
        mock_issue2.fields.project = project

        jira_client = mock_jira_client
        search_issues_mock = jira_client.search_issues
        search_issues_mock.side_effect = [[mock_issue1, mock_issue2], []]

        jql = connector._get_jql_query(
            datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp(),
            datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp(),
        )

        with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
            gen = connector._load_from_checkpoint(jql, checkpoint, False)
            results = []
            try:
                while True:
                    results.append(next(gen))
            except StopIteration:
                pass

        assert len(results) == 2
        assert all(isinstance(doc, Document) for doc in results)
        assert all(
            doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT for doc in results
        )

    def test_load_from_checkpoint_handles_processing_errors(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test that _load_from_checkpoint handles processing errors."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Issue 1")
        checkpoint = JiraConnectorCheckpoint(has_more=True, offset=0)

        jira_client = mock_jira_client
        search_issues_mock = jira_client.search_issues
        search_issues_mock.side_effect = [[mock_issue], []]

        with patch(
            "onyx.connectors.jira_service_management.connector.process_jira_issue"
        ) as mock_process, patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
            mock_process.side_effect = Exception("Processing failed")

            jql = connector._get_jql_query(
                datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp(),
                datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp(),
            )
            gen = connector._load_from_checkpoint(jql, checkpoint, False)
            results = []
            try:
                while True:
                    results.append(next(gen))
            except StopIteration:
                pass

        assert len(results) == 1
        assert isinstance(results[0], ConnectorFailure)
        assert results[0].failed_document.document_id == "ITSM-1"

    def test_load_from_checkpoint_with_permissions(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test _load_from_checkpoint with permission sync enabled."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Issue 1")
        # Ensure the mock issue has a project field for get_jira_project_key_from_issue
        from types import SimpleNamespace
        project = SimpleNamespace(key=jsm_project_key, name="ITSM Project")
        mock_issue.fields.project = project

        checkpoint = JiraConnectorCheckpoint(has_more=True, offset=0)

        jira_client = mock_jira_client
        search_issues_mock = jira_client.search_issues
        search_issues_mock.side_effect = [[mock_issue], []]

        with patch(
            "onyx.connectors.jira_service_management.connector.get_project_permissions"
        ) as mock_perms, patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
            mock_perms.return_value = {"read": ["user@example.com"]}

            jql = connector._get_jql_query(
                datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp(),
                datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp(),
            )
            gen = connector._load_from_checkpoint(jql, checkpoint, True)
            results = []
            try:
                while True:
                    results.append(next(gen))
            except StopIteration:
                pass

        assert len(results) == 1
        assert isinstance(results[0], Document)
        assert results[0].external_access == {"read": ["user@example.com"]}

    def test_update_checkpoint_for_next_run_cloud(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
    ):
        """Test update_checkpoint_for_next_run for cloud client."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "3"}

        checkpoint = JiraConnectorCheckpoint(has_more=False)
        checkpoint.all_issue_ids = [["ITSM-1", "ITSM-2"]]

        with patch(
            "onyx.connectors.jira.connector._is_cloud_client"
        ) as mock_is_cloud:
            mock_is_cloud.return_value = True
            connector.update_checkpoint_for_next_run(checkpoint, 2, 0, 2)

        assert checkpoint.has_more is True

    def test_update_checkpoint_for_next_run_server(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
    ):
        """Test update_checkpoint_for_next_run for server client."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        checkpoint = JiraConnectorCheckpoint(has_more=False, offset=0)

        with patch(
            "onyx.connectors.jira.connector._is_cloud_client"
        ) as mock_is_cloud:
            mock_is_cloud.return_value = False
            connector.update_checkpoint_for_next_run(checkpoint, 2, 0, 2)

        assert checkpoint.offset == 2
        assert checkpoint.has_more is True

    def test_get_project_permissions_caching(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
    ):
        """Test that _get_project_permissions caches results."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        with patch(
            "onyx.connectors.jira_service_management.connector.get_project_permissions"
        ) as mock_perms:
            mock_perms.return_value = {"read": ["user@example.com"]}

            # First call
            result1 = connector._get_project_permissions(jsm_project_key)
            # Second call should use cache
            result2 = connector._get_project_permissions(jsm_project_key)

        assert result1 == result2
        assert mock_perms.call_count == 1
        assert jsm_project_key in connector._project_permissions_cache
