"""Live tests against the Zoom test account described in account.py.

Discovery first: every recording the account holds is found and transcribed.
Then who may read each one: indexing and the perm-sync listing must name the
same readers, the doc sync must rewrite them and revoke what is gone, the
group sync must fill the domain groups those readers rely on, and the whole
must let exactly the right people find each recording.
"""

import time
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from ee.onyx.access.access import _get_acl_for_user
from ee.onyx.external_permissions.zoom.doc_sync import zoom_doc_sync
from ee.onyx.external_permissions.zoom.group_sync import zoom_group_sync
from onyx.access.models import DocExternalAccess, DocumentAccess, ExternalAccess
from onyx.access.utils import build_domain_group_id, build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document, SlimDocument, TextSection
from onyx.connectors.zoom.client import MAX_LISTING_PAGES
from onyx.connectors.zoom.connector import ZoomConnector
from onyx.connectors.zoom.recordings.models import ZoomSessionType
from onyx.connectors.zoom.recordings.processing import parse_zoom_document_id
from onyx.db.models import ConnectorCredentialPair, User
from onyx.db.utils import DocumentRow, SortOrder
from onyx.utils.sensitive import make_mock_sensitive_value
from tests.daily.connectors.utils import load_all_from_connector
from tests.daily.connectors.zoom.account import (
    RECORDINGS,
    RECORDINGS_WITHIN,
    Grant,
    domain_of,
    expected_access,
)
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

VANISHED_ID = "ZOOM_MEETING_vanished"
STRANGER = "nobody@example.com"


def _secret(test_secrets: dict[TestSecret, str], name: TestSecret) -> str:
    # get_secrets drops whatever it cannot resolve, so an unavailable secret
    # shows up as a missing key rather than an error.
    if name not in test_secrets:
        pytest.skip(f"{name.value} is not available")
    return test_secrets[name]


def _connector(credentials: dict[str, str], **config: Any) -> ZoomConnector:
    connector = ZoomConnector(**config)
    connector.load_credentials(credentials)
    return connector


@pytest.fixture(scope="module")
def credentials(test_secrets: dict[TestSecret, str]) -> dict[str, str]:
    return {
        "zoom_account_id": _secret(test_secrets, TestSecret.ZOOM_ACCOUNT_ID),
        "zoom_client_id": _secret(test_secrets, TestSecret.ZOOM_CLIENT_ID),
        "zoom_client_secret": _secret(test_secrets, TestSecret.ZOOM_CLIENT_SECRET),
    }


@pytest.fixture(scope="module")
def owner_email(test_secrets: dict[TestSecret, str]) -> str:
    return _secret(test_secrets, TestSecret.ZOOM_TEST_HOST_EMAIL).strip().lower()


@pytest.fixture(scope="module")
def host_connector(credentials: dict[str, str], owner_email: str) -> ZoomConnector:
    return _connector(credentials, host_emails=[owner_email])


@pytest.fixture
def meeting_connector(
    test_secrets: dict[TestSecret, str], credentials: dict[str, str]
) -> ZoomConnector:
    return _connector(
        credentials,
        meeting_ids=[_secret(test_secrets, TestSecret.ZOOM_TEST_MEETING_ID)],
    )


@pytest.fixture
def webinar_connector(
    test_secrets: dict[TestSecret, str], credentials: dict[str, str]
) -> ZoomConnector:
    # The account behind these secrets needs the Webinar add-on, or every
    # webinar call fails whatever the scopes are.
    return _connector(
        credentials,
        webinar_ids=[_secret(test_secrets, TestSecret.ZOOM_TEST_WEBINAR_ID)],
    )


@pytest.fixture
def group_connector(
    test_secrets: dict[TestSecret, str], credentials: dict[str, str]
) -> ZoomConnector:
    return _connector(
        credentials, group_id=_secret(test_secrets, TestSecret.ZOOM_TEST_GROUP_ID)
    )


