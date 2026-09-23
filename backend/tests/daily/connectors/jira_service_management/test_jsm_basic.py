import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
    TestSecret.JIRA_API_TOKEN_SCOPED,
)

# Key of a service-desk project on the shared test Jira instance.
JSM_PROJECT_KEY_ENV_VAR = "JSM_TEST_PROJECT_KEY"


def _make_connector(
    test_secrets: dict[TestSecret, str],
    scoped_token: bool = False,
) -> JiraServiceManagementConnector:
    project_key = os.environ.get(JSM_PROJECT_KEY_ENV_VAR)
    connector = JiraServiceManagementConnector(
        jira_base_url="https://danswerai.atlassian.net",
        project_key=project_key or "",
        comment_email_blacklist=[],
        scoped_token=scoped_token,
        include_attachments=True,
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


def test_jsm_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    if not os.environ.get(JSM_PROJECT_KEY_ENV_VAR):
        pytest.skip(
            f"{JSM_PROJECT_KEY_ENV_VAR} not set; no service desk project is "
            "configured on the test Jira instance"
        )
    jsm_connector.validate_connector_settings()

    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0
    assert all(doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT for doc in docs)
    # Attachment documents don't carry the "project" key; the scoping property
    # only applies to issue documents.
    issue_docs = [doc for doc in docs if "project" in doc.metadata]
    assert len(issue_docs) > 0
    assert all(
        doc.metadata["project"] == jsm_connector.jira_project for doc in issue_docs
    )
