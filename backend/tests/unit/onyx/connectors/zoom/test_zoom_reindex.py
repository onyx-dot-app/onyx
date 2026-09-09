from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
)
from onyx.connectors.zoom.client import ZoomNotEntitledError
from onyx.connectors.zoom.connector import ZoomConnector
from onyx.connectors.zoom.models import ZoomSessionDetails
from onyx.connectors.zoom.recordings.models import OccurrenceWork, ZoomSessionType
from onyx.connectors.zoom.recordings.processing import process_occurrence
from tests.unit.onyx.connectors.zoom.helpers import (
    http_error,
    with_access,
    with_transcript,
)
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import (
    invitee,
    panelist,
    participant,
    past_meeting_details,
    registrant,
    transcript,
    webinar_details,
)

_MEETING_DOC_ID = "ZOOM_MEETING_uuid-abc"
_WEBINAR_DOC_ID = "ZOOM_WEBINAR_uuid-xyz"


def _client() -> MagicMock:
    client = with_access(with_transcript())
    client.get_past_meeting_details.return_value = past_meeting_details(
        id=111, topic="Weekly Sync", start_time="2026-01-15T10:00:00Z"
    )
    client.get_webinar_details.return_value = webinar_details(
        id=222, topic="Launch Webinar", start_time="2026-02-20T15:00:00Z"
    )
    return client


def _connector(client: MagicMock) -> ZoomConnector:
    connector = ZoomConnector(meeting_ids=["111"])
    connector.client = client
    return connector


def _target(document_id: str) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(document_id=document_id),
        failure_message="Failed to download transcript",
    )


def _reindex(
    client: MagicMock,
    targets: list[ConnectorFailure],
    include_permissions: bool = False,
) -> list[Document | ConnectorFailure]:
    return [
        item
        for item in _connector(client).reindex(
            errors=targets, include_permissions=include_permissions
        )
        if isinstance(item, (Document, ConnectorFailure))
    ]


class TestResolveTargets:
    def test_meeting_target_is_reindexed(self) -> None:
        client = _client()

        items = _reindex(client, [_target(_MEETING_DOC_ID)])

        assert len(items) == 1
        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.id == _MEETING_DOC_ID
        assert doc.metadata == {"session_type": "meeting"}
        assert doc.sections[0].text is not None
        assert "Jane Doe: Hello everyone" in doc.sections[0].text
        client.get_meeting_transcript.assert_called_once_with("uuid-abc")

    def test_webinar_target_uses_the_webinar_handler(self) -> None:
        client = _client()
        client.list_past_webinar_participants.return_value = [
            participant(user_email="viewer@example.com")
        ]

        items = _reindex(client, [_target(_WEBINAR_DOC_ID)], include_permissions=True)

        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.id == _WEBINAR_DOC_ID
        assert doc.metadata == {"session_type": "webinar"}
        assert doc.semantic_identifier == "Launch Webinar"
        client.get_webinar_details.assert_called_with("uuid-xyz")
        client.get_past_meeting_details.assert_not_called()
        client.list_past_webinar_participants.assert_called_once_with("uuid-xyz")
        client.list_past_meeting_participants.assert_not_called()

    def test_nothing_but_the_named_occurrence_is_touched(self) -> None:
        client = _client()

        items = _reindex(client, [_target(_MEETING_DOC_ID)])

        assert [d.id for d in items if isinstance(d, Document)] == [_MEETING_DOC_ID]
        client.get_meeting_transcript.assert_called_once_with("uuid-abc")
        client.list_user_recordings.assert_not_called()
        client.list_past_meeting_occurrences.assert_not_called()
        client.list_users.assert_not_called()
        client.list_group_members.assert_not_called()


class TestUnresolvableTargets:
    """Dropping one of these silently leaves the admin looking at a row that
    never resolves and never explains itself.
    """

    def test_unparseable_id_fails_that_target_alone(self) -> None:
        client = _client()

        items = _reindex(client, [_target("not-a-zoom-id"), _target(_MEETING_DOC_ID)])

        failure = items[0]
        assert isinstance(failure, ConnectorFailure)
        assert failure.failed_document is not None
        assert failure.failed_document.document_id == "not-a-zoom-id"
        assert "not-a-zoom-id" in failure.failure_message
        assert isinstance(items[1], Document)

    def test_discovery_failure_is_reported_as_unsupported(self) -> None:
        entity_target = ConnectorFailure(
            failed_entity=EntityFailure(entity_id="host@example.com"),
            failure_message="Couldn't list recordings for host@example.com",
        )
        client = _client()

        items = _reindex(client, [entity_target, _target(_MEETING_DOC_ID)])

        assert len(items) == 2
        unsupported = items[0]
        assert isinstance(unsupported, ConnectorFailure)
        assert unsupported.failed_entity is not None
        assert unsupported.failed_entity.entity_id == "host@example.com"
        assert "ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS" in unsupported.failure_message
        assert isinstance(items[1], Document)

    def test_one_broken_target_does_not_cost_the_others_their_retry(self) -> None:
        client = _client()
        client.get_meeting_transcript.side_effect = [
            RuntimeError("boom"),
            transcript(download_url="https://zoom.example/transcript.vtt"),
        ]

        items = _reindex(
            client, [_target(_MEETING_DOC_ID), _target("ZOOM_MEETING_uuid-2")]
        )

        assert len(items) == 2
        failure = items[0]
        assert isinstance(failure, ConnectorFailure)
        assert failure.failed_document is not None
        assert failure.failed_document.document_id == _MEETING_DOC_ID
        assert isinstance(items[1], Document)

    def test_an_error_worth_ending_the_job_over_is_raised(self) -> None:
        # Expired credentials hit every remaining target too, so a batch of
        # identical failure rows tells the admin less than one loud error does.
        client = _client()
        client.get_meeting_transcript.side_effect = CredentialExpiredError("expired")

        with pytest.raises(CredentialExpiredError):
            _reindex(client, [_target(_MEETING_DOC_ID)])