@pytest.fixture(scope="module")
def cc_pair(credentials: dict[str, str], owner_email: str) -> ConnectorCredentialPair:
    """What the doc and group syncs read off a cc_pair, without a database."""
    cc_pair = MagicMock(spec=ConnectorCredentialPair)
    cc_pair.id = 1
    cc_pair.connector = MagicMock()
    cc_pair.connector.connector_specific_config = {"host_emails": [owner_email]}
    cc_pair.connector.indexing_start = None
    cc_pair.credential = MagicMock()
    cc_pair.credential.credential_json = make_mock_sensitive_value(credentials)
    return cast(ConnectorCredentialPair, cc_pair)


def _walk(
    connector: ZoomConnector,
    include_permissions: bool = False,
    since_epoch: bool = False,
) -> list[Document]:
    """Every 30-day window before the account's oldest recording is an empty
    call, so only the backfill test asks for the whole of history."""
    now = time.time()
    start = 0 if since_epoch else now - RECORDINGS_WITHIN.total_seconds()
    return load_all_from_connector(
        connector, start, now, include_permissions=include_permissions
    ).documents


# A connector resolves its hosts once for its lifetime, an empty answer
# included, so each indexing walk gets a fresh one.
@pytest.fixture(scope="module")
def backfill(credentials: dict[str, str], owner_email: str) -> list[Document]:
    """One plain walk from the epoch, the way a first index attempt runs."""
    return _walk(_connector(credentials, host_emails=[owner_email]), since_epoch=True)


@pytest.fixture(scope="module")
def indexed(credentials: dict[str, str], owner_email: str) -> list[Document]:
    """One walk with permissions, shared by every test that only reads it."""
    return _walk(
        _connector(credentials, host_emails=[owner_email]), include_permissions=True
    )


@pytest.fixture(scope="module")
def roster(host_connector: ZoomConnector) -> set[str]:
    """Every active user's email, as the group sync reads it."""
    client = host_connector.client
    assert client is not None
    emails: set[str] = set()
    page_token: str | None = None
    seen_tokens: set[str] = set()

    for _ in range(MAX_LISTING_PAGES):
        page = client.list_users(page_token=page_token)
        emails |= {u.email.strip().lower() for u in page.users if u.email.strip()}
        page_token = page.next_page_token
        if not page_token:
            return emails
        assert page_token not in seen_tokens, "Zoom stopped advancing the user cursor"
        seen_tokens.add(page_token)

    raise AssertionError(f"Zoom kept paging users past {MAX_LISTING_PAGES} pages")


def _slim(
    batches: Iterator[list[SlimDocument | Any]],
) -> dict[str, ExternalAccess | None]:
    return {
        doc.id: doc.external_access
        for batch in batches
        for doc in batch
        if isinstance(doc, SlimDocument)
    }


@contextmanager
def _no_transcript_downloads(connector: ZoomConnector) -> Iterator[None]:
    """The slim walks exist to skip the transcript fetch that the old fallback
    paid to read an id off the finished document."""
    client = connector.client
    assert client is not None
    with patch.object(
        client, "download_transcript_vtt", side_effect=AssertionError("downloaded")
    ):
        yield


def _assert_transcripts(docs: list[Document]) -> None:
    assert docs
    for doc in docs:
        parsed = parse_zoom_document_id(doc.id)
        assert parsed is not None, doc.id
        assert doc.metadata == {"session_type": parsed[0].value}, doc.id
        assert doc.source is DocumentSource.ZOOM, doc.id
        assert doc.doc_updated_at is not None, doc.id
        assert any(isinstance(s, TextSection) and s.text for s in doc.sections), (
            f"{doc.semantic_identifier} has no transcript text"
        )


def _assert_one_session(docs: list[Document], session_type: ZoomSessionType) -> None:
    """The secret names one session, so its documents are one table row: the
    same topic and kind, one document per recorded occurrence."""
    topics = {doc.semantic_identifier for doc in docs}
    assert len(topics) == 1, topics
    rows = {(r.topic, r.session_type): r for r in RECORDINGS}
    recording = rows.get((topics.pop(), session_type))
    assert recording is not None, (
        f"{docs[0].semantic_identifier!r} is not a {session_type.value} in account.py"
    )
    assert all(doc.metadata["session_type"] == session_type.value for doc in docs)
    assert len(docs) == recording.occurrences, recording.topic


