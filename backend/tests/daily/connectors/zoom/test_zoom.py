import time
from datetime import date, timedelta

import pytest

from onyx.connectors.models import Document
from onyx.connectors.zoom.client import MAX_LISTING_PAGES, ZoomClient
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


def _secret(test_secrets: dict[TestSecret, str], name: TestSecret) -> str:
    # get_secrets drops whatever it cannot resolve, so an unavailable secret
    # shows up as a missing key rather than an error.
    if name not in test_secrets:
        pytest.skip(f"{name.value} is not available")
    return test_secrets[name]


def _authenticated(
    connector: ZoomConnector, test_secrets: dict[TestSecret, str]
) -> ZoomConnector:
    connector.load_credentials(
        {
            "zoom_account_id": _secret(test_secrets, TestSecret.ZOOM_ACCOUNT_ID),
            "zoom_client_id": _secret(test_secrets, TestSecret.ZOOM_CLIENT_ID),
            "zoom_client_secret": _secret(test_secrets, TestSecret.ZOOM_CLIENT_SECRET),
        }
    )
    return connector


@pytest.fixture
def zoom_connector(
    test_secrets: dict[TestSecret, str],
) -> ZoomConnector:
    return _authenticated(
        ZoomConnector(
            meeting_ids=[_secret(test_secrets, TestSecret.ZOOM_TEST_MEETING_ID)]
        ),
        test_secrets,
    )


@pytest.fixture
def zoom_webinar_connector(
    test_secrets: dict[TestSecret, str],
) -> ZoomConnector:
    # The account behind these secrets needs the Webinar add-on, or every
    # webinar call fails whatever the scopes are.
    return _authenticated(
        ZoomConnector(
            webinar_ids=[_secret(test_secrets, TestSecret.ZOOM_TEST_WEBINAR_ID)]
        ),
        test_secrets,
    )


@pytest.fixture
def zoom_host_connector(
    test_secrets: dict[TestSecret, str],
) -> ZoomConnector:
    return _authenticated(
        ZoomConnector(
            host_emails=[_secret(test_secrets, TestSecret.ZOOM_TEST_HOST_EMAIL)]
        ),
        test_secrets,
    )


@pytest.fixture
def zoom_group_connector(
    test_secrets: dict[TestSecret, str],
) -> ZoomConnector:
    return _authenticated(
        ZoomConnector(group_id=_secret(test_secrets, TestSecret.ZOOM_TEST_GROUP_ID)),
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
    # Polling from 0 asks Zoom for everything since the epoch, so this runs the
    # full historical backfill rather than a narrow poll window.
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


# Wider than both the one-month cap folklore attributes to this endpoint and
# the three-month range its own reference example uses.
_MULTI_MONTH_LOOKBACK = timedelta(days=400)


def _zoom_client(test_secrets: dict[TestSecret, str]) -> ZoomClient:
    return ZoomClient(
        account_id=_secret(test_secrets, TestSecret.ZOOM_ACCOUNT_ID),
        client_id=_secret(test_secrets, TestSecret.ZOOM_CLIENT_ID),
        client_secret=_secret(test_secrets, TestSecret.ZOOM_CLIENT_SECRET),
    )


def _user_id_for(client: ZoomClient, email: str) -> str:
    wanted = email.strip().lower()
    page_token: str | None = None
    seen_tokens: set[str] = set()

    for _ in range(MAX_LISTING_PAGES):
        page = client.list_users(page_token=page_token)
        for user in page.users:
            if (user.email or "").strip().lower() == wanted and user.id:
                return user.id

        page_token = page.next_page_token
        if not page_token:
            raise AssertionError(f"No active Zoom user has the email {email}")
        if page_token in seen_tokens:
            raise AssertionError(
                f"Zoom stopped advancing the user cursor while looking for {email}"
            )
        seen_tokens.add(page_token)

    raise AssertionError(
        f"Zoom kept paging users past {MAX_LISTING_PAGES} pages looking for {email}"
    )


def test_recording_listing_accepts_a_multi_month_range(
    test_secrets: dict[TestSecret, str],
) -> None:
    """The connector sends the whole poll window in one call, and a first sync
    polls from the epoch. Zoom's reference puts "Maximum duration: 1 month" on
    the Reports and analytics endpoints, never on this one, and documents no 400
    for it at all. This test is what catches Zoom ever changing that.
    """
    client = _zoom_client(test_secrets)
    user_id = _user_id_for(
        client, _secret(test_secrets, TestSecret.ZOOM_TEST_HOST_EMAIL)
    )

    to_date = date.today()
    page = client.list_user_recordings(
        user_id=user_id,
        from_date=to_date - _MULTI_MONTH_LOOKBACK,
        to_date=to_date,
    )

    # The test account's recordings come and go, so Zoom accepting the range is
    # the whole result.
    assert isinstance(page.recordings, list)
