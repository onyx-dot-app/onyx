import copy
import datetime
import json
import os
from collections.abc import Callable
from typing import Any, cast
from unittest.mock import MagicMock, patch

import httplib2
import pytest
from googleapiclient.errors import HttpError

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.gmail import connector as gmail_connector_module
from onyx.connectors.gmail.connector import (
    GmailCheckpoint,
    GmailConnector,
    _batch_get_threads,
    _build_time_range_query,
    thread_to_document,
)
from onyx.connectors.google_utils.resources import GoogleService
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector_from_checkpoint,
)


def test_thread_to_document() -> None:
    json_path = os.path.join(os.path.dirname(__file__), "thread.json")
    with open(json_path, "r") as f:
        full_email_thread = json.load(f)

    doc = thread_to_document(full_email_thread, "admin@onyx-test.com")
    assert isinstance(doc, Document)
    assert doc.source == DocumentSource.GMAIL
    assert doc.semantic_identifier == "Email Chain 1"
    assert doc.doc_updated_at == datetime.datetime(
        2024, 11, 2, 17, 34, 55, tzinfo=datetime.timezone.utc
    )
    assert len(doc.sections) == 4
    assert doc.metadata == {}


def test_build_time_range_query() -> None:
    time_range_start = 1703066296.159339
    time_range_end = 1704984791.657404
    query = _build_time_range_query(time_range_start, time_range_end)
    assert query == "after:1703066296 before:1704984791"
    query = _build_time_range_query(time_range_start, None)
    assert query == "after:1703066296"
    query = _build_time_range_query(None, time_range_end)
    assert query == "before:1704984791"
    query = _build_time_range_query(0.0, time_range_end)
    assert query == "before:1704984791"
    query = _build_time_range_query(None, None)
    assert query is None


def _thread_with_date(date_header: str | None) -> dict[str, Any]:
    """Load the fixture thread and replace (or strip, if None) its Date header."""
    json_path = os.path.join(os.path.dirname(__file__), "thread.json")
    with open(json_path, "r") as f:
        thread = cast(dict[str, Any], json.load(f))
    thread = copy.deepcopy(thread)

    for message in thread["messages"]:
        headers: list[dict[str, str]] = message["payload"]["headers"]
        if date_header is None:
            message["payload"]["headers"] = [
                h for h in headers if h.get("name") != "Date"
            ]
            continue

        replaced = False
        for header in headers:
            if header.get("name") == "Date":
                header["value"] = date_header
                replaced = True
                break
        if not replaced:
            headers.append({"name": "Date", "value": date_header})

    return thread


def test_thread_to_document_skips_unparseable_dates() -> None:
    for bad_date in (
        "Wed, 33 Sep 2007 13:42:59 +0100",
        "Thu, 11 Oct 2007 31:50:55 +0900",
        "total garbage not even close to a date",
    ):
        doc = thread_to_document(_thread_with_date(bad_date), "admin@example.com")
        assert isinstance(doc, Document), f"failed for {bad_date!r}"
        assert doc.doc_updated_at is None
        assert doc.id == "192edefb315737c3"


