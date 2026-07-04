import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.monday.connector import MondayConnector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.MONDAY_API_TOKEN)


def _load_all_documents(connector: MondayConnector) -> list[Document]:
    documents: list[Document] = []
    for batch in connector.load_from_state():
        documents.extend(batch)
    return documents


def _poll_documents(
    connector: MondayConnector,
    start: float,
    end: float,
) -> list[Document]:
    documents: list[Document] = []
    for batch in connector.poll_source(start, end):
        documents.extend(batch)
    return documents


@pytest.fixture
def monday_connector(test_secrets: dict[TestSecret, str]) -> MondayConnector:
    connector = MondayConnector()
    connector.load_credentials(
        {"monday_api_token": test_secrets[TestSecret.MONDAY_API_TOKEN]}
    )
    connector.validate_connector_settings()
    return connector


def test_monday_connector_basic(monday_connector: MondayConnector) -> None:
    docs = _load_all_documents(monday_connector)
    assert len(docs) > 0

    for doc in docs:
        assert doc.id
        assert doc.semantic_identifier
        assert doc.source == DocumentSource.MONDAY
        assert doc.doc_updated_at is not None
        assert doc.metadata.get("board_name")
        assert len(doc.sections) >= 1
        assert doc.sections[0].link
        assert "monday.com" in doc.sections[0].link or doc.id.startswith("monday__")


def test_monday_connector_poll_window(monday_connector: MondayConnector) -> None:
    now = datetime.now(tz=timezone.utc)
    recent_start = (now - timedelta(hours=1)).timestamp()
    recent_end = now.timestamp()

    recent_docs = _poll_documents(monday_connector, recent_start, recent_end)

    old_end = (now - timedelta(days=30)).timestamp()
    old_start = (now - timedelta(days=31)).timestamp()
    old_docs = _poll_documents(monday_connector, old_start, old_end)

    for doc in recent_docs:
        assert doc.doc_updated_at is not None
        assert recent_start <= doc.doc_updated_at.timestamp() <= recent_end

    for doc in old_docs:
        assert doc.doc_updated_at is not None
        assert doc.doc_updated_at.timestamp() < recent_start
