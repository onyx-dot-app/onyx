"""Tests to achieve 100% code coverage for JSM connector."""

from datetime import datetime
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from onyx.connectors.exceptions import ConnectorValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document


class Test100Coverage:
    """Tests to achieve 100% code coverage."""

    def test_load_from_checkpoint_date_error_retry(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test load_from_checkpoint retries on date error (lines 153-154)."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Test Issue")
        start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
        checkpoint = JiraConnectorCheckpoint(has_more=True, offset=0)

        date_error = ConnectorValidationError("field 'updated' is invalid")

        with patch(
            "onyx.connectors.jira_service_management.connector.is_atlassian_date_error"
        ) as mock_is_date_error, patch.object(
            connector, "_load_from_checkpoint"
        ) as mock_load:
            call_count = [0]

            def load_side_effect(jql, cp, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise date_error
                # Second call succeeds
                def success_gen():
                    doc = Document(
                        id=f"{jira_base_url}/browse/ITSM-1",
                        sections=[],
                        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
                        semantic_identifier="ITSM-1: Test Issue",
                        metadata={},
                    )
                    yield doc
                    return cp
                return success_gen()

            mock_is_date_error.return_value = True
            mock_load.side_effect = load_side_effect

            gen = connector.load_from_checkpoint(start, end, checkpoint)
            results = []
            try:
                while True:
                    results.append(next(gen))
            except StopIteration:
                pass

        assert len(results) == 1
        assert mock_is_date_error.called
        assert mock_load.call_count == 2
        # Verify second call used adjusted start time (different JQL)
        assert mock_load.call_args_list[1][0][0] != mock_load.call_args_list[0][0][0]

    def test_load_from_checkpoint_raises_non_date_error(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
    ):
        """Test load_from_checkpoint raises non-date errors (line 157)."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
        checkpoint = JiraConnectorCheckpoint(has_more=True, offset=0)

        other_error = ValueError("Some other error")

        with patch(
            "onyx.connectors.jira_service_management.connector.is_atlassian_date_error"
        ) as mock_is_date_error, patch.object(
            connector, "_load_from_checkpoint"
        ) as mock_load:
            mock_is_date_error.return_value = False
            mock_load.side_effect = other_error

            with pytest.raises(ValueError, match="Some other error"):
                gen = connector.load_from_checkpoint(start, end, checkpoint)
                next(gen)

    def test_load_from_checkpoint_with_perm_sync_date_error_retry(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test load_from_checkpoint_with_perm_sync retries on date error (lines 171-172)."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Test Issue")
        mock_issue.fields.project = SimpleNamespace(key=jsm_project_key)
        start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
        checkpoint = JiraConnectorCheckpoint(has_more=True, offset=0)

        date_error = ConnectorValidationError("field 'updated' is invalid")

        with patch(
            "onyx.connectors.jira_service_management.connector.is_atlassian_date_error"
        ) as mock_is_date_error, patch.object(
            connector, "_load_from_checkpoint"
        ) as mock_load:
            call_count = [0]

            def load_side_effect(jql, cp, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise date_error
                # Second call succeeds
                def success_gen():
                    doc = Document(
                        id=f"{jira_base_url}/browse/ITSM-1",
                        sections=[],
                        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
                        semantic_identifier="ITSM-1: Test Issue",
                        metadata={},
                    )
                    yield doc
                    return cp
                return success_gen()

            mock_is_date_error.return_value = True
            mock_load.side_effect = load_side_effect

            gen = connector.load_from_checkpoint_with_perm_sync(start, end, checkpoint)
            results = []
            try:
                while True:
                    results.append(next(gen))
            except StopIteration:
                pass

        assert len(results) == 1
        assert mock_is_date_error.called
        assert mock_load.call_count == 2

    def test_load_from_checkpoint_with_perm_sync_raises_non_date_error(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
    ):
        """Test load_from_checkpoint_with_perm_sync raises non-date errors (line 175)."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
        checkpoint = JiraConnectorCheckpoint(has_more=True, offset=0)

        other_error = ValueError("Some other error")

        with patch(
            "onyx.connectors.jira_service_management.connector.is_atlassian_date_error"
        ) as mock_is_date_error, patch.object(
            connector, "_load_from_checkpoint"
        ) as mock_load:
            mock_is_date_error.return_value = False
            mock_load.side_effect = other_error

            with pytest.raises(ValueError, match="Some other error"):
                gen = connector.load_from_checkpoint_with_perm_sync(start, end, checkpoint)
                next(gen)


    def test_retrieve_all_slim_docs_skips_issue_without_project_key(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
        create_mock_issue,
    ):
        """Test retrieve_all_slim_docs_perm_sync skips issue without project_key (line 291)."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client
        mock_jira_client._options = {"rest_api_version": "2"}

        mock_issue = create_mock_issue(key="ITSM-1", summary="Issue 1")
        # Remove project field so get_jira_project_key_from_issue returns None
        if hasattr(mock_issue.fields, 'project'):
            delattr(mock_issue.fields, 'project')

        jira_client = mock_jira_client
        search_issues_mock = jira_client.search_issues
        search_issues_mock.side_effect = [[mock_issue], []]

        results = list(connector.retrieve_all_slim_docs_perm_sync())

        # Should skip issue without project key - no batches should be yielded
        total_docs = sum(len(batch) for batch in results)
        assert total_docs == 0
