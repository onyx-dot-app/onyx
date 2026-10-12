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
from onyx.connectors.zoom.connector import ZoomConnector
from onyx.connectors.zoom.recordings.models import OccurrenceWork, ZoomSessionType
from onyx.connectors.zoom.recordings.processing import process_occurrence
from tests.unit.onyx.connectors.zoom.helpers import (
    http_error,
    with_recording_access,
    with_transcript,
)
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import (
    past_meeting_details,
    recording_with_transcript,
    webinar_details,
)

_MEETING_DOC_ID = "ZOOM_MEETING_uuid-abc"
_WEBINAR_DOC_ID = "ZOOM_WEBINAR_uuid-xyz"


def _client() -> MagicMock:
    client = with_transcript()
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
        client.get_recording.assert_called_once_with("uuid-abc")

    def test_webinar_target_uses_the_webinar_handler(self) -> None:
        client = _with_access(_client())

        items = _reindex(client, [_target(_WEBINAR_DOC_ID)], include_permissions=True)

        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.id == _WEBINAR_DOC_ID
        assert doc.metadata == {"session_type": "webinar"}
        assert doc.semantic_identifier == "Launch Webinar"
        client.get_webinar_details.assert_called_with("uuid-xyz")
        client.get_past_meeting_details.assert_not_called()
        # Access comes from the recording, which is the same call for both.
        client.get_recording_settings.assert_called_once_with("uuid-xyz")

    def test_nothing_but_the_named_occurrence_is_touched(self) -> None:
        client = _client()

        items = _reindex(client, [_target(_MEETING_DOC_ID)])

        assert [d.id for d in items if isinstance(d, Document)] == [_MEETING_DOC_ID]
        client.get_recording.assert_called_once_with("uuid-abc")
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
        client.get_recording.side_effect = [
            RuntimeError("boom"),
            recording_with_transcript(
                download_url="https://zoom.example/transcript.vtt"
            ),
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
        client.get_recording.side_effect = CredentialExpiredError("expired")

        with pytest.raises(CredentialExpiredError):
            _reindex(client, [_target(_MEETING_DOC_ID)])


def _with_access(client: MagicMock) -> MagicMock:
    return with_recording_access(with_transcript(client, host_id="owner-1"))


class TestPermissionParity:
    """If these two paths drift, a recovered document quietly ends up with
    different permissions to its neighbours.
    """

    def _crawled(self, client: MagicMock, work: OccurrenceWork) -> Document:
        doc = process_occurrence(
            client, work, resolve_access=_connector(client)._resolve_access
        )
        assert isinstance(doc, Document)
        return doc

    @pytest.mark.parametrize(
        ("document_id", "work"),
        [
            (
                _MEETING_DOC_ID,
                OccurrenceWork(
                    session_type=ZoomSessionType.MEETING,
                    session_id="111",
                    occurrence_uuid="uuid-abc",
                ),
            ),
            (
                _WEBINAR_DOC_ID,
                OccurrenceWork(
                    session_type=ZoomSessionType.WEBINAR,
                    session_id="222",
                    occurrence_uuid="uuid-xyz",
                ),
            ),
        ],
        ids=["meeting", "webinar"],
    )
    def test_access_matches_the_crawl(
        self, document_id: str, work: OccurrenceWork
    ) -> None:
        client = _with_access(_client())

        reindexed = _reindex(client, [_target(document_id)], include_permissions=True)[
            0
        ]
        crawled = self._crawled(client, work)

        assert isinstance(reindexed, Document)
        assert reindexed.external_access is not None
        assert reindexed.external_access == crawled.external_access
        assert reindexed.external_access.external_user_emails == {"owner@example.com"}
        assert reindexed.external_access.is_public is True

    @pytest.mark.parametrize(
        "details_error",
        # Zoom reports a session over a year old with code 12702, and answers
        # 404 for one it has dropped.
        [http_error(400, 12702), http_error(404)],
        ids=["too-old", "dropped"],
    )
    @pytest.mark.parametrize("include_permissions", [False, True])
    def test_a_session_zoom_no_longer_resolves_is_still_reindexed(
        self, details_error: Exception, include_permissions: bool
    ) -> None:
        # The transcript is already downloaded by then, so the document is
        # indexed without the title and timestamp that call would have
        # supplied. The recording and its share settings still answer for the
        # occurrence, so the access list does not depend on the session.
        client = _with_access(_client())
        client.get_past_meeting_details.side_effect = details_error

        items = _reindex(
            client, [_target(_MEETING_DOC_ID)], include_permissions=include_permissions
        )

        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.doc_created_at is None
        if include_permissions:
            assert doc.external_access is not None
            assert doc.external_access.external_user_emails == {"owner@example.com"}
        else:
            assert doc.external_access is None

    @pytest.mark.parametrize(
        "error",
        [http_error(429), http_error(503), requests.ConnectionError("dropped")],
    )
    def test_share_settings_that_could_not_be_reached_are_not_guessed_at(
        self, error: Exception
    ) -> None:
        client = _with_access(_client())
        client.get_recording_settings.side_effect = error

        with pytest.raises(type(error)):
            _reindex(client, [_target(_MEETING_DOC_ID)], include_permissions=True)

    def test_permissions_are_not_fetched_when_not_requested(self) -> None:
        client = _with_access(_client())

        items = _reindex(client, [_target(_MEETING_DOC_ID)])

        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.external_access is None
        client.get_recording_settings.assert_not_called()
        client.get_user.assert_not_called()
