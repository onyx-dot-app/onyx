import os
import time
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document, SlimDocument
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
)


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    """A connector against the shared Atlassian test site.

    ``JSM_PROJECT_KEY`` must hold the key of a service-desk project on that
    site; the test asserts on whatever requests exist in it, so any project
    with at least one raised request passes.
    """
    project_key = os.environ.get("JSM_PROJECT_KEY")
    if not project_key:
        pytest.skip("JSM_PROJECT_KEY is not set; no service desk to index")

    connector = JiraServiceManagementConnector(
        jira_base_url="https://danswerai.atlassian.net",
        project_key=project_key,
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    connector.validate_connector_settings()
    return connector


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jira_service_management_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0
    for doc in docs:
        assert isinstance(doc, Document)
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.id.startswith(jsm_connector.jira_base)
        # Every JSM request is a Jira issue in the configured project.
        assert doc.metadata["project"] == jsm_connector.jira_project


def test_jira_service_management_connector_slim(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    slim_docs = [
        slim_doc
        for batch in jsm_connector.retrieve_all_slim_docs(
            start=0,
            end=time.time(),
        )
        for slim_doc in batch
        if isinstance(slim_doc, SlimDocument)
    ]

    assert len(slim_docs) > 0
    for slim_doc in slim_docs:
        assert slim_doc.id.startswith(jsm_connector.jira_base)
