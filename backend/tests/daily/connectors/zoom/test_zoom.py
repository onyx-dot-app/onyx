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
    TestSecret.ZOOM_TEST_HOST_EMAIL,
    TestSecret.ZOOM_TEST_GROUP_ID,
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


@pytest.fixture
def zoom_host_connector(
    test_secrets: dict[TestSecret, str],
) -> ZoomConnector:
    return _authenticated(
        ZoomConnector(host_emails=[test_secrets[TestSecret.ZOOM_TEST_HOST_EMAIL]]),
        test_secrets,
    )


@pytest.fixture
def zoom_group_connector(
    test_secrets: dict[TestSecret, str],
) -> ZoomConnector:
    return _authenticated(
        ZoomConnector(group_id=test_secrets[TestSecret.ZOOM_TEST_GROUP_ID]),
        test_secrets,
    )


def _documents(connector: ZoomConnector) -> list[Document]:
    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())
    return [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]


def test_zoom_basic(zoom_connector: ZoomConnector) -> None:
    docs = _documents(zoom_connector)

    # Not ==1: if the configured meeting recurs, every recorded occurrence
    # produces its own document.
    assert len(docs) >= 1
    assert all(doc.id.startswith("ZOOM_MEETING_") for doc in docs)
    assert all(doc.metadata == {"session_type": "meeting"} for doc in docs)
    assert all(doc.sections[0].text for doc in docs)


def test_zoom_webinar(zoom_webinar_connector: ZoomConnector) -> None:
    docs = _documents(zoom_webinar_connector)

    assert len(docs) >= 1
    assert all(doc.id.startswith("ZOOM_WEBINAR_") for doc in docs)
    assert all(doc.metadata == {"session_type": "webinar"} for doc in docs)
    assert all(doc.sections[0].text for doc in docs)


def test_zoom_host_allowlist(zoom_host_connector: ZoomConnector) -> None:
    # Polling from 0 asks Zoom for everything since the epoch, so this test is
    # also what settles whether the endpoint's rumoured one-month range cap is
    # real. Zoom's own reference does not mention it.
    docs = _documents(zoom_host_connector)

    assert len(docs) >= 1
    assert all(doc.id.startswith(("ZOOM_MEETING_", "ZOOM_WEBINAR_")) for doc in docs)
    assert all(doc.metadata["session_type"] in ("meeting", "webinar") for doc in docs)
    assert all(doc.sections[0].text for doc in docs)


def test_zoom_group_discovery(zoom_group_connector: ZoomConnector) -> None:
    docs = _documents(zoom_group_connector)

    assert len(docs) >= 1
    assert all(doc.id.startswith(("ZOOM_MEETING_", "ZOOM_WEBINAR_")) for doc in docs)
    assert all(doc.sections[0].text for doc in docs)
