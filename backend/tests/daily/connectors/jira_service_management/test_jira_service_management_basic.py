"""Daily test for the Jira Service Management connector.

Follows the connectors README: daily tests live under
``backend/tests/daily/connectors/<source>/`` and run against a live source.
This one needs a Jira Cloud site with a JSM project that holds at least one
request with a public comment.

Credentials and the site URL come from the shared secret resolution
(``test_secrets``: process env, then ``.vscode/.env``, then AWS Secrets
Manager — see ``backend/tests/utils/aws_secrets.py``). The service project
key is configuration, not a credential: set ``JSM_TEST_PROJECT_KEY`` in the
environment; the test skips when it is unset.
"""

import os
import time
from collections.abc import Iterable

import pytest

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_BASE_URL,
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
)


def _project_key() -> str:
    project_key = os.environ.get("JSM_TEST_PROJECT_KEY")
    if not project_key:
        pytest.skip("JSM_TEST_PROJECT_KEY is not set")
    return project_key


def _flatten(batches: Iterable[list[Document]]) -> list[Document]:
    return [doc for batch in batches for doc in batch]


@pytest.fixture(scope="module")
def connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    conn = JiraServiceManagementConnector(
        jira_base_url=test_secrets[TestSecret.JIRA_BASE_URL],
        project_key=_project_key(),
    )
    conn.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    return conn


def test_validate_settings(connector: JiraServiceManagementConnector) -> None:
    connector.validate_connector_settings()


def test_load_from_state_returns_seeded_request(
    connector: JiraServiceManagementConnector,
) -> None:
    docs = _flatten(connector.load_from_state())
    assert len(docs) >= 1
    doc = docs[0]
    assert doc.semantic_identifier.startswith(_project_key())
    assert doc.metadata.get("request_type")
    assert doc.metadata.get("status")


def test_poll_source_recent_window(
    connector: JiraServiceManagementConnector,
) -> None:
    now = time.time()
    docs = _flatten(connector.poll_source(now - 7 * 24 * 3600, now + 24 * 3600))
    assert len(docs) >= 1


def test_slim_docs_match_full_docs(
    connector: JiraServiceManagementConnector,
) -> None:
    full_ids = {doc.id for doc in _flatten(connector.load_from_state())}
    slim_ids = {
        slim.id for batch in connector.retrieve_all_slim_docs() for slim in batch
    }
    assert slim_ids == full_ids