def test_gmail_checkpoint_progression() -> None:
    connector = GmailConnector()
    connector._creds = MagicMock()
    connector._primary_admin_email = "admin@example.com"

    user_emails = ["user1@example.com", "user2@example.com"]

    thread_list_responses: dict[str, dict[str | None, dict[str, Any]]] = {
        "user1@example.com": {
            None: {
                "threads": [{"id": "t1"}, {"id": "t2"}],
                "nextPageToken": "token-user1-page2",
            },
            "token-user1-page2": {
                "threads": [{"id": "t3"}],
                "nextPageToken": None,
            },
        },
        "user2@example.com": {
            None: {
                "threads": [{"id": "t4"}],
                "nextPageToken": None,
            }
        },
    }

    full_thread_responses = {
        "user1@example.com": {
            "t1": {"id": "t1"},
            "t2": {"id": "t2"},
            "t3": {"id": "t3"},
        },
        "user2@example.com": {
            "t4": {"id": "t4"},
        },
    }

    class MockRequest:
        def __init__(self, response: dict[str, Any]):
            self._response = response

        def execute(self) -> dict[str, Any]:
            return self._response

    class MockThreadsResource:
        def __init__(self, user_email: str) -> None:
            self._user_email = user_email

        def list(
            self,
            *,
            userId: str,
            fields: str,
            q: str | None = None,  # noqa: ARG002
            pageToken: str | None = None,
            **_: object,
        ) -> MockRequest:
            assert userId == self._user_email
            assert "nextPageToken" in fields
            responses = thread_list_responses[self._user_email]
            key = pageToken or None
            return MockRequest(responses[key])

        def get(
            self,
            *,
            userId: str,
            id: str,
            fields: str,
            **_: object,
        ) -> MockRequest:
            assert userId == self._user_email
            assert "messages" in fields or "payload" in fields
            return MockRequest(full_thread_responses[self._user_email][id])

    class MockUsersResource:
        def __init__(self, user_email: str) -> None:
            self._user_email = user_email

        def threads(self) -> MockThreadsResource:
            return MockThreadsResource(self._user_email)

    class MockGmailService:
        def __init__(self, user_email: str) -> None:
            self._user_email = user_email

        def users(self) -> MockUsersResource:
            return MockUsersResource(self._user_email)

    def fake_get_google_service(
        service: GoogleService, _: object, user_email: str
    ) -> MockGmailService:
        assert service is GoogleService.GMAIL
        return MockGmailService(user_email)

    def fake_thread_to_document(
        full_thread: dict[str, object], user_email: str
    ) -> Document:
        thread_id = cast(str, full_thread["id"])
        return Document(
            id=f"{user_email}:{thread_id}",
            semantic_identifier=f"Thread {thread_id}",
            sections=[TextSection(text=f"Body {thread_id}")],
            source=DocumentSource.GMAIL,
            metadata={},
            external_access=ExternalAccess(
                external_user_emails={user_email},
                external_user_group_ids=set(),
                is_public=False,
            ),
        )

    checkpoint = connector.build_dummy_checkpoint()
    assert isinstance(checkpoint, GmailCheckpoint)

    with patch.object(GmailConnector, "_get_all_user_emails", return_value=user_emails):
        with patch(
            "onyx.connectors.gmail.connector.get_google_service",
            side_effect=fake_get_google_service,
        ):
            with patch(
                "onyx.connectors.gmail.connector.thread_to_document",
                side_effect=fake_thread_to_document,
            ) as mock_thread_to_document:
                outputs = load_everything_from_checkpoint_connector_from_checkpoint(
                    connector=connector,
                    start=0,
                    end=1_000,
                    checkpoint=checkpoint,
                )

    document_ids = [
        item.id
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    assert document_ids == [
        "user2@example.com:t4",
        "user1@example.com:t1",
        "user1@example.com:t2",
        "user1@example.com:t3",
    ]

    assert mock_thread_to_document.call_count == 4

    final_checkpoint = outputs[-1].next_checkpoint
    assert isinstance(final_checkpoint, GmailCheckpoint)
    assert final_checkpoint.has_more is False
    assert final_checkpoint.user_emails == []


def _slim_listing_connector() -> GmailConnector:
    connector = GmailConnector()
    connector._creds = MagicMock()
    connector._primary_admin_email = "admin@example.com"
    return connector


def _list_slim_ids(
    connector: GmailConnector,
    user_emails: list[str],
    thread_list_responses: dict[str, dict[str | None, dict[str, Any]]],
    list_calls: list[tuple[str, str | None]],
) -> list[str]:
    """Runs the slim listing against a fake Gmail API that serves
    ``thread_list_responses[user][page_token]`` and records each list call."""

    def fake_get_google_service(
        service: GoogleService, _: object, __: str
    ) -> MagicMock:
        assert service is GoogleService.GMAIL

        def list_threads(
            *,
            userId: str,
            pageToken: str | None = None,
            **_: object,
        ) -> MagicMock:
            list_calls.append((userId, pageToken))
            request = MagicMock()
            request.execute.return_value = thread_list_responses[userId][pageToken]
            return request

        service = MagicMock()
        service.users.return_value.threads.return_value.list.side_effect = list_threads
        return service

    with patch.object(GmailConnector, "_get_all_user_emails", return_value=user_emails):
        with patch(
            "onyx.connectors.gmail.connector.get_google_service",
            side_effect=fake_get_google_service,
        ):
            return [
                item.id
                for batch in connector.retrieve_all_slim_docs_perm_sync()
                for item in batch
                if isinstance(item, SlimDocument)
            ]


def test_slim_listing_reads_every_page_of_every_user() -> None:
    """The slim listing (used by pruning and permission sync) must return
    every thread: all pages of a user, and each user from its first page."""
    thread_list_responses: dict[str, dict[str | None, dict[str, Any]]] = {
        "user1@example.com": {
            None: {
                "threads": [{"id": "t1"}, {"id": "t2"}],
                "nextPageToken": "token-user1-page2",
            },
            "token-user1-page2": {
                "threads": [{"id": "t3"}],
                "nextPageToken": None,
            },
        },
        "user2@example.com": {
            None: {"threads": [{"id": "t4"}], "nextPageToken": None},
        },
    }
    list_calls: list[tuple[str, str | None]] = []

    slim_ids = _list_slim_ids(
        _slim_listing_connector(),
        ["user1@example.com", "user2@example.com"],
        thread_list_responses,
        list_calls,
    )

    assert sorted(slim_ids) == ["t1", "t2", "t3", "t4"]
    assert list_calls == [
        ("user1@example.com", None),
        ("user1@example.com", "token-user1-page2"),
        ("user2@example.com", None),
    ]


def test_slim_listing_fails_on_a_repeated_page_token() -> None:
    thread_list_responses: dict[str, dict[str | None, dict[str, Any]]] = {
        "user1@example.com": {
            None: {"threads": [{"id": "t1"}], "nextPageToken": "stuck"},
            "stuck": {"threads": [{"id": "t2"}], "nextPageToken": "stuck"},
        },
    }

    with pytest.raises(RuntimeError, match="same page token"):
        _list_slim_ids(
            _slim_listing_connector(),
            ["user1@example.com"],
            thread_list_responses,
            [],
        )


def test_slim_listing_fails_after_the_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gmail_connector_module, "MAX_SLIM_PAGES_PER_USER", 3)
    pages: dict[str | None, dict[str, Any]] = {
        None: {"threads": [{"id": "t0"}], "nextPageToken": "p1"}
    }
    for page in range(1, 10):
        pages[f"p{page}"] = {
            "threads": [{"id": f"t{page}"}],
            "nextPageToken": f"p{page + 1}",
        }

    with pytest.raises(RuntimeError, match="without reaching the end"):
        _list_slim_ids(
            _slim_listing_connector(),
            ["user1@example.com"],
            {"user1@example.com": pages},
            [],
        )


