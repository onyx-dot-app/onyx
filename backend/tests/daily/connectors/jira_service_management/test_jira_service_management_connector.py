import os
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


def _make_connector(
    test_secrets: dict[TestSecret, str],
    project_key: str,
    include_internal_comments: bool = False,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=test_secrets[TestSecret.JIRA_BASE_URL],
        project_key=project_key,
        include_internal_comments=include_internal_comments,
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    return connector


@pytest.fixture
def jsm_project_key() -> str:
    project_key = os.environ.get("JSM_PROJECT_KEY")
    if not project_key:
        pytest.skip("JSM_PROJECT_KEY not set in environment")
    return project_key


def test_jsm_connector_basic(
    reset: None,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
    jsm_project_key: str,
) -> None:
    connector = _make_connector(test_secrets, jsm_project_key)
    connector.validate_connector_settings()

    docs = load_all_from_connector(
        connector=connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0
    for doc in docs:
        assert isinstance(doc, Document)
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.id.startswith(
            f"{test_secrets[TestSecret.JIRA_BASE_URL].rstrip('/')}/browse/"
        )
        assert doc.id.split("/browse/")[-1].startswith(f"{jsm_project_key}-")
        assert doc.metadata["project"] == jsm_project_key


def test_jsm_connector_poll(
    reset: None,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
    jsm_project_key: str,
) -> None:
    connector = _make_connector(test_secrets, jsm_project_key)

    now = time.time()
    one_day_ago = now - 24 * 60 * 60
    docs = load_all_from_connector(
        connector=connector,
        start=one_day_ago,
        end=now,
    ).documents

    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.doc_updated_at is not None
        assert one_day_ago - 60 <= doc.doc_updated_at.timestamp() <= now + 60


def test_jsm_connector_slim_docs(
    reset: None,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
    jsm_project_key: str,
) -> None:
    """The slim listing (pruning) returns the same ticket ids as the index."""
    connector = _make_connector(test_secrets, jsm_project_key)

    docs = load_all_from_connector(
        connector=connector,
        start=0,
        end=time.time(),
    ).documents
    slim_ids = {
        slim_doc.id
        for batch in connector.retrieve_all_slim_docs(start=0, end=time.time())
        for slim_doc in batch
        if isinstance(slim_doc, SlimDocument)
    }
    indexed_ids = {doc.id for doc in docs}
    assert indexed_ids
    assert indexed_ids <= slim_ids
