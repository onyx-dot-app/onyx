import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
    TestSecret.JIRA_API_TOKEN_SCOPED,
)


def _make_connector(
    test_secrets: dict[TestSecret, str],
    scoped_token: bool = False,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://danswerai.atlassian.net",
        project_key="AS",
        comment_email_blacklist=[],
        scoped_token=scoped_token,
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": (
                test_secrets[TestSecret.JIRA_API_TOKEN_SCOPED]
                if scoped_token
                else test_secrets[TestSecret.JIRA_API_TOKEN]
            ),
        }
    )
    return connector


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    return _make_connector(test_secrets)


@pytest.fixture
def jsm_connector_scoped(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    return _make_connector(test_secrets, scoped_token=True)


def test_jsm_basic_load(
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
        assert doc.id.startswith("https://danswerai.atlassian.net")
