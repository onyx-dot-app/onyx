"""Daily test for the Jira Service Management connector.

Setup guide for the test environment:

1. Create or reuse a Jira Cloud site that includes Jira Service Management
   (e.g. https://danswerai.atlassian.net). The free JSM tier is enough.
2. Create a service desk project and note its project key (e.g. `HELP`).
   Seed it with at least one customer request that has a comment.
3. Create an Atlassian API token for the test user:
   https://id.atlassian.com/manage-profile/security/api-tokens
4. Provide the secrets used below (JIRA_BASE_URL must point at the site that
   hosts the JSM project).
"""

import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document, SlimDocument
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_BASE_URL,
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
)

JSM_PROJECT_KEY = "HELP"


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=test_secrets[TestSecret.JIRA_BASE_URL],
        project_key=JSM_PROJECT_KEY,
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    return connector


def test_jsm_fetch_all(
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


def test_jsm_slim_docs(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    slim_docs = [
        slim_doc
        for batch in jsm_connector.retrieve_all_slim_docs(start=0)
        for slim_doc in batch
        if isinstance(slim_doc, SlimDocument)
    ]
    assert len(slim_docs) > 0
    for slim_doc in slim_docs:
        assert slim_doc.id.startswith(jsm_connector.jira_base)
