"""Unit tests for checkpoint handling in JSM connector."""

import json

import pytest

from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


class TestCheckpointHandling:
    """Test checkpoint creation, validation, and updates."""

    def test_build_dummy_checkpoint(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test building a dummy checkpoint."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        checkpoint = connector.build_dummy_checkpoint()

        assert isinstance(checkpoint, JiraConnectorCheckpoint)
        assert checkpoint.has_more is True

    def test_validate_checkpoint_json(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test checkpoint JSON validation."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        checkpoint_data = {
            "has_more": True,
            "offset": 10,
            "all_issue_ids": [],
            "ids_done": False,
            "cursor": None,
        }
        checkpoint_json = json.dumps(checkpoint_data)

        checkpoint = connector.validate_checkpoint_json(checkpoint_json)

        assert isinstance(checkpoint, JiraConnectorCheckpoint)
        assert checkpoint.has_more is True
        assert checkpoint.offset == 10

    def test_validate_checkpoint_json_invalid(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test checkpoint JSON validation with invalid JSON."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        invalid_json = "{ invalid json }"

        with pytest.raises(Exception):  # Should raise validation error
            connector.validate_checkpoint_json(invalid_json)
