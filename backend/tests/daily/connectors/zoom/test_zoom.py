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
    TestSecret.ZOOM_TEST_WEBINAR_ID,
)


def _authenticated(
    connector: ZoomConnector, test_secrets: dict[TestSecret, str]
) -> ZoomConnector:
    connector.load_credentials(
        {
            "zoom_account_id": test_secrets[TestSecret.ZOOM_ACCOUNT_ID],
            "zoom_client_id": test_secrets[TestSecret.ZOOM_CLIENT_ID],
            "zoom_client_secret": test_secrets[TestSecret.ZOOM_CLIENT_SECRET],
        }
    )
    return connector


@pytest.fixture
def zoom_connector(
    test_secrets: dict[TestSecret, str],
) -> ZoomConnector:
    return _authenticated(
        ZoomConnector(meeting_ids=[test_secrets[TestSecret.ZOOM_TEST_MEETING_ID]]),
        test_secrets,
    )


@pytest.fixture
def zoom_webinar_connector(
    test_secrets: dict[TestSecret, str],
) -> ZoomConnector:
    # The account behind these secrets needs the Webinar add-on, or every
    # webinar call fails whatever the scopes are.
    return _authenticated(
        ZoomConnector(webinar_ids=[test_secrets[TestSecret.ZOOM_TEST_WEBINAR_ID]]),
        test_secrets,
    )


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


def test_zoom_webinar(zoom_webinar_connector: ZoomConnector) -> None:
    outputs = load_everything_from_checkpoint_connector(
        zoom_webinar_connector, 0, time.time()
    )
    docs = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    assert len(docs) >= 1
    assert all(doc.id.startswith("ZOOM_WEBINAR_") for doc in docs)
    assert all(doc.metadata == {"session_type": "webinar"} for doc in docs)
    assert all(doc.sections[0].text for doc in docs)
