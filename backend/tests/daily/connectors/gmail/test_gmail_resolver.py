"""Tests for GmailConnector.reindex against the real Gmail test workspace.

The test window holds one email thread seen from four mailboxes (admin,
test_user_1, test_user_2, test_user_3). Each mailbox has its own thread id.
"""

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.gmail.connector import GmailConnector
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
)
from tests.utils.secret_names import TestSecret

_THREAD_1_START_TIME = 1730568700
_THREAD_1_END_TIME = 1730569000
_ADMIN_EMAIL = "admin@onyx-test.com"
# Well formed, but no mailbox has it.
_BOGUS_THREAD_ID = "ffffffffffffffff"


def _owner_by_thread_id(connector: GmailConnector) -> dict[str, str]:
    """List the window's thread ids with the mailbox that holds each one."""
    owners: dict[str, str] = {}
    for batch in connector.retrieve_all_slim_docs_perm_sync(
        _THREAD_1_START_TIME, _THREAD_1_END_TIME
    ):
        for doc in batch:
            if isinstance(doc, HierarchyNode):
                continue
            assert doc.external_access is not None
            owners[doc.id] = next(iter(doc.external_access.external_user_emails))
    return owners


def _build_failures(
    thread_ids: list[str], document_link: str | None = None
) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=thread_id, document_link=document_link
            ),
            failure_message=f"Synthetic failure for {thread_id}",
        )
        for thread_id in thread_ids
    ]


def _split(
    results: list[Document | ConnectorFailure | HierarchyNode],
) -> tuple[list[Document], list[ConnectorFailure]]:
    assert not any(isinstance(r, HierarchyNode) for r in results)
    docs = [r for r in results if isinstance(r, Document)]
    failures = [r for r in results if isinstance(r, ConnectorFailure)]
    return docs, failures


@pytest.fixture
def service_acct_connector(
    google_gmail_service_acct_connector_factory: Callable[..., GmailConnector],
) -> GmailConnector:
    return google_gmail_service_acct_connector_factory()


@pytest.mark.secrets(TestSecret.GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR)
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_single_thread(
    mock_api_key: MagicMock,  # noqa: ARG001
    service_acct_connector: GmailConnector,
) -> None:
    owners = _owner_by_thread_id(service_acct_connector)
    # Pick a thread outside the admin's mailbox: the id alone must be enough
    # to find its mailbox.
    target = next(tid for tid, email in owners.items() if email != _ADMIN_EMAIL)

    docs, failures = _split(
        list(service_acct_connector.reindex(_build_failures([target])))
    )

    assert failures == []
    assert [d.id for d in docs] == [target]
    assert docs[0].external_access is not None
    assert docs[0].external_access.external_user_emails == {owners[target]}
    assert docs[0].sections


@pytest.mark.secrets(TestSecret.GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR)
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_multiple_threads_across_mailboxes(
    mock_api_key: MagicMock,  # noqa: ARG001
    service_acct_connector: GmailConnector,
) -> None:
    owners = _owner_by_thread_id(service_acct_connector)
    assert len(set(owners.values())) >= 2, "Test window must span several mailboxes"

    docs, failures = _split(
        list(service_acct_connector.reindex(_build_failures(list(owners))))
    )

    assert failures == []
    assert {
        d.id: next(iter(d.external_access.external_user_emails))
        for d in docs
        if d.external_access
    } == owners


@pytest.mark.secrets(TestSecret.GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR)
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_uses_mailbox_from_crawl_failure_link(
    mock_api_key: MagicMock,  # noqa: ARG001
    service_acct_connector: GmailConnector,
) -> None:
    """A crawl failure links to its mailbox; reindex goes there first."""
    owners = _owner_by_thread_id(service_acct_connector)
    target, owner = next(
        (tid, email) for tid, email in owners.items() if email != _ADMIN_EMAIL
    )
    link = f"https://mail.google.com/mail/u/{owner}/#all/{target}"

    docs, failures = _split(
        list(service_acct_connector.reindex(_build_failures([target], link)))
    )

    assert failures == []
    assert [d.id for d in docs] == [target]


@pytest.mark.secrets(TestSecret.GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR)
def test_reindex_unknown_thread_yields_failure(
    service_acct_connector: GmailConnector,
) -> None:
    docs, failures = _split(
        list(service_acct_connector.reindex(_build_failures([_BOGUS_THREAD_ID])))
    )

    assert docs == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == _BOGUS_THREAD_ID


@pytest.mark.secrets(TestSecret.GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR)
def test_reindex_unparseable_id_yields_failure(
    service_acct_connector: GmailConnector,
) -> None:
    weird = "not-a-thread-id"

    docs, failures = _split(
        list(service_acct_connector.reindex(_build_failures([weird])))
    )

    assert docs == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == weird


@pytest.mark.secrets(TestSecret.GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR)
def test_reindex_empty_errors(service_acct_connector: GmailConnector) -> None:
    assert list(service_acct_connector.reindex([])) == []


@pytest.mark.secrets(TestSecret.GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR)
def test_reindex_entity_failures_are_skipped(
    service_acct_connector: GmailConnector,
) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="some_user"),
        failure_message="retrieval failure",
    )

    assert list(service_acct_connector.reindex([entity])) == []


@pytest.mark.secrets(TestSecret.GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR)
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_with_permissions_sets_external_access(
    mock_api_key: MagicMock,  # noqa: ARG001
    service_acct_connector: GmailConnector,
) -> None:
    owners = _owner_by_thread_id(service_acct_connector)

    docs, failures = _split(
        list(
            service_acct_connector.reindex(
                _build_failures(list(owners)), include_permissions=True
            )
        )
    )

    assert failures == []
    assert {d.id for d in docs} == set(owners)
    for doc in docs:
        assert doc.external_access is not None
        assert not doc.external_access.is_public
        assert doc.external_access.external_user_emails == {owners[doc.id]}


@pytest.mark.secrets(
    TestSecret.GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON_STR,
    TestSecret.GOOGLE_GMAIL_OAUTH_CREDENTIALS_JSON_STR,
)
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_oauth_reads_only_the_admin_mailbox(
    mock_api_key: MagicMock,  # noqa: ARG001
    service_acct_connector: GmailConnector,
    google_gmail_oauth_connector_factory: Callable[..., GmailConnector],
) -> None:
    """OAuth reads one mailbox. Threads of other mailboxes are out of scope."""
    owners = _owner_by_thread_id(service_acct_connector)
    admin_thread = next(tid for tid, email in owners.items() if email == _ADMIN_EMAIL)
    other_thread = next(tid for tid, email in owners.items() if email != _ADMIN_EMAIL)
    try:
        oauth_connector = google_gmail_oauth_connector_factory()
    except PermissionError as e:
        # The stored token must carry the gmail.readonly scope.
        pytest.skip(f"Gmail OAuth test credential does not load: {e}")

    docs, failures = _split(
        list(oauth_connector.reindex(_build_failures([admin_thread, other_thread])))
    )

    assert [d.id for d in docs] == [admin_thread]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == other_thread