def _reindex_with_thread_labels(
    labels_per_message: list[list[str]],
) -> list[Document | ConnectorFailure | HierarchyNode]:
    """Reindex the fixture thread, with these labels on its messages."""
    json_path = os.path.join(os.path.dirname(__file__), "thread.json")
    with open(json_path, "r") as f:
        thread = cast(dict[str, Any], json.load(f))
    for message, labels in zip(thread["messages"], labels_per_message, strict=True):
        message["labelIds"] = labels

    connector = GmailConnector()
    connector._creds = MagicMock()
    connector._primary_admin_email = "admin@example.com"
    failure = ConnectorFailure(
        failed_document=DocumentFailure(document_id=thread["id"]),
        failure_message="synthetic",
    )
    with (
        patch.object(
            connector, "_get_all_user_emails", return_value=["admin@example.com"]
        ),
        patch.object(gmail_connector_module, "get_google_service"),
        patch.object(
            gmail_connector_module,
            "_batch_get_threads",
            return_value=({thread["id"]: thread}, {}),
        ),
    ):
        return list(connector.reindex([failure]))


def test_reindex_skips_thread_the_crawl_does_not_list() -> None:
    # threads.list leaves out threads whose messages are all in Spam or Trash.
    results = _reindex_with_thread_labels([["TRASH"], ["SPAM"], ["TRASH"], ["TRASH"]])

    assert len(results) == 1
    failure = results[0]
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_document is not None
    assert failure.failed_document.document_id == "192edefb315737c3"
    assert "Spam or Trash" in failure.failure_message


