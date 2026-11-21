"""Mail that a Collaborative Inbox group delivers is one document for the
group, built the same from every member's copy, and never from the copy of a
mailbox outside the group."""

import json
from base64 import urlsafe_b64encode
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError

from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_names_for_storage
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
)
from onyx.connectors.gmail import collaborative_inbox
from onyx.connectors.gmail import connector as gmail_connector_module
from onyx.connectors.gmail.collaborative_inbox import (
    CollaborativeInboxLookup,
    build_groups_settings_service,
    get_delivering_group,
    is_collaborative_inbox,
)
from onyx.connectors.gmail.config import GmailConnectorConfig
from onyx.connectors.gmail.connector import (
    GmailConnector,
    thread_to_document,
    thread_to_documents,
)
from onyx.connectors.google_utils.resources import GoogleService
from onyx.connectors.google_utils.shared_constants import MISSING_SCOPES_ERROR_STR
from onyx.connectors.models import Document, SlimDocument
from onyx.db.models import Document as DBDocument
from onyx.indexing.indexing_pipeline import get_docs_to_update

_GROUP = "support@example.com"
_OTHER_GROUP = "legal@example.com"
_MEMBER = "member@example.com"
_OTHER_MEMBER = "other-member@example.com"
_OUTSIDER = "outsider@example.com"
_GROUP_ACCESS = ExternalAccess(
    external_user_emails=set(), external_user_group_ids={_GROUP}, is_public=False
)


def _message(
    gmail_id: str,
    rfc_message_id: str | None = "abc@mail.example.com",
    group: str | None = _GROUP,
    body: str = "Hello team",
) -> dict[str, Any]:
    headers = [
        {"name": "From", "value": "Reader <reader@customer.com>"},
        {"name": "To", "value": group or _MEMBER},
        {"name": "Subject", "value": "Billing question"},
        {"name": "Date", "value": "Sat, 2 Nov 2024 10:32:57 -0700"},
    ]
    if rfc_message_id is not None:
        headers.append({"name": "Message-ID", "value": f"<{rfc_message_id}>"})
    if group is not None:
        headers.append({"name": "List-ID", "value": f"<{group.replace('@', '.')}>"})
        headers.append({"name": "X-BeenThere", "value": group})
    return {
        "id": gmail_id,
        "payload": {
            "mimeType": "text/plain",
            "headers": headers,
            "body": {"data": urlsafe_b64encode(body.encode()).decode()},
        },
    }


