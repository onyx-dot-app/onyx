"""Daily (live-API) tests for the Jira Service Management connector.

Requires a real Atlassian site with a JSM project. Set the secrets below
in your daily-test secret store; tests are skipped when they are absent.

    JSM_DOMAIN            e.g. your-site.atlassian.net
    JSM_SERVICE_DESK_ID   numeric ID (Project Settings or the portal URL)
    JIRA_USER_EMAIL       Atlassian account email
    JIRA_API_TOKEN        API token from id.atlassian.com
"""

import time
from datetime import datetime

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JSM_DOMAIN,
    TestSecret.JSM_SERVICE_DESK_ID,
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
)


def _make_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jsm_domain=test_secrets[TestSecret.JSM_DOMAIN],
        service_desk_id=test_secrets[TestSecret.JSM_SERVICE_DESK_ID],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    return connector


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    return _make_connector(test_secrets)


def test_jsm_validation_succeeds(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jsm_connector.validate_connector_settings()


def test_jsm_load_from_state(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    docs = load_all_from_connector(connector=jsm_connector, start=0, end=0).documents
    assert isinstance(docs, list)
    for doc in docs:
        assert isinstance(doc, Document)
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.semantic_identifier
        assert doc.metadata["issue_key"]


def test_jsm_poll_recent_window(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    # A one-week window: small enough to stay cheap, wide enough that most
    # service desks have at least one request fall inside it.
    now = time.time()
    docs: list[Document] = [
        doc
        for batch in jsm_connector.poll_source(now - 7 * 24 * 3600, now)
        for doc in batch
    ]
    for doc in docs:
        assert doc.doc_updated_at is not None
        assert doc.doc_updated_at <= datetime.fromtimestamp(now)
