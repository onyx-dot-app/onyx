from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.gmail.connector import GmailConnector
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument


_THREAD_1_START_TIME = 1730568700
_THREAD_1_END_TIME = 1730569000

"""
This thread was 4 emails long:
    admin@onyx-test.com -> test-group-1@onyx-test.com (conaining test_user_1 and test_user_2)
    test_user_1@onyx-test.com -> admin@onyx-test.com
    admin@onyx-test.com -> test_user_2@onyx-test.com + BCC: test_user_3@onyx-test.com
    test_user_3@onyx-test.com -> admin@onyx-test.com
"""
_THREAD_1_BY_ID: dict[str, dict[str, Any]] = {
    "192edefb315737c3": {
        "email": "admin@onyx-test.com",
        "sections_count": 4,
        "primary_owners": set(
            [
                "admin@onyx-test.com",
                "test_user_1@onyx-test.com",
                "test_user_3@onyx-test.com",
            ]
        ),
        "secondary_owners": set(
            [
                "test-group-1@onyx-test.com",
                "admin@onyx-test.com",
                "test_user_2@onyx-test.com",
                "test_user_3@onyx-test.com",
            ]
        ),
    },
    "192edf020d2f5def": {
        "email": "test_user_1@onyx-test.com",
        "sections_count": 2,
        "primary_owners": set(["admin@onyx-test.com", "test_user_1@onyx-test.com"]),
        "secondary_owners": set(["test-group-1@onyx-test.com", "admin@onyx-test.com"]),
    },
    "192edf020ae90aab": {
        "email": "test_user_2@onyx-test.com",
        "sections_count": 2,
        "primary_owners": set(["admin@onyx-test.com"]),
        "secondary_owners": set(
            ["test-group-1@onyx-test.com", "test_user_2@onyx-test.com"]
        ),
    },
    "192edf18316015fa": {
        "email": "test_user_3@onyx-test.com",
        "sections_count": 2,
        "primary_owners": set(["admin@onyx-test.com", "test_user_3@onyx-test.com"]),
        "secondary_owners": set(
            [
                "admin@onyx-test.com",
                "test_user_2@onyx-test.com",
                "test_user_3@onyx-test.com",
            ]
        ),
    },
}


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_slim_docs_retrieval(
    mock_get_api_key: MagicMock,
    google_gmail_service_acct_connector_factory: Callable[..., GmailConnector],
) -> None:
    print("\n\nRunning test_slim_docs_retrieval")
    connector = google_gmail_service_acct_connector_factory()
    retrieved_slim_docs: list[SlimDocument] = []
    for doc_batch in connector.retrieve_all_slim_docs_perm_sync(
        _THREAD_1_START_TIME, _THREAD_1_END_TIME
    ):
        retrieved_slim_docs.extend(doc_batch)

    assert len(retrieved_slim_docs) == 4

    for doc in retrieved_slim_docs:
        assert doc.external_access is not None
        assert len(doc.external_access.external_user_emails) == 1
        user_email = next(iter(doc.external_access.external_user_emails))
        assert _THREAD_1_BY_ID[doc.id]["email"] == user_email


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_docs_retrieval(
    mock_get_api_key: MagicMock,
    google_gmail_service_acct_connector_factory: Callable[..., GmailConnector],
) -> None:
    print("\n\nRunning test_docs_retrieval")
    connector = google_gmail_service_acct_connector_factory()
    retrieved_docs: list[Document] = []
    for doc_batch in connector.poll_source(_THREAD_1_START_TIME, _THREAD_1_END_TIME):
        retrieved_docs.extend(doc_batch)

    assert len(retrieved_docs) == 4

    for doc in retrieved_docs:
        id = doc.id
        retrieved_primary_owner_emails: set[str | None] = set()
        retrieved_secondary_owner_emails: set[str | None] = set()
        if doc.primary_owners:
            retrieved_primary_owner_emails = set(
                [owner.email for owner in doc.primary_owners]
            )
        if doc.secondary_owners:
            retrieved_secondary_owner_emails = set(
                [owner.email for owner in doc.secondary_owners]
            )
        assert _THREAD_1_BY_ID[id]["sections_count"] == len(doc.sections)
        assert _THREAD_1_BY_ID[id]["primary_owners"] == retrieved_primary_owner_emails
        assert (
            _THREAD_1_BY_ID[id]["secondary_owners"] == retrieved_secondary_owner_emails
        )