def test_a_backfill_from_the_epoch_indexes_every_recording(
    backfill: list[Document],
) -> None:
    _assert_transcripts(backfill)
    assert all(doc.external_access is None for doc in backfill)

    listed = Counter(
        (doc.semantic_identifier, doc.metadata["session_type"]) for doc in backfill
    )
    assert listed == Counter(
        {(r.topic, r.session_type.value): r.occurrences for r in RECORDINGS}
    )


def test_a_meeting_number_indexes_each_recorded_occurrence(
    meeting_connector: ZoomConnector,
) -> None:
    docs = _walk(meeting_connector)
    _assert_transcripts(docs)
    _assert_one_session(docs, ZoomSessionType.MEETING)


def test_a_webinar_number_indexes_each_recorded_occurrence(
    webinar_connector: ZoomConnector,
) -> None:
    docs = _walk(webinar_connector)
    _assert_transcripts(docs)
    _assert_one_session(docs, ZoomSessionType.WEBINAR)


def test_a_zoom_group_indexes_its_members_recordings(
    group_connector: ZoomConnector,
) -> None:
    # The app cannot list a Group's members, so which recordings to expect is
    # not known here.
    _assert_transcripts(_walk(group_connector))


def test_the_meeting_number_walk_lists_every_indexed_document(
    meeting_connector: ZoomConnector,
) -> None:
    """Pruning deletes every indexed id the slim path leaves out. The id path
    resolves the number to its host before it can list anything, so it is the
    half most likely to come back empty."""
    indexed_ids = {doc.id for doc in _walk(meeting_connector)}
    assert indexed_ids

    with _no_transcript_downloads(meeting_connector):
        assert set(_slim(meeting_connector.retrieve_all_slim_docs())) == indexed_ids


def _readers(docs: list[Document]) -> dict[str, ExternalAccess]:
    readers: dict[str, ExternalAccess] = {}
    for doc in docs:
        assert doc.external_access is not None, doc.id
        readers[doc.id] = doc.external_access
    return readers


def _stored(rows: Mapping[str, ExternalAccess | None]) -> dict[str, ExternalAccess]:
    """The doc sync's rows as the database holds them: its writer adds the
    source prefix to each group id, which indexing adds itself, so this is the
    form the two paths can be compared in."""
    stored: dict[str, ExternalAccess] = {}
    for doc_id, access in rows.items():
        assert access is not None, doc_id
        stored[doc_id] = ExternalAccess(
            external_user_emails=access.external_user_emails,
            external_user_group_ids={
                build_ext_group_name_for_onyx(group_id, DocumentSource.ZOOM)
                for group_id in access.external_user_group_ids
            },
            is_public=access.is_public,
        )
    return stored


def _groups(cc_pair: ConnectorCredentialPair) -> dict[str, set[str]]:
    groups = list(zoom_group_sync("tenant", cc_pair))
    assert not any(group.gives_anyone_access for group in groups)
    return {group.id: set(group.user_emails) for group in groups}


def _topics(grant: Grant) -> set[str]:
    return {recording.topic for recording in RECORDINGS if recording.grant is grant}


def _no_rows(sort_order: SortOrder | None = None) -> list[DocumentRow]:  # noqa: ARG001
    return []


def test_indexing_attaches_each_recordings_link_access(
    indexed: list[Document], owner_email: str
) -> None:
    rows = {recording.topic: recording for recording in RECORDINGS}
    assert {doc.semantic_identifier for doc in indexed} == set(rows)

    for doc in indexed:
        recording = rows[doc.semantic_identifier]
        assert doc.external_access == expected_access(recording.grant, owner_email), (
            f"{recording.topic!r} is on {recording.link_access!r}, "
            f"so it should be readable by {recording.grant.value}"
        )


def test_pruning_lists_every_document_without_reading_access(
    host_connector: ZoomConnector, backfill: list[Document]
) -> None:
    with _no_transcript_downloads(host_connector):
        listed = _slim(host_connector.retrieve_all_slim_docs())

    assert set(listed) == {doc.id for doc in backfill}
    assert all(access is None for access in listed.values())


def test_the_perm_sync_walk_names_the_readers_indexing_named(
    host_connector: ZoomConnector, indexed: list[Document]
) -> None:
    with _no_transcript_downloads(host_connector):
        listed = _slim(host_connector.retrieve_all_slim_docs_perm_sync())

    assert _stored(listed) == _readers(indexed)