class TestPermissionParity:
    """If these two paths drift, a recovered document quietly ends up with
    different permissions to its neighbours.
    """

    def _populate_access(self, client: MagicMock) -> None:
        """These answer for the session number only, the way Zoom does. A mock
        that answers for anything passes even when the reindex never resolved
        the session.
        """

        def _for_session(session_id: str, found: list[object]) -> list[object]:
            if session_id in ("111", "222"):
                return found
            raise http_error(404)

        client.list_past_meeting_participants.return_value = [
            participant(user_email="attendee@example.com")
        ]
        client.list_meeting_registrants.side_effect = lambda session_id, **_: (
            _for_session(
                session_id,
                [registrant(email="registrant@example.com", status="approved")],
            )
        )
        client.list_meeting_invitees.side_effect = lambda session_id: _for_session(
            session_id, [invitee(email="invitee@example.com")]
        )
        client.list_past_webinar_participants.return_value = [
            participant(user_email="viewer@example.com")
        ]
        client.list_webinar_registrants.side_effect = lambda session_id, **_: (
            _for_session(
                session_id, [registrant(email="signup@example.com", status="approved")]
            )
        )
        client.list_webinar_panelists.side_effect = lambda session_id: _for_session(
            session_id, [panelist(email="panelist@example.com")]
        )

    def _crawled(self, client: MagicMock, work: OccurrenceWork) -> Document:
        items = list(process_occurrence(client, work, include_access=True))
        doc = items[0]
        assert isinstance(doc, Document)
        return doc

    def test_meeting_access_matches_the_crawl(self) -> None:
        client = _client()
        self._populate_access(client)

        reindexed = _reindex(
            client, [_target(_MEETING_DOC_ID)], include_permissions=True
        )[0]
        crawled = self._crawled(
            client,
            OccurrenceWork(
                session_type=ZoomSessionType.MEETING,
                session_id="111",
                occurrence_uuid="uuid-abc",
            ),
        )

        assert isinstance(reindexed, Document)
        assert reindexed.external_access is not None
        assert reindexed.external_access == crawled.external_access
        assert reindexed.external_access.external_user_emails == {
            "attendee@example.com",
            "registrant@example.com",
            "invitee@example.com",
        }

    def test_webinar_access_matches_the_crawl(self) -> None:
        client = _client()
        self._populate_access(client)

        reindexed = _reindex(
            client, [_target(_WEBINAR_DOC_ID)], include_permissions=True
        )[0]
        crawled = self._crawled(
            client,
            OccurrenceWork(
                session_type=ZoomSessionType.WEBINAR,
                session_id="222",
                occurrence_uuid="uuid-xyz",
            ),
        )

        assert isinstance(reindexed, Document)
        assert reindexed.external_access is not None
        assert reindexed.external_access == crawled.external_access

    @pytest.mark.parametrize(
        "details",
        # Zoom says "over a year old" with code 12702, answers 404 for a
        # session it has dropped, and can answer without a session number.
        [
            http_error(400, 12702),
            None,
            ZoomSessionDetails(topic="Weekly Sync"),
        ],
    )
    def test_a_session_it_cannot_resolve_fails_that_target(
        self, details: object
    ) -> None:
        client = _client()
        self._populate_access(client)
        if isinstance(details, Exception):
            client.get_past_meeting_details.side_effect = details
        else:
            client.get_past_meeting_details.return_value = details

        items = _reindex(client, [_target(_MEETING_DOC_ID)], include_permissions=True)

        assert len(items) == 1
        failure = items[0]
        assert isinstance(failure, ConnectorFailure)
        assert failure.failed_document is not None
        assert failure.failed_document.document_id == _MEETING_DOC_ID
        assert "uuid-abc" in failure.failure_message
        client.list_meeting_registrants.assert_not_called()

    def test_a_webinar_without_the_add_on_fails_and_names_the_plan(self) -> None:
        # Every webinar endpoint needs the add-on, the access list included, so
        # this account can name nobody.
        client = _client()
        client.get_webinar_details.side_effect = ZoomNotEntitledError("no add-on")

        items = _reindex(client, [_target(_WEBINAR_DOC_ID)], include_permissions=True)

        failure = items[0]
        assert isinstance(failure, ConnectorFailure)
        assert failure.failed_document is not None
        assert failure.failed_document.document_id == _WEBINAR_DOC_ID
        assert "plan does not cover" in failure.failure_message

    def test_an_unresolvable_session_still_indexes_without_permissions(self) -> None:
        # Nothing reads the session id when no access list is built.
        client = _client()
        client.get_past_meeting_details.return_value = None

        items = _reindex(client, [_target(_MEETING_DOC_ID)])

        assert isinstance(items[0], Document)

    @pytest.mark.parametrize(
        "error",
        [http_error(429), http_error(503), requests.ConnectionError("dropped")],
    )
    def test_a_session_that_could_not_be_reached_is_not_guessed_at(
        self, error: Exception
    ) -> None:
        client = _client()
        self._populate_access(client)
        client.get_past_meeting_details.side_effect = error

        with pytest.raises(type(error)):
            _reindex(client, [_target(_MEETING_DOC_ID)], include_permissions=True)

    def test_permissions_are_not_fetched_when_not_requested(self) -> None:
        client = _client()
        self._populate_access(client)

        items = _reindex(client, [_target(_MEETING_DOC_ID)])

        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.external_access is None
        client.list_past_meeting_participants.assert_not_called()
