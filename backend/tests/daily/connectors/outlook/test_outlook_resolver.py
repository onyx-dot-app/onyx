"""Live checks of OutlookConnector.reindex against the shared Microsoft test
tenant. The slim walk lists the real document ids, which reindex reads again."""

import base64
import os

import pytest

from onyx.access.models import ExternalAccess
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
)
from onyx.connectors.outlook.connector import (
    EVENT_DOCUMENT_ID_PREFIX,
    OutlookConnector,
)
from onyx.connectors.outlook.threads import (
    OWN_DOCUMENT_SUFFIX,
    THREAD_DOCUMENT_ID_PREFIX,
)
from onyx.db.enums import HierarchyNodeType
from tests.utils.pytest_secrets import RedactedDict
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.SHAREPOINT_CLIENT_SECRET)

TEST_MAILBOX = "test@danswerai.onmicrosoft.com"
# Keeps the fixture meeting inside the calendar window for years either way.
CALENDAR_WINDOW_DAYS = 3650
# Threads a multi-document reindex reads, so the test stays quick.
MAX_THREADS = 5
# A well-formed thread key no conversation index produces.
BOGUS_KEY = base64.urlsafe_b64encode(b"\x01" + bytes(21)).decode().rstrip("=")


@pytest.fixture(scope="module")
def outlook_credentials(
    test_secrets: dict[TestSecret, str],
) -> RedactedDict[str, str]:
    return RedactedDict(
        {
            "outlook_client_id": os.environ["SHAREPOINT_CLIENT_ID"],
            "outlook_client_secret": test_secrets[TestSecret.SHAREPOINT_CLIENT_SECRET],
            "outlook_directory_id": os.environ["SHAREPOINT_CLIENT_DIRECTORY_ID"],
        }
    )


def _connector(
    credentials: dict[str, str], include_calendar: bool = True
) -> OutlookConnector:
    """A fresh connector, as each targeted reindex job builds one."""
    connector = OutlookConnector(
        mailboxes=[TEST_MAILBOX],
        include_calendar=include_calendar,
        calendar_past_days=CALENDAR_WINDOW_DAYS,
        calendar_future_days=CALENDAR_WINDOW_DAYS,
    )
    connector.load_credentials(credentials)
    return connector


@pytest.fixture(scope="module")
def listed_access(
    outlook_credentials: dict[str, str],
) -> dict[str, ExternalAccess | None]:
    """Every document id the walk writes, with its readers."""
    listed: dict[str, ExternalAccess | None] = {}
    connector = _connector(outlook_credentials)
    for batch in connector.retrieve_all_slim_docs_perm_sync():
        for entry in batch:
            if isinstance(entry, SlimDocument):
                listed[entry.id] = entry.external_access
    return listed


@pytest.fixture(scope="module")
def mailbox_id(outlook_credentials: dict[str, str]) -> str:
    mailbox = _connector(outlook_credentials).ops.resolve_mailbox(address=TEST_MAILBOX)
    assert mailbox is not None
    return mailbox.id


def _thread_ids(listed: dict[str, ExternalAccess | None]) -> list[str]:
    return sorted(
        doc_id
        for doc_id in listed
        if doc_id.startswith(THREAD_DOCUMENT_ID_PREFIX)
        and not doc_id.endswith(OWN_DOCUMENT_SUFFIX)
    )


def _own_ids(listed: dict[str, ExternalAccess | None]) -> list[str]:
    return sorted(doc_id for doc_id in listed if doc_id.endswith(OWN_DOCUMENT_SUFFIX))


def _event_ids(listed: dict[str, ExternalAccess | None]) -> list[str]:
    return sorted(
        doc_id for doc_id in listed if doc_id.startswith(EVENT_DOCUMENT_ID_PREFIX)
    )


def _failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id),
            failure_message=f"Synthetic failure for {doc_id}",
        )
        for doc_id in doc_ids
    ]


def _split(
    results: list[Document | ConnectorFailure | HierarchyNode],
) -> tuple[list[Document], list[ConnectorFailure], list[HierarchyNode]]:
    return (
        [r for r in results if isinstance(r, Document)],
        [r for r in results if isinstance(r, ConnectorFailure)],
        [r for r in results if isinstance(r, HierarchyNode)],
    )


def _failed_ids(failures: list[ConnectorFailure]) -> set[str]:
    return {f.failed_document.document_id for f in failures if f.failed_document}