def test_the_doc_sync_rewrites_every_access_and_revokes_a_vanished_document(
    cc_pair: ConnectorCredentialPair, indexed: list[Document]
) -> None:
    readers = _readers(indexed)

    rows = zoom_doc_sync(cc_pair, _no_rows, lambda: [*readers, VANISHED_ID], None)
    synced = {
        row.doc_id: row.external_access
        for row in rows
        if isinstance(row, DocExternalAccess)
    }

    assert _stored(synced) == {**readers, VANISHED_ID: ExternalAccess.empty()}


def test_the_group_sync_fills_one_group_per_roster_domain(
    cc_pair: ConnectorCredentialPair, roster: set[str]
) -> None:
    expected: dict[str, set[str]] = defaultdict(set)
    for email in roster:
        expected[build_domain_group_id(domain_of(email))].add(email)

    assert _groups(cc_pair) == dict(expected)


def _acl_of(viewer: str, groups: dict[str, set[str]]) -> set[str]:
    """The production ACL builder, with only its two database reads stood in
    for: the user row, and the membership rows the group sync wrote, whose ids
    carry the source prefix upsert_external_groups adds."""
    user = cast(
        User,
        SimpleNamespace(id=viewer, email=viewer, prior_emails=[], is_anonymous=False),
    )
    memberships = [
        SimpleNamespace(
            external_user_group_id=build_ext_group_name_for_onyx(
                group_id, DocumentSource.ZOOM
            )
        )
        for group_id, members in groups.items()
        if viewer in members
    ]
    with (
        patch("ee.onyx.access.access.fetch_user_groups_for_user", return_value=[]),
        patch(
            "ee.onyx.access.access.fetch_external_groups_for_user",
            return_value=memberships,
        ),
    ):
        return _get_acl_for_user(user, db_session=cast(Session, None))


def _document_acl(access: ExternalAccess) -> set[str]:
    """What the search filter holds for a document, as indexing wrote it."""
    return DocumentAccess.build(
        user_emails=[],
        user_groups=[],
        external_user_emails=list(access.external_user_emails),
        external_user_group_ids=list(access.external_user_group_ids),
        is_public=access.is_public,
    ).to_acl()


def test_who_can_find_each_recording(
    cc_pair: ConnectorCredentialPair,
    indexed: list[Document],
    roster: set[str],
    owner_email: str,
) -> None:
    groups = _groups(cc_pair)
    readers = _readers(indexed)
    owner_domain = domain_of(owner_email)
    colleagues = [
        email
        for email in roster
        if email != owner_email and domain_of(email) == owner_domain
    ]
    assert colleagues, "the account needs a second user in the owner's domain"
    outsiders = [STRANGER, *(e for e in roster if domain_of(e) != owner_domain)]

    def findable_by(viewer: str) -> set[str]:
        acl = _acl_of(viewer, groups)
        return {
            doc.semantic_identifier
            for doc in indexed
            if acl & _document_acl(readers[doc.id])
        }

    assert findable_by(owner_email) == {recording.topic for recording in RECORDINGS}
    assert findable_by(colleagues[0]) == _topics(Grant.PUBLIC) | _topics(Grant.DOMAIN)
    for outsider in outsiders:
        assert findable_by(outsider) == _topics(Grant.PUBLIC), outsider


def test_link_access_off_leaves_only_the_owner(
    credentials: dict[str, str], owner_email: str
) -> None:
    connector = _connector(
        credentials, host_emails=[owner_email], treat_link_access_as_public=False
    )

    docs = _walk(connector, include_permissions=True)

    assert len(docs) == sum(recording.occurrences for recording in RECORDINGS)
    owner_only = expected_access(Grant.OWNER_ONLY, owner_email)
    for doc in docs:
        assert doc.external_access == owner_only, doc.semantic_identifier


def test_the_app_passes_the_permission_sync_probe(
    host_connector: ZoomConnector,
) -> None:
    # A scope dropped from the Marketplace app fails here before it can index
    # every transcript as readable by its owner alone.
    host_connector.validate_connector_settings()
    host_connector.probe_recording_access_permissions()
