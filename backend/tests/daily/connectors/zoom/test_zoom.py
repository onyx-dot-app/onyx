import time

import pytest

from onyx.connectors.models import Document
from onyx.connectors.zoom.connector import ZoomConnector
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.ZOOM_ACCOUNT_ID,
    TestSecret.ZOOM_CLIENT_ID,
    TestSecret.ZOOM_CLIENT_SECRET,
    TestSecret.ZOOM_TEST_MEETING_ID,
)


@pytest.fixture
def zoom_connector(
    test_secrets: dict[TestSecret, str],
) -> ZoomConnector:
    connector = ZoomConnector(
        meeting_ids=[test_secrets[TestSecret.ZOOM_TEST_MEETING_ID]]
    )

    connector.load_credentials(
        {
            "zoom_account_id": test_secrets[TestSecret.ZOOM_ACCOUNT_ID],
            "zoom_client_id": test_secrets[TestSecret.ZOOM_CLIENT_ID],
            "zoom_client_secret": test_secrets[TestSecret.ZOOM_CLIENT_SECRET],
        }
    )

    return connector


def test_zoom_basic(zoom_connector: ZoomConnector) -> None:
    outputs = load_everything_from_checkpoint_connector(zoom_connector, 0, time.time())
    docs = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    # Not ==1: if the configured meeting recurs, every recorded occurrence
    # produces its own document.
    assert len(docs) >= 1
    assert all(doc.id.startswith("ZOOM_MEETING_") for doc in docs)
    assert all(doc.metadata == {"session_type": "meeting"} for doc in docs)
    assert all(doc.sections[0].text for doc in docs)
