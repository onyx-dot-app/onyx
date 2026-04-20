import os
import time
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_from_connector


def _make_connector(scoped_token: bool = False) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ["JIRA_PROJECT_KEY"],
        comment_email_blacklist=[],
        scoped_token=scoped_token,
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": (os.environ["JIRA_API_TOKEN_SCOPED"] if scoped_token else os.environ["JIRA_API_TOKEN"]),
        }
    )
    return connector


@pytest.fixture
def jsm_connector() -> JiraServiceManagementConnector:
    return _make_connector()


@pytest.fixture
def jsm_connector_scoped() -> JiraServiceManagementConnector:
    return _make_connector(scoped_token=True)


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    _test_jsm_connector_basic(jsm_connector)


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic_scoped(
    reset: None,  # noqa: ARG001
    jsm_connector_scoped: JiraServiceManagementConnector,
) -> None:
    _test_jsm_connector_basic(jsm_connector_scoped)


def _test_jsm_connector_basic(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0

    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert "issuetype" in doc.metadata
        assert "status" in doc.metadata
        if doc.metadata.get("request_status"):
            assert isinstance(doc.metadata["request_status"], str)
        if doc.metadata.get("service_desk_id"):
            assert isinstance(doc.metadata["service_desk_id"], str)
