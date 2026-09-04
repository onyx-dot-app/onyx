import time
from unittest.mock import MagicMock

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.connector import ZoomConnector, ZoomConnectorCheckpoint
from onyx.connectors.zoom.models import (
    ZoomMeetingOccurrence,
    ZoomPastMeetingDetails,
    ZoomTranscript,
)
from onyx.connectors.zoom.recordings.models import (
    OccurrenceWork,
    RecordingsState,
    ZoomSessionType,
)
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector,
    load_everything_from_checkpoint_connector_from_checkpoint,
)

_ZOOM_CREDS = {
    "zoom_account_id": "test-account",
    "zoom_client_id": "test-client-id",
    "zoom_client_secret": "test-client-secret",
}

_FULL_HISTORY_END = time.time()

_SAMPLE_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:02.500
Jane Doe: Hello everyone, welcome to the call.

2
00:00:02.600 --> 00:00:05.000
John Smith: Thanks for having me.
"""


def _make_connector(
    meeting_ids: list[str] | None = None,
) -> tuple[ZoomConnector, MagicMock]:
    # Don't write `meeting_ids or [...]` here: it swaps a caller's empty list
    # for the default, and the empty-allowlist tests below then pass for the
    # wrong reason.
    connector = ZoomConnector(
        meeting_ids=["111"] if meeting_ids is None else meeting_ids
    )
    connector.load_credentials(_ZOOM_CREDS)
    mock_client = MagicMock(spec=ZoomClient)
    connector.client = mock_client
    return connector, mock_client


def _configure_happy_path(mock_client: MagicMock) -> None:
    mock_client.list_past_meeting_occurrences.side_effect = lambda session_id: [
        ZoomMeetingOccurrence(
            uuid=f"uuid-{session_id}", start_time="2026-01-15T10:00:00Z"
        )
    ]
    mock_client.get_meeting_transcript.side_effect = lambda uuid: ZoomTranscript(
        download_url=f"https://zoom.example/{uuid}.vtt"
    )
    mock_client.download_transcript_vtt.return_value = _SAMPLE_VTT
    mock_client.get_past_meeting_details.return_value = ZoomPastMeetingDetails(
        topic="Weekly Sync"
    )


class TestZoomConnectorCredentials:
    def test_load_credentials_requires_all_fields(self) -> None:
        connector = ZoomConnector(meeting_ids=["111"])
        with pytest.raises(ConnectorMissingCredentialError):
            connector.load_credentials({"zoom_account_id": "only-one-field"})

    def test_load_from_checkpoint_without_credentials_raises(self) -> None:
        connector = ZoomConnector(meeting_ids=["111"])
        checkpoint = connector.build_dummy_checkpoint()
        with pytest.raises(ConnectorMissingCredentialError):
            next(connector.load_from_checkpoint(0, 1, checkpoint))


class TestZoomConnectorValidateSettings:
    def test_no_discovery_mechanism_rejected(self) -> None:
        connector = ZoomConnector(meeting_ids=[])
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()

    def test_configured_meeting_ids_accepted(self) -> None:
        connector = ZoomConnector(meeting_ids=["111"])
        connector.validate_connector_settings()


class TestZoomConnectorCheckpoint:
    def test_build_dummy_checkpoint(self) -> None:
        connector, _ = _make_connector()
        checkpoint = connector.build_dummy_checkpoint()
        assert checkpoint.has_more is True
        assert checkpoint.recordings == RecordingsState()

    def test_validate_checkpoint_json(self) -> None:
        connector, _ = _make_connector()
        original = ZoomConnectorCheckpoint(
            has_more=True,
            recordings=RecordingsState(
                source_index=1,
                source_cursor={"index": 2},
                pending_work=[
                    OccurrenceWork(
                        session_type=ZoomSessionType.MEETING,
                        session_id="111",
                        occurrence_uuid="uuid-1",
                    )
                ],
                work_index=1,
            ),
        )
        restored = connector.validate_checkpoint_json(original.model_dump_json())
        assert restored == original

    def test_recorded_meeting_becomes_document_end_to_end(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        _configure_happy_path(mock_client)

        outputs = load_everything_from_checkpoint_connector(
            connector, 0, _FULL_HISTORY_END
        )
        docs = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]

        # One invocation to discover the occurrence, one to process it.
        assert len(outputs) == 2
        assert len(docs) == 1
        doc = docs[0]
        # Assert on the occurrence UUID, not the meeting id: passing the bare
        # meeting id would silently index only the most recent occurrence.
        assert doc.id == "ZOOM_MEETING_uuid-111"
        mock_client.get_meeting_transcript.assert_called_once_with("uuid-111")
        assert doc.semantic_identifier == "Weekly Sync"
        assert doc.metadata == {"session_type": "meeting"}
        assert outputs[-1].next_checkpoint.has_more is False

    def test_recurring_meeting_yields_one_document_per_occurrence(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        _configure_happy_path(mock_client)
        mock_client.list_past_meeting_occurrences.side_effect = None
        mock_client.list_past_meeting_occurrences.return_value = [
            ZoomMeetingOccurrence(uuid="uuid-1", start_time="2026-01-01T10:00:00Z"),
            ZoomMeetingOccurrence(uuid="uuid-2", start_time="2026-01-08T10:00:00Z"),
            ZoomMeetingOccurrence(uuid="uuid-3", start_time="2026-01-15T10:00:00Z"),
        ]

        outputs = load_everything_from_checkpoint_connector(
            connector, 0, _FULL_HISTORY_END
        )
        docs = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-1",
            "ZOOM_MEETING_uuid-2",
            "ZOOM_MEETING_uuid-3",
        ]
        assert outputs[-1].next_checkpoint.has_more is False

    def test_one_failing_occurrence_does_not_block_the_others(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        _configure_happy_path(mock_client)
        mock_client.list_past_meeting_occurrences.side_effect = None
        mock_client.list_past_meeting_occurrences.return_value = [
            ZoomMeetingOccurrence(uuid="uuid-1", start_time="2026-01-01T10:00:00Z"),
            ZoomMeetingOccurrence(uuid="uuid-2", start_time="2026-01-08T10:00:00Z"),
            ZoomMeetingOccurrence(uuid="uuid-3", start_time="2026-01-15T10:00:00Z"),
        ]

        def _transcript(uuid: str) -> ZoomTranscript:
            if uuid == "uuid-2":
                raise RuntimeError("boom")
            return ZoomTranscript(download_url=f"https://zoom.example/{uuid}.vtt")

        mock_client.get_meeting_transcript.side_effect = _transcript

        outputs = load_everything_from_checkpoint_connector(
            connector, 0, _FULL_HISTORY_END
        )
        items = [item for output in outputs for item in output.items]
        docs = [item for item in items if isinstance(item, Document)]
        failures = [item for item in items if isinstance(item, ConnectorFailure)]

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-1",
            "ZOOM_MEETING_uuid-3",
        ]
        assert len(failures) == 1
        assert failures[0].failed_document is not None
        assert failures[0].failed_document.document_id == "ZOOM_MEETING_uuid-2"
        assert outputs[-1].next_checkpoint.has_more is False

    def test_failing_id_does_not_block_the_next_id(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111", "222"])
        _configure_happy_path(mock_client)

        def _occurrences(session_id: str) -> list[ZoomMeetingOccurrence]:
            if session_id == "111":
                raise RuntimeError("boom")
            return [
                ZoomMeetingOccurrence(
                    uuid=f"uuid-{session_id}", start_time="2026-01-15T10:00:00Z"
                )
            ]

        mock_client.list_past_meeting_occurrences.side_effect = _occurrences

        outputs = load_everything_from_checkpoint_connector(
            connector, 0, _FULL_HISTORY_END
        )
        items = [item for output in outputs for item in output.items]
        docs = [item for item in items if isinstance(item, Document)]
        failures = [item for item in items if isinstance(item, ConnectorFailure)]

        assert [d.id for d in docs] == ["ZOOM_MEETING_uuid-222"]
        assert len(failures) == 1
        assert failures[0].failed_entity is not None
        assert failures[0].failed_entity.entity_id == "111"
        assert outputs[-1].next_checkpoint.has_more is False

    def test_meeting_with_no_occurrences_completes_without_documents(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        mock_client.list_past_meeting_occurrences.return_value = []

        outputs = load_everything_from_checkpoint_connector(
            connector, 0, _FULL_HISTORY_END
        )

        assert all(output.items == [] for output in outputs)
        mock_client.get_meeting_transcript.assert_not_called()
        assert outputs[-1].next_checkpoint.has_more is False

    def test_discovery_failure_surfaces_as_connector_failure(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        mock_client.list_past_meeting_occurrences.side_effect = RuntimeError("boom")

        outputs = load_everything_from_checkpoint_connector(
            connector, 0, _FULL_HISTORY_END
        )
        failures = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, ConnectorFailure)
        ]

        assert len(failures) == 1
        assert failures[0].failed_entity is not None
        assert failures[0].failed_entity.entity_id == "111"
        assert outputs[-1].next_checkpoint.has_more is False

    def test_iterates_multiple_meeting_ids_across_checkpoint_calls(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111", "222"])
        _configure_happy_path(mock_client)

        outputs = load_everything_from_checkpoint_connector(
            connector, 0, _FULL_HISTORY_END
        )

        # Discover and process each of the two ids in turn.
        assert len(outputs) == 4
        assert outputs[-1].next_checkpoint.has_more is False

        docs = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]
        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-111",
            "ZOOM_MEETING_uuid-222",
        ]

    def test_resumes_mid_run_from_serialized_checkpoint(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111", "222"])
        _configure_happy_path(mock_client)

        # Send the checkpoint through JSON between invocations, the way the
        # real worker does, and finish the run from the restored copy.
        checkpoint = connector.build_dummy_checkpoint()
        generator = connector.load_from_checkpoint(0, _FULL_HISTORY_END, checkpoint)
        try:
            while True:
                next(generator)
        except StopIteration as e:
            checkpoint = e.value
        restored = connector.validate_checkpoint_json(checkpoint.model_dump_json())

        outputs = load_everything_from_checkpoint_connector_from_checkpoint(
            connector, 0, _FULL_HISTORY_END, restored
        )
        docs = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-111",
            "ZOOM_MEETING_uuid-222",
        ]
        assert outputs[-1].next_checkpoint.has_more is False

    def test_no_meeting_ids_completes_immediately(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=[])

        outputs = load_everything_from_checkpoint_connector(
            connector, 0, _FULL_HISTORY_END
        )

        assert len(outputs) == 1
        assert outputs[0].items == []
        assert outputs[0].next_checkpoint.has_more is False
        mock_client.list_past_meeting_occurrences.assert_not_called()