@pytest.fixture
def group_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Google answers that the credential has settings access, that every
    address is a Collaborative Inbox, and that it has two members."""
    monkeypatch.setattr(
        "onyx.connectors.gmail.access.global_version.is_ee_version", lambda: True
    )
    api = MagicMock()
    api.is_collaborative_inbox.return_value = True
    api.list_group_member_emails.side_effect = lambda *_: iter([_MEMBER, _OTHER_MEMBER])
    with (
        patch.object(
            collaborative_inbox,
            "build_groups_settings_service",
            api.build_groups_settings_service,
        ),
        patch.object(
            collaborative_inbox, "is_collaborative_inbox", api.is_collaborative_inbox
        ),
        patch.object(
            collaborative_inbox,
            "list_group_member_emails",
            api.list_group_member_emails,
        ),
        patch.object(collaborative_inbox, "get_google_service"),
    ):
        yield api


def _lookup(group_emails: list[str] | None = None) -> CollaborativeInboxLookup:
    return CollaborativeInboxLookup(
        MagicMock(),
        "admin@example.com",
        [_GROUP] if group_emails is None else group_emails,
    )


def _http_error(status: int) -> HttpError:
    return HttpError(
        resp=httplib2.Response({"status": status}),
        content=json.dumps({"error": {"code": status, "message": "error"}}).encode(),
    )


def test_delivering_group_needs_both_headers_to_name_a_listed_group() -> None:
    groups = frozenset({_GROUP})

    assert get_delivering_group(_message("m1"), groups) == _GROUP
    assert get_delivering_group(_message("m1", group=None), groups) is None
    assert get_delivering_group(_message("m1", group=_OTHER_GROUP), groups) is None

    display_name_list_id = _message("m1")
    display_name_list_id["payload"]["headers"][-2]["value"] = (
        "Support Desk <support.example.com>"
    )
    assert get_delivering_group(display_name_list_id, groups) == _GROUP

    # The dotted List-ID alone is ambiguous: a.b@example.com and
    # a@b.example.com share one. X-BeenThere names the group exactly.
    other_list = _message("m1")
    other_list["payload"]["headers"][-2]["value"] = "<legal.example.com>"
    assert get_delivering_group(other_list, groups) is None
    no_been_there = _message("m1")
    no_been_there["payload"]["headers"].pop()
    assert get_delivering_group(no_been_there, groups) is None


def test_lookup_returns_the_group_only_for_a_member_mailbox(
    group_api: MagicMock,
) -> None:
    lookup = _lookup()

    assert lookup.get_group(_message("m1"), _MEMBER) == _GROUP
    assert lookup.get_group(_message("m2"), "Member@Example.com") == _GROUP
    assert lookup.get_group(_message("m3"), _OUTSIDER) is None
    # One settings read and one member listing serve the whole run.
    assert group_api.is_collaborative_inbox.call_count == 1
    assert group_api.list_group_member_emails.call_count == 1


def test_lookup_ignores_a_group_without_collaborative_inbox(
    group_api: MagicMock,
) -> None:
    group_api.is_collaborative_inbox.return_value = False
    lookup = _lookup()

    assert lookup.get_group(_message("m1"), _MEMBER) is None
    assert lookup.get_groups_without_collaborative_inbox() == [_GROUP]
    group_api.list_group_member_emails.assert_not_called()


def test_lookup_makes_no_google_call_without_listed_groups(
    group_api: MagicMock,
) -> None:
    lookup = _lookup(group_emails=[])

    assert lookup.get_group(_message("m1"), _MEMBER) is None
    assert lookup.get_groups_of_member(_MEMBER) == []
    group_api.build_groups_settings_service.assert_not_called()


def test_settings_service_is_unavailable_without_the_delegated_scope() -> None:
    creds = MagicMock(spec=ServiceAccountCredentials)
    scoped_creds = creds.with_scopes.return_value.with_subject.return_value

    scoped_creds.refresh.side_effect = RefreshError(
        f"unauthorized_client: {MISSING_SCOPES_ERROR_STR}"
    )
    assert build_groups_settings_service(creds, "admin@example.com") is None

    # Any other token failure must not read as "scope missing": the slim
    # listing would then list no group mail and pruning would delete it.
    scoped_creds.refresh.side_effect = RefreshError("invalid_grant")
    with pytest.raises(RefreshError):
        build_groups_settings_service(creds, "admin@example.com")

    # An OAuth token cannot carry the scope.
    assert build_groups_settings_service(MagicMock(), "admin@example.com") is None


def test_collaborative_inbox_flag_reads_the_string_boolean() -> None:
    settings_service = MagicMock()
    execute = settings_service.groups.return_value.get.return_value.execute

    execute.return_value = {"enableCollaborativeInbox": "true"}
    assert is_collaborative_inbox(settings_service, _GROUP) is True
    execute.return_value = {"enableCollaborativeInbox": "false"}
    assert is_collaborative_inbox(settings_service, _GROUP) is False
    execute.side_effect = _http_error(404)
    assert is_collaborative_inbox(settings_service, _GROUP) is False


def test_thread_splits_into_group_documents_and_a_personal_document(
    group_api: MagicMock,  # noqa: ARG001
) -> None:
    thread = {
        "id": "18f0aaaa",
        "messages": [
            _message("m1", "first@mail.example.com", body="Customer asks"),
            _message("m2", "private@mail.example.com", group=None, body="Off list"),
            _message("m3", "second@mail.example.com", body="Agent answers"),
        ],
    }

    documents = thread_to_documents(thread, _MEMBER, _lookup())

    assert [document.id for document in documents] == [
        f"{_GROUP}:first@mail.example.com",
        f"{_GROUP}:second@mail.example.com",
        "18f0aaaa",
    ]
    first, second, personal = documents
    assert first.external_access == _GROUP_ACCESS
    assert second.external_access == _GROUP_ACCESS
    assert first.semantic_identifier == "Billing question"
    assert [section.link for section in first.sections] == [
        "https://mail.google.com/mail/u/0/#search/"
        "rfc822msgid%3Afirst%40mail.example.com"
    ]
    assert "Customer asks" in (first.sections[0].text or "")
    # The off-list reply stays with the mailbox owner, and alone.
    assert personal.external_access == ExternalAccess(
        external_user_emails={_MEMBER}, external_user_group_ids=set(), is_public=False
    )
    assert [section.text for section in personal.sections] == [
        section.text
        for section in _thread_document(
            {"id": "18f0aaaa", "messages": [thread["messages"][1]]}, _MEMBER
        ).sections
    ]


def _thread_document(thread: dict[str, Any], user_email: str) -> Document:
    document = thread_to_document(thread, user_email)
    assert document is not None
    return document


def test_every_member_copy_builds_the_same_group_document(
    group_api: MagicMock,  # noqa: ARG001
) -> None:
    """Gmail message and thread ids differ per mailbox. The indexing pipeline
    skips a later copy only if its document id and content hash are the same."""
    lookup = _lookup()
    (from_member,) = thread_to_documents(
        {"id": "18f0aaaa", "messages": [_message("m-member")]}, _MEMBER, lookup
    )
    (from_other_member,) = thread_to_documents(
        {"id": "18f0bbbb", "messages": [_message("m-other")]}, _OTHER_MEMBER, lookup
    )

    assert from_member.id == from_other_member.id
    assert from_member.content_hash() == from_other_member.content_hash()
    assert from_member.sections == from_other_member.sections
    assert from_member.external_access == from_other_member.external_access
    assert from_member.doc_updated_at == from_other_member.doc_updated_at


def test_indexing_skips_a_second_member_copy_as_unchanged(
    group_api: MagicMock,  # noqa: ARG001
) -> None:
    """The group document is embedded once, however many members hold a copy."""
    lookup = _lookup()
    (stored,) = thread_to_documents(
        {"id": "18f0aaaa", "messages": [_message("m-member")]}, _MEMBER, lookup
    )
    (later_copy,) = thread_to_documents(
        {"id": "18f0bbbb", "messages": [_message("m-other")]}, _OTHER_MEMBER, lookup
    )
    db_document = DBDocument(
        id=stored.id,
        semantic_id=stored.semantic_identifier,
        doc_updated_at=stored.doc_updated_at,
        content_hash=stored.content_hash(),
        external_user_emails=[],
        external_user_group_ids=list(
            build_ext_group_names_for_storage({_GROUP}, DocumentSource.GMAIL)
        ),
        is_public=False,
    )

    # Docprocessing runs with the timestamp gate off, so the hash gate decides.
    to_update = get_docs_to_update(
        [later_copy], [db_document], ignore_timestamp_gate=True
    )

    assert to_update.updatable_docs == []


def test_a_message_sent_to_two_groups_is_one_document_per_group(
    group_api: MagicMock,  # noqa: ARG001
) -> None:
    lookup = _lookup(group_emails=[_GROUP, _OTHER_GROUP])
    thread = {
        "id": "18f0aaaa",
        "messages": [_message("m1"), _message("m2", group=_OTHER_GROUP)],
    }

    documents = thread_to_documents(thread, _MEMBER, lookup)

    assert [document.id for document in documents] == [
        f"{_GROUP}:abc@mail.example.com",
        f"{_OTHER_GROUP}:abc@mail.example.com",
    ]
    assert [document.external_access for document in documents] == [
        _GROUP_ACCESS,
        ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids={_OTHER_GROUP},
            is_public=False,
        ),
    ]


@pytest.mark.parametrize(
    ("user_email", "message"),
    [
        (_OUTSIDER, _message("m1")),
        (_MEMBER, _message("m1", rfc_message_id=None)),
    ],
    ids=["mailbox outside the group", "no Message-ID header"],
)
def test_group_mail_stays_a_thread_document_when_a_check_fails(
    group_api: MagicMock,  # noqa: ARG001
    user_email: str,
    message: dict[str, Any],
) -> None:
    thread = {"id": "18f0aaaa", "messages": [message]}

    documents = thread_to_documents(thread, user_email, _lookup())

    assert documents == [_thread_document(thread, user_email)]


def _group_mail_connector() -> GmailConnector:
    connector = GmailConnector(collaborative_inbox_groups=[_GROUP])
    connector._creds = MagicMock()
    connector._primary_admin_email = "admin@example.com"
    return connector


class _FakeGmailBatch:
    def __init__(self, gmail: "_FakeGmail", callback: Any) -> None:
        self._gmail = gmail
        self._callback = callback
        self._thread_ids: list[str] = []

    def add(self, request: str, request_id: str) -> None:  # noqa: ARG002
        self._thread_ids.append(request)

    def execute(self) -> None:
        for thread_id in self._thread_ids:
            outcome = self._gmail.threads_by_id[thread_id]
            if isinstance(outcome, HttpError):
                self._callback(thread_id, None, outcome)
            else:
                self._callback(thread_id, outcome, None)


class _FakeGmail:
    """One mailbox. The group search returns ``group_thread_ids`` and the
    plain thread listing returns every thread."""

    def __init__(
        self,
        threads_by_id: dict[str, dict[str, Any] | HttpError],
        group_thread_ids: list[str],
    ) -> None:
        self.threads_by_id = threads_by_id
        self.group_thread_ids = group_thread_ids
        self.list_queries: list[str | None] = []
        self.get_kwargs: list[dict[str, Any]] = []

    def users(self) -> "_FakeGmail":
        return self

    def threads(self) -> "_FakeGmail":
        return self

    def list(self, q: str | None = None, **_: Any) -> MagicMock:  # noqa: A003
        self.list_queries.append(q)
        thread_ids = self.group_thread_ids if q else list(self.threads_by_id)
        request = MagicMock()
        request.execute.return_value = {"threads": [{"id": i} for i in thread_ids]}
        return request

    def get(self, id: str, **kwargs: Any) -> str:  # noqa: A002
        self.get_kwargs.append(kwargs)
        return id

    def new_batch_http_request(self, callback: Any) -> _FakeGmailBatch:
        return _FakeGmailBatch(self, callback)


def _list_slim_documents(
    connector: GmailConnector, gmail: _FakeGmail, user_email: str = _MEMBER
) -> list[SlimDocument]:
    def fake_get_google_service(service: GoogleService, _: object, __: str) -> object:
        assert service is GoogleService.GMAIL
        return gmail

    with (
        patch.object(GmailConnector, "_get_all_user_emails", return_value=[user_email]),
        patch.object(
            gmail_connector_module,
            "get_google_service",
            side_effect=fake_get_google_service,
        ),
        patch.object(gmail_connector_module.time, "sleep"),
    ):
        return [
            item
            for batch in connector.retrieve_all_slim_docs_perm_sync()
            for item in batch
            if isinstance(item, SlimDocument)
        ]


def test_slim_listing_lists_group_documents_and_keeps_every_thread(
    group_api: MagicMock,  # noqa: ARG001
) -> None:
    gmail = _FakeGmail(
        threads_by_id={
            "18f0aaaa": {"id": "18f0aaaa", "messages": [_message("m1")]},
            "18f0bbbb": {"id": "18f0bbbb", "messages": [_message("m2", group=None)]},
        },
        group_thread_ids=["18f0aaaa"],
    )

    slim_documents = _list_slim_documents(_group_mail_connector(), gmail)

    # A thread document indexed before the group was listed must stay listed,
    # or pruning deletes it.
    assert [(slim.id, slim.external_access) for slim in slim_documents] == [
        (
            "18f0aaaa",
            ExternalAccess(
                external_user_emails={_MEMBER},
                external_user_group_ids=set(),
                is_public=False,
            ),
        ),
        (
            "18f0bbbb",
            ExternalAccess(
                external_user_emails={_MEMBER},
                external_user_group_ids=set(),
                is_public=False,
            ),
        ),
        (f"{_GROUP}:abc@mail.example.com", _GROUP_ACCESS),
    ]
    assert gmail.list_queries == [None, f"(list:{_GROUP})"]
    assert gmail.get_kwargs == [
        {
            "userId": _MEMBER,
            "fields": "id, messages(id, payload(headers))",
            "format": "metadata",
            "metadataHeaders": ["List-ID", "X-BeenThere", "Message-ID"],
        }
    ]


def test_slim_listing_skips_the_group_search_for_a_mailbox_outside_the_group(
    group_api: MagicMock,  # noqa: ARG001
) -> None:
    gmail = _FakeGmail(
        threads_by_id={"18f0aaaa": {"id": "18f0aaaa", "messages": [_message("m1")]}},
        group_thread_ids=["18f0aaaa"],
    )

    slim_documents = _list_slim_documents(
        _group_mail_connector(), gmail, user_email=_OUTSIDER
    )

    assert [slim.id for slim in slim_documents] == ["18f0aaaa"]
    assert gmail.list_queries == [None]


def test_slim_listing_fails_when_a_group_thread_cannot_be_read(
    group_api: MagicMock,  # noqa: ARG001
) -> None:
    """A group document that the listing leaves out is deleted by pruning."""
    gmail = _FakeGmail(
        threads_by_id={"18f0aaaa": _http_error(400)}, group_thread_ids=["18f0aaaa"]
    )

    with pytest.raises(RuntimeError, match="while listing group mail"):
        _list_slim_documents(_group_mail_connector(), gmail)


def test_validation_names_every_group_without_collaborative_inbox(
    group_api: MagicMock,
) -> None:
    connector = GmailConnector(collaborative_inbox_groups=[_GROUP, _OTHER_GROUP])
    connector._creds = MagicMock()
    connector._primary_admin_email = "admin@example.com"
    connector.validate_connector_settings()

    group_api.is_collaborative_inbox.return_value = False
    connector = GmailConnector(collaborative_inbox_groups=[_GROUP, _OTHER_GROUP])
    connector._creds = MagicMock()
    connector._primary_admin_email = "admin@example.com"
    with pytest.raises(ConnectorValidationError, match=f"{_OTHER_GROUP}, {_GROUP}"):
        connector.validate_connector_settings()


def test_validation_fails_when_the_credential_lacks_the_settings_scope(
    group_api: MagicMock,
) -> None:
    group_api.build_groups_settings_service.return_value = None
    connector = _group_mail_connector()

    with pytest.raises(InsufficientPermissionsError, match="apps.groups.settings"):
        connector.validate_connector_settings()

    # No listed group, nothing to check: no token is requested.
    group_api.build_groups_settings_service.reset_mock()
    GmailConnector().validate_connector_settings()
    group_api.build_groups_settings_service.assert_not_called()


def test_config_normalizes_group_addresses() -> None:
    config = GmailConnectorConfig.model_validate(
        {
            "collaborative_inbox_groups": [
                " Support@Example.com ",
                "",
                _GROUP,
                _OTHER_GROUP,
            ]
        }
    )
    assert config.collaborative_inbox_groups == [_OTHER_GROUP, _GROUP]

    with pytest.raises(ValueError, match="Enter each group as an email address"):
        GmailConnectorConfig.model_validate({"collaborative_inbox_groups": ["support"]})
