"""Daily tests for the Jira Service Management connector.

These run against the shared Jira test site with the same credentials as the
Jira daily tests. The pinned test indexes project ``JSM_PROJECT_KEY``, which must
contain at least one issue. The auto-scoped test needs at least one Service
Management (service desk) project on the site and is skipped when none is
visible, so a site without one does not break the shared daily run.
"""

import time
from unittest.mock import patch

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
)

JIRA_BASE_URL = "https://danswerai.atlassian.net"
# Project the pinned test indexes. Adjust this if the site uses a different key.
JSM_PROJECT_KEY = "SUP"


def _make_connector(
    test_secrets: dict[TestSecret, str],
    project_key: str | None,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=JIRA_BASE_URL,
        project_key=project_key,
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    return connector


@pytest.fixture
def jsm_connector_pinned(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    return _make_connector(test_secrets, project_key=JSM_PROJECT_KEY)


@pytest.fixture
def jsm_connector_auto_scoped(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    return _make_connector(test_secrets, project_key=None)


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_pinned_project(
    reset: None,  # noqa: ARG001
    jsm_connector_pinned: JiraServiceManagementConnector,
) -> None:
    jsm_connector_pinned.validate_connector_settings()

    docs = load_all_from_connector(
        connector=jsm_connector_pinned,
        start=0,
        end=time.time(),
    ).documents

    assert docs
    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.id.startswith(f"{JIRA_BASE_URL}/browse/{JSM_PROJECT_KEY}-")


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_auto_scopes_to_service_desks(
    reset: None,  # noqa: ARG001
    jsm_connector_auto_scoped: JiraServiceManagementConnector,
) -> None:
    service_desk_keys = jsm_connector_auto_scoped._get_service_desk_project_keys()
    if not service_desk_keys:
        pytest.skip("no Jira Service Management project on the test site")
    jsm_connector_auto_scoped.validate_connector_settings()

    docs = load_all_from_connector(
        connector=jsm_connector_auto_scoped,
        start=0,
        end=time.time(),
    ).documents

    assert docs
    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        issue_key = doc.id.rsplit("/browse/", 1)[1]
        assert issue_key.split("-", 1)[0] in service_desk_keys