def test_reindex_matches_crawl_document_for_listed_thread() -> None:
    results = _reindex_with_thread_labels([["TRASH"], ["INBOX"], ["SENT"], ["INBOX"]])

    assert len(results) == 1
    doc = results[0]
    assert isinstance(doc, Document)
    assert doc.id == "192edefb315737c3"
    # The crawl does not fetch labels, so they must not reach the document.
    assert all(
        isinstance(section, TextSection) and "labels:" not in section.text
        for section in doc.sections
    )


def _http_error(status: int, reason: str | None = None) -> HttpError:
    error: dict[str, Any] = {"code": status, "message": reason or "error"}
    if reason is not None:
        error["errors"] = [{"reason": reason, "message": reason}]
    payload = {"error": error}
    return HttpError(
        resp=httplib2.Response({"status": status}),
        content=json.dumps(payload).encode(),
    )


_ThreadOutcome = dict[str, Any] | HttpError


class _FakeGmailBatch:
    def __init__(
        self,
        gmail: "_FakeGmail",
        callback: Callable[[str, Any, Exception | None], None],
    ) -> None:
        self._gmail = gmail
        self._callback = callback
        self._requests: list[tuple[tuple[str, str], str]] = []

    def add(self, request: tuple[str, str], request_id: str) -> None:
        self._requests.append((request, request_id))

    def execute(self) -> None:
        if self._gmail.batch_errors:
            raise self._gmail.batch_errors.pop(0)
        for key, request_id in self._requests:
            self._gmail.reads.append(key)
            outcomes = self._gmail.outcomes.get(key)
            if not outcomes:
                self._callback(request_id, None, _http_error(404))
                continue
            outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
            if isinstance(outcome, HttpError):
                self._callback(request_id, None, outcome)
            else:
                self._callback(request_id, copy.deepcopy(outcome), None)


class _FakeGmail:
    """Gmail client fake for batched threads.get. Each (mailbox, thread id)
    returns its outcomes in order, and the last one repeats. Any other thread
    gets a 404. ``batch_errors`` fail whole batch requests, in order."""

    def __init__(
        self,
        outcomes: dict[tuple[str, str], list[_ThreadOutcome]],
        batch_errors: list[HttpError] | None = None,
    ) -> None:
        self.outcomes = outcomes
        self.batch_errors = list(batch_errors or [])
        self.reads: list[tuple[str, str]] = []

    def users(self) -> "_FakeGmail":
        return self

    def threads(self) -> "_FakeGmail":
        return self

    def get(self, userId: str, id: str, fields: str) -> tuple[str, str]:  # noqa: A002, ARG002
        return userId, id

    def new_batch_http_request(
        self, callback: Callable[[str, Any, Exception | None], None]
    ) -> _FakeGmailBatch:
        return _FakeGmailBatch(self, callback)


_MAILBOX = "admin@example.com"


def _batch_get(
    gmail: _FakeGmail, thread_ids: list[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, Exception]]:
    with patch.object(gmail_connector_module.time, "sleep"):
        return _batch_get_threads(
            cast(gmail_connector_module.GmailService, gmail), _MAILBOX, thread_ids
        )


def test_batch_get_threads_retries_rate_limits_and_server_errors() -> None:
    gmail = _FakeGmail(
        {
            (_MAILBOX, "a"): [_http_error(403, "userRateLimitExceeded"), {"id": "a"}],
            (_MAILBOX, "b"): [_http_error(429), {"id": "b"}],
            (_MAILBOX, "c"): [_http_error(503), {"id": "c"}],
            (_MAILBOX, "d"): [{"id": "d"}],
        }
    )

    found, errors = _batch_get(gmail, ["a", "b", "c", "d"])

    assert set(found) == {"a", "b", "c", "d"}
    assert errors == {}
    # A thread read on the first try is not read again.
    assert sorted(gmail.reads) == sorted(
        [(_MAILBOX, tid) for tid in ["a", "b", "c", "d", "a", "b", "c"]]
    )


def test_batch_get_threads_retries_a_failed_batch_request() -> None:
    gmail = _FakeGmail(
        {(_MAILBOX, "a"): [{"id": "a"}]},
        batch_errors=[_http_error(503), _http_error(429)],
    )

    found, errors = _batch_get(gmail, ["a"])

    assert set(found) == {"a"}
    assert errors == {}
    assert gmail.reads == [(_MAILBOX, "a")]