def test_reindex_one_thread(
    outlook_credentials: dict[str, str],
    listed_access: dict[str, ExternalAccess | None],
) -> None:
    threads = _thread_ids(listed_access)
    assert threads, "The test mailbox must hold at least one thread document"
    target = threads[0]

    docs, failures, nodes = _split(
        list(_connector(outlook_credentials).reindex(_failures([target])))
    )

    assert not failures, [f.failure_message for f in failures]
    assert [d.id for d in docs] == [target]
    assert docs[0].metadata["mailbox"] == TEST_MAILBOX
    assert docs[0].sections and docs[0].sections[0].text
    assert docs[0].external_access is None
    assert any(n.node_type == HierarchyNodeType.MAILBOX for n in nodes)
    node_ids = {n.raw_node_id for n in nodes}
    assert docs[0].parent_hierarchy_raw_node_id in node_ids


def test_reindex_every_document_type(
    outlook_credentials: dict[str, str],
    listed_access: dict[str, ExternalAccess | None],
) -> None:
    events = _event_ids(listed_access)
    assert events, "The test calendar holds the fixture meeting"
    targets = [
        *_thread_ids(listed_access)[:MAX_THREADS],
        *_own_ids(listed_access)[:MAX_THREADS],
        *events[:MAX_THREADS],
    ]

    docs, failures, _ = _split(
        list(_connector(outlook_credentials).reindex(_failures(targets)))
    )

    assert not failures, [f.failure_message for f in failures]
    assert sorted(d.id for d in docs) == sorted(targets)


def test_reindex_attaches_the_walks_readers(
    outlook_credentials: dict[str, str],
    listed_access: dict[str, ExternalAccess | None],
) -> None:
    targets = [
        *_thread_ids(listed_access)[:2],
        *_own_ids(listed_access)[:1],
        *_event_ids(listed_access)[:2],
    ]

    docs, failures, nodes = _split(
        list(
            _connector(outlook_credentials).reindex(
                _failures(targets), include_permissions=True
            )
        )
    )

    assert not failures, [f.failure_message for f in failures]
    assert sorted(d.id for d in docs) == sorted(targets)
    for doc in docs:
        assert doc.external_access is not None, doc.id
        assert TEST_MAILBOX in doc.external_access.external_user_emails
        assert doc.external_access == listed_access[doc.id], doc.id
    for node in nodes:
        assert node.external_access is not None, node.display_name


def test_well_formed_ids_of_missing_documents_fail(
    outlook_credentials: dict[str, str], mailbox_id: str
) -> None:
    missing = [
        f"{THREAD_DOCUMENT_ID_PREFIX}{BOGUS_KEY}",
        f"{THREAD_DOCUMENT_ID_PREFIX}{BOGUS_KEY}:{mailbox_id}",
        f"{THREAD_DOCUMENT_ID_PREFIX}{BOGUS_KEY}:{mailbox_id}{OWN_DOCUMENT_SUFFIX}",
        f"{EVENT_DOCUMENT_ID_PREFIX}{mailbox_id}:AAMkAGU3NDcyY2U5LWJvZ3VzAAA=",
        # A mailbox outside the connector's configuration.
        f"{THREAD_DOCUMENT_ID_PREFIX}{BOGUS_KEY}:00000000-0000-0000-0000-000000000000"
        f"{OWN_DOCUMENT_SUFFIX}",
    ]

    docs, failures, _ = _split(
        list(_connector(outlook_credentials).reindex(_failures(missing)))
    )

    assert not docs
    assert _failed_ids(failures) == set(missing)


def test_unparseable_ids_fail(outlook_credentials: dict[str, str]) -> None:
    unparseable = [
        "not-an-outlook-id",
        f"{THREAD_DOCUMENT_ID_PREFIX}not-a-key",
        f"{THREAD_DOCUMENT_ID_PREFIX}{BOGUS_KEY}:a:b:c",
        f"{EVENT_DOCUMENT_ID_PREFIX}no-event-id",
    ]

    docs, failures, nodes = _split(
        list(_connector(outlook_credentials).reindex(_failures(unparseable)))
    )

    assert not docs and not nodes
    assert _failed_ids(failures) == set(unparseable)


def test_events_fail_when_the_calendar_is_off(
    outlook_credentials: dict[str, str],
    listed_access: dict[str, ExternalAccess | None],
) -> None:
    target = _event_ids(listed_access)[0]

    docs, failures, _ = _split(
        list(
            _connector(outlook_credentials, include_calendar=False).reindex(
                _failures([target])
            )
        )
    )

    assert not docs
    assert _failed_ids(failures) == {target}


def test_empty_and_entity_only_input_yield_nothing(
    outlook_credentials: dict[str, str],
) -> None:
    connector = _connector(outlook_credentials)
    assert list(connector.reindex([])) == []
    entity_only = [
        ConnectorFailure(
            failed_entity=EntityFailure(entity_id=TEST_MAILBOX),
            failure_message="Mailbox unavailable",
        )
    ]
    assert list(connector.reindex(entity_only)) == []
