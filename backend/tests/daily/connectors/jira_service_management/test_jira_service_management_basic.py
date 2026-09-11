"""Daily (live-credentials) test for the Jira Service Management connector.

Setup guide (needed before this test can run):

1. In the same Jira/Atlassian site used for `TestSecret.JIRA_BASE_URL`
   (see backend/tests/daily/connectors/jira/test_jira_basic.py), create a
   Jira Service Management project — e.g. key `JSM`, type "IT Service
   Management" or "Service Desk". A blank JSM project comes with sample
   requests, or add a couple of test tickets yourself.
2. Store the project key as `TestSecret.JIRA_SERVICE_MANAGEMENT_PROJECT_KEY`
   in AWS Secrets Manager under `test/jira-service-management-project-key`.
3. Replace `_JIRA_BASE_URL` below with the real base URL (or wire it to
   `TestSecret.JIRA_BASE_URL` once that secret is confirmed populated —
   the existing Jira daily test hardcodes it directly rather than reading
   the secret, so this mirrors that same precedent rather than assuming).

This intentionally does NOT assert exact ticket content the way
test_jira_basic.py does (that file's assertions were written against a
known, pre-existing Onyx test project this contribution doesn't have access
to). These assertions check connector *behavior* — real tickets come back,
they're tagged with the right DocumentSource, and pointing the connector at
a non-service-desk project is rejected — which holds regardless of what's
actually in the test JSM project.
"""

import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
    TestSecret.JIRA_SERVICE_MANAGEMENT_PROJECT_KEY,
)

# See setup guide above — must point at a real Atlassian site.
_JIRA_BASE_URL = "https://danswerai.atlassian.net"


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=_JIRA_BASE_URL,
        project_key=test_secrets[TestSecret.JIRA_SERVICE_MANAGEMENT_PROJECT_KEY],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    return connector


def test_jira_service_management_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jsm_connector.validate_connector_settings()

    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0, (
        "No tickets returned — the configured JSM project needs at least "
        "one request/ticket for this test to mean anything."
    )
    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.id.startswith(_JIRA_BASE_URL)
        assert len(doc.sections) >= 1


def test_jira_service_management_rejects_non_service_desk_project(
    test_secrets: dict[TestSecret, str],
) -> None:
    """Pointing the connector at a plain Jira project (not a service desk
    project) must fail validation with a clear error, not silently index
    the wrong content. Uses the existing Jira daily-test project ("AS")
    as a known non-service-desk project on the same site."""
    connector = JiraServiceManagementConnector(
        jira_base_url=_JIRA_BASE_URL,
        project_key="AS",
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )

    with pytest.raises(
        ConnectorValidationError, match="not a Jira Service Management project"
    ):
        connector.validate_connector_settings()