def test_batch_get_threads_raises_a_non_retryable_batch_error() -> None:
    gmail = _FakeGmail({}, batch_errors=[_http_error(400)])

    with pytest.raises(HttpError):
        _batch_get(gmail, ["a"])


def test_batch_get_threads_reports_exhausted_retries_as_errors() -> None:
    gmail = _FakeGmail(
        {(_MAILBOX, "a"): [_http_error(429)], (_MAILBOX, "b"): [{"id": "b"}]}
    )

    found, errors = _batch_get(gmail, ["a", "b"])

    assert set(found) == {"b"}
    # Never "not found": the thread may still be in this mailbox.
    assert set(errors) == {"a"}
    assert (
        gmail.reads.count((_MAILBOX, "a")) == gmail_connector_module._GMAIL_BATCH_TRIES
    )
    assert gmail.reads.count((_MAILBOX, "b")) == 1


def _reindex_with_fake_gmail(
    gmail: _FakeGmail,
    thread_ids: list[str],
    admin_service: MagicMock,
) -> list[Document | ConnectorFailure | HierarchyNode]:
    def fake_get_google_service(service: GoogleService, _: object, __: str) -> object:
        if service is GoogleService.ADMIN:
            return admin_service
        assert service is GoogleService.GMAIL
        return gmail

    connector = GmailConnector()
    connector._creds = MagicMock()
    connector._primary_admin_email = _MAILBOX
    failures = [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=thread_id),
            failure_message="synthetic",
        )
        for thread_id in thread_ids
    ]
    with (
        patch.object(
            gmail_connector_module,
            "get_google_service",
            side_effect=fake_get_google_service,
        ),
        patch.object(gmail_connector_module.time, "sleep"),
    ):
        return list(connector.reindex(failures))


def _admin_service_listing(user_emails: list[str]) -> MagicMock:
    admin_service = MagicMock()
    admin_service.users.return_value.list.return_value.execute.return_value = {
        "users": [{"primaryEmail": email} for email in user_emails]
    }
    return admin_service


def test_reindex_reports_exhausted_retries_as_failures() -> None:
    other_mailbox = "user1@example.com"
    gmail = _FakeGmail({(_MAILBOX, "aaaa"): [_http_error(429)]})

    results = _reindex_with_fake_gmail(
        gmail, ["aaaa"], _admin_service_listing([_MAILBOX, other_mailbox])
    )

    assert len(results) == 1
    failure = results[0]
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_document is not None
    assert failure.failed_document.document_id == "aaaa"
    assert "Failed to retrieve thread" in failure.failure_message
    # The thread resolved to a failure, so no other mailbox is searched.
    assert {mailbox for mailbox, _ in gmail.reads} == {_MAILBOX}


def test_reindex_oauth_reads_only_the_admin_mailbox() -> None:
    """An OAuth user cannot list the domain's users (403), so the crawl reads
    only the admin's mailbox. Reindex must read only that mailbox too."""
    json_path = os.path.join(os.path.dirname(__file__), "thread.json")
    with open(json_path, "r") as f:
        admin_thread = cast(dict[str, Any], json.load(f))
    admin_thread_id = cast(str, admin_thread["id"])
    other_thread_id = "aaaaaaaaaaaaaaaa"
    gmail = _FakeGmail({(_MAILBOX, admin_thread_id): [admin_thread]})
    admin_service = MagicMock()
    admin_service.users.return_value.list.return_value.execute.side_effect = (
        _http_error(403)
    )

    results = _reindex_with_fake_gmail(
        gmail, [admin_thread_id, other_thread_id], admin_service
    )

    docs = [r for r in results if isinstance(r, Document)]
    missing = [r for r in results if isinstance(r, ConnectorFailure)]
    assert [d.id for d in docs] == [admin_thread_id]
    assert docs[0].external_access is not None
    assert docs[0].external_access.external_user_emails == {_MAILBOX}
    assert len(missing) == 1
    assert missing[0].failed_document is not None
    assert missing[0].failed_document.document_id == other_thread_id
    assert {mailbox for mailbox, _ in gmail.reads} == {_MAILBOX}
