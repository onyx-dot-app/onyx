from collections.abc import Generator
from typing import cast
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.fixture
def mock_source_operations() -> MagicMock:
    """Return an autospecced mock JiraSourceOperations gateway."""
    gateway = cast(MagicMock, create_autospec(JiraSourceOperations, instance=True))
    gateway._is_cloud.return_value = False
    gateway.get_service_desk_request.return_value = None
    gateway.get_service_desk_sla.return_value = None
    return gateway


@pytest.fixture
def jsm_connector(
    mock_source_operations: MagicMock,
) -> Generator[JiraServiceManagementConnector, None, None]:
    """Yield a JSM connector wired with mocked source operations."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jsm.example.com",
        project_key="HELP",
        labels_to_skip=["secret"],
    )
    connector._source_operations = mock_source_operations
    yield connector
