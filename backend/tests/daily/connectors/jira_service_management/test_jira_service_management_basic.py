import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management import JiraServiceManagementConnector
from onyx.connectors.models import Document, SlimDocument
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_BASE_URL,
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
)

_NO_VISIBLE_DESK = "No Jira Service Management service desk is visible"


def _service_desk_ids() -> list[str] | None:
    raw = os.environ.get("JIRA_SERVICE_DESK_IDS", "")
    ids = [value.strip() for value in raw.split(",") if value.strip()]
    return ids or None


def _make_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=test_secrets[TestSecret.JIRA_BASE_URL].strip(),
        service_desk_ids=_service_desk_ids(),
        project_key=os.environ.get("JIRA_SERVICE_MANAGEMENT_PROJECT_KEY") or None,
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    return connector


def _skip_if_fixture_has_no_desks(error: ConnectorValidationError) -> None:
    if _NO_VISIBLE_DESK in str(error):
        pytest.skip("The Jira test site has no service desk visible to the account.")
    raise error


def test_jira_service_management_connector(
    test_secrets: dict[TestSecret, str],
) -> None:
    connector = _make_connector(test_secrets)
    documents: list[Document] = []
    slim_ids: set[str] = set()
    try:
        connector.validate_connector_settings()
        for batch in connector.load_from_state():
            documents.extend(item for item in batch if isinstance(item, Document))
        slim_ids = {
            item.id
            for batch in connector.retrieve_all_slim_docs(start=0, end=time.time())
            for item in batch
            if isinstance(item, SlimDocument)
        }
    except ConnectorValidationError as error:
        _skip_if_fixture_has_no_desks(error)

    assert documents, "The service desk scope returned no requests."
    assert slim_ids, "The service desk scope returned no slim documents."

    base_url = test_secrets[TestSecret.JIRA_BASE_URL].strip().rstrip("/")
    for document in documents:
        assert document.source is DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert document.metadata["key"]
        assert document.metadata["project"]
        assert document.metadata["jsm_service_desk_id"]
        assert document.id == f"{base_url}/browse/{document.metadata['key']}"

    assert {document.id for document in documents} <= slim_ids
