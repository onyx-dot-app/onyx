from unittest.mock import MagicMock

from onyx.connectors.models import ConnectorFailure, Document
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomPastMeetingDetails, ZoomTranscript
from onyx.connectors.zoom.recordings.models import OccurrenceWork, ZoomSessionType
from onyx.connectors.zoom.recordings.processing import (
    process_occurrence,
    zoom_document_id,
)

_SAMPLE_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:02.500
Jane Doe: Hello everyone, welcome to the call.

2
00:00:02.600 --> 00:00:05.000
John Smith: Thanks for having me.
"""


def _work(
    topic: str | None = None,
    start_time: str | None = "2026-01-15T10:00:00Z",
) -> OccurrenceWork:
    return OccurrenceWork(
        session_type=ZoomSessionType.MEETING,
        session_id="111",
        occurrence_uuid="uuid-abc",
        start_time=start_time,
        topic=topic,
    )


def _client_with_transcript() -> MagicMock:
    client = MagicMock(spec=ZoomClient)
    client.get_meeting_transcript.return_value = ZoomTranscript(
        download_url="https://zoom.example/transcript.vtt"
    )
    client.download_transcript_vtt.return_value = _SAMPLE_VTT
    client.get_past_meeting_details.return_value = ZoomPastMeetingDetails(
        topic="Weekly Sync"
    )
    return client


def _run(client: MagicMock, work: OccurrenceWork) -> list[Document | ConnectorFailure]:
    return list(process_occurrence(client, work))


class TestZoomDocumentId:
    """A targeted reindex is handed document ids and nothing else, so the id
    has to say which session type it came from. Changing this scheme after
    documents exist orphans them, so these values are effectively frozen."""

    def test_meeting_and_webinar_ids_are_distinguishable(self) -> None:
        meeting = zoom_document_id(ZoomSessionType.MEETING, "abc==")
        webinar = zoom_document_id(ZoomSessionType.WEBINAR, "abc==")

        assert meeting == "ZOOM_MEETING_abc=="
        assert webinar == "ZOOM_WEBINAR_abc=="
        # Same occurrence uuid must not collide across types.
        assert meeting != webinar


class TestProcessOccurrence:
    def test_recorded_occurrence_becomes_document(self) -> None:
        client = _client_with_transcript()

        items = _run(client, _work())

        assert len(items) == 1
        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.id == "ZOOM_MEETING_uuid-abc"
        assert doc.semantic_identifier == "Weekly Sync"
        assert doc.metadata == {"session_type": "meeting"}
        assert doc.sections[0].text is not None
        assert "Jane Doe: Hello everyone" in doc.sections[0].text
        assert doc.doc_created_at is not None
        client.get_meeting_transcript.assert_called_once_with("uuid-abc")
        client.get_past_meeting_details.assert_called_once_with("uuid-abc")

    def test_never_recorded_is_skipped(self) -> None:
        client = _client_with_transcript()
        client.get_meeting_transcript.return_value = None

        assert _run(client, _work()) == []
        client.download_transcript_vtt.assert_not_called()

    def test_not_ready_transcript_is_skipped(self) -> None:
        client = _client_with_transcript()
        client.get_meeting_transcript.return_value = ZoomTranscript(
            download_url=None, download_restriction_reason="NOT_READY"
        )

        assert _run(client, _work()) == []
        client.download_transcript_vtt.assert_not_called()

    def test_missing_download_url_is_skipped(self) -> None:
        client = _client_with_transcript()
        client.get_meeting_transcript.return_value = ZoomTranscript(download_url=None)

        assert _run(client, _work()) == []
        client.download_transcript_vtt.assert_not_called()

    def test_transcript_fetch_failure_yields_document_failure(self) -> None:
        client = _client_with_transcript()
        client.get_meeting_transcript.side_effect = RuntimeError("boom")

        items = _run(client, _work())

        assert len(items) == 1
        failure = items[0]
        assert isinstance(failure, ConnectorFailure)
        assert failure.failed_document is not None
        assert failure.failed_document.document_id == "ZOOM_MEETING_uuid-abc"

    def test_transcript_download_failure_yields_document_failure(self) -> None:
        client = _client_with_transcript()
        client.download_transcript_vtt.side_effect = RuntimeError("boom")

        items = _run(client, _work())

        assert len(items) == 1
        failure = items[0]
        assert isinstance(failure, ConnectorFailure)
        assert failure.failed_document is not None
        assert failure.failed_document.document_id == "ZOOM_MEETING_uuid-abc"

    def test_empty_transcript_after_parsing_is_skipped(self) -> None:
        client = _client_with_transcript()
        client.download_transcript_vtt.return_value = "WEBVTT\n"

        assert _run(client, _work()) == []

    def test_missing_details_falls_back_to_generic_title(self) -> None:
        client = _client_with_transcript()
        client.get_past_meeting_details.return_value = None

        items = _run(client, _work(start_time=None))

        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.semantic_identifier == "Zoom Meeting 111"
        assert doc.doc_created_at is None

    def test_details_failure_still_yields_document(self) -> None:
        client = _client_with_transcript()
        client.get_past_meeting_details.side_effect = RuntimeError("boom")

        items = _run(client, _work())

        assert len(items) == 1
        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.semantic_identifier == "Zoom Meeting 111"

    def test_details_fill_in_a_timestamp_discovery_did_not_have(self) -> None:
        client = _client_with_transcript()
        client.get_past_meeting_details.return_value = ZoomPastMeetingDetails(
            topic="Weekly Sync", start_time="2026-01-15T10:00:00Z"
        )

        items = _run(client, _work(start_time=None))

        doc = items[0]
        assert isinstance(doc, Document)
        # Don't discard a timestamp from a details call we already paid for.
        assert doc.doc_created_at is not None
        assert doc.doc_updated_at == doc.doc_created_at

    def test_empty_prefetched_topic_still_asks_for_details(self) -> None:
        client = _client_with_transcript()
        client.get_past_meeting_details.return_value = ZoomPastMeetingDetails(
            topic="Weekly Sync", start_time="2026-01-15T10:00:00Z"
        )

        items = _run(client, _work(topic=""))

        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.semantic_identifier == "Weekly Sync"

    def test_prefetched_topic_skips_details_call(self) -> None:
        client = _client_with_transcript()

        items = _run(client, _work(topic="Town Hall"))

        doc = items[0]
        assert isinstance(doc, Document)
        assert doc.semantic_identifier == "Town Hall"
        client.get_past_meeting_details.assert_not_called()
