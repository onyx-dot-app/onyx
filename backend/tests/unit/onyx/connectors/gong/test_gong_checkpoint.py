import time
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.gong.connector import GongConnector
from onyx.connectors.gong.connector import GongConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document


def _make_transcript(call_id: str) -> dict[str, Any]:
    return {
        "callId": call_id,
        "transcript": [
            {
                "speakerId": "speaker1",
                "sentences": [{"text": "Hello world"}],
            }
        ],
    }


def _make_call_detail(call_id: str, title: str) -> dict[str, Any]:
    return {
        "metaData": {
            "id": call_id,
            "started": "2026-01-15T10:00:00Z",
            "title": title,
            "purpose": "Test call",
            "url": f"https://app.gong.io/call?id={call_id}",
            "system": "test-system",
        },
        "parties": [
            {
                "speakerId": "speaker1",
                "name": "Alice",
                "emailAddress": "alice@test.com",
            }
        ],
    }


@pytest.fixture
def connector() -> GongConnector:
    connector = GongConnector()
    connector.load_credentials(
        {
            "gong_access_key": "test-key",
            "gong_access_key_secret": "test-secret",
        }
    )
    return connector


class TestGongConnectorCheckpoint:
    def test_build_dummy_checkpoint(self, connector: GongConnector) -> None:
        checkpoint = connector.build_dummy_checkpoint()
        assert checkpoint.has_more is True
        assert checkpoint.workspace_ids is None
        assert checkpoint.workspace_index == 0
        assert checkpoint.cursor is None

    def test_validate_checkpoint_json(self, connector: GongConnector) -> None:
        original = GongConnectorCheckpoint(
            has_more=True,
            workspace_ids=["ws1", None],
            workspace_index=1,
            cursor="abc123",
        )
        json_str = original.model_dump_json()
        restored = connector.validate_checkpoint_json(json_str)
        assert restored == original

    @patch.object(GongConnector, "_throttled_request")
    def test_first_call_resolves_workspaces(
        self,
        mock_request: MagicMock,
        connector: GongConnector,
    ) -> None:
        """First checkpoint call should resolve workspaces and return without fetching."""
        # No workspaces configured — should resolve to [None]
        checkpoint = connector.build_dummy_checkpoint()
        generator = connector.load_from_checkpoint(0, time.time(), checkpoint)

        # Should return immediately (no yields)
        with pytest.raises(StopIteration) as exc_info:
            next(generator)

        new_checkpoint = exc_info.value.value
        assert new_checkpoint.workspace_ids == [None]
        assert new_checkpoint.has_more is True
        assert new_checkpoint.workspace_index == 0

        # No API calls should have been made for workspace resolution
        # when no workspaces are configured
        mock_request.assert_not_called()

    @patch.object(GongConnector, "_throttled_request")
    def test_single_page_no_cursor(
        self,
        mock_request: MagicMock,
        connector: GongConnector,
    ) -> None:
        """Single page of transcripts with no pagination cursor."""
        transcript_response = MagicMock()
        transcript_response.status_code = 200
        transcript_response.json.return_value = {
            "callTranscripts": [_make_transcript("call1")],
            "records": {},
        }

        details_response = MagicMock()
        details_response.status_code = 200
        details_response.json.return_value = {
            "calls": [_make_call_detail("call1", "Test Call")]
        }

        mock_request.side_effect = [transcript_response, details_response]

        # Start from a checkpoint that already has workspaces resolved
        checkpoint = GongConnectorCheckpoint(
            has_more=True,
            workspace_ids=[None],
            workspace_index=0,
        )

        docs: list[Document] = []
        failures: list[ConnectorFailure] = []
        generator = connector.load_from_checkpoint(0, time.time(), checkpoint)
        try:
            while True:
                item = next(generator)
                if isinstance(item, Document):
                    docs.append(item)
                elif isinstance(item, ConnectorFailure):
                    failures.append(item)
        except StopIteration as e:
            checkpoint = e.value

        assert len(docs) == 1
        assert docs[0].semantic_identifier == "Test Call"
        assert len(failures) == 0
        assert checkpoint.has_more is False
        assert checkpoint.workspace_index == 1

    @patch.object(GongConnector, "_throttled_request")
    def test_multi_page_with_cursor(
        self,
        mock_request: MagicMock,
        connector: GongConnector,
    ) -> None:
        """Two pages of transcripts — cursor advances between checkpoint calls."""
        # Page 1: returns cursor
        page1_response = MagicMock()
        page1_response.status_code = 200
        page1_response.json.return_value = {
            "callTranscripts": [_make_transcript("call1")],
            "records": {"cursor": "page2cursor"},
        }

        details1_response = MagicMock()
        details1_response.status_code = 200
        details1_response.json.return_value = {
            "calls": [_make_call_detail("call1", "Call One")]
        }

        # Page 2: no cursor (done)
        page2_response = MagicMock()
        page2_response.status_code = 200
        page2_response.json.return_value = {
            "callTranscripts": [_make_transcript("call2")],
            "records": {},
        }

        details2_response = MagicMock()
        details2_response.status_code = 200
        details2_response.json.return_value = {
            "calls": [_make_call_detail("call2", "Call Two")]
        }

        mock_request.side_effect = [
            page1_response,
            details1_response,
            page2_response,
            details2_response,
        ]

        checkpoint = GongConnectorCheckpoint(
            has_more=True,
            workspace_ids=[None],
            workspace_index=0,
        )

        all_docs: list[Document] = []

        # First checkpoint call — page 1
        generator = connector.load_from_checkpoint(0, time.time(), checkpoint)
        try:
            while True:
                item = next(generator)
                if isinstance(item, Document):
                    all_docs.append(item)
        except StopIteration as e:
            checkpoint = e.value

        assert len(all_docs) == 1
        assert checkpoint.cursor == "page2cursor"
        assert checkpoint.has_more is True

        # Second checkpoint call — page 2
        generator = connector.load_from_checkpoint(0, time.time(), checkpoint)
        try:
            while True:
                item = next(generator)
                if isinstance(item, Document):
                    all_docs.append(item)
        except StopIteration as e:
            checkpoint = e.value

        assert len(all_docs) == 2
        assert all_docs[0].semantic_identifier == "Call One"
        assert all_docs[1].semantic_identifier == "Call Two"
        assert checkpoint.has_more is False

    @patch.object(GongConnector, "_throttled_request")
    def test_missing_call_details_yields_failure(
        self,
        mock_request: MagicMock,
        connector: GongConnector,
    ) -> None:
        """When call details are missing after retries, yield ConnectorFailure."""
        transcript_response = MagicMock()
        transcript_response.status_code = 200
        transcript_response.json.return_value = {
            "callTranscripts": [_make_transcript("call1")],
            "records": {},
        }

        # Return empty call details every time (simulating the race condition)
        empty_details = MagicMock()
        empty_details.status_code = 200
        empty_details.json.return_value = {"calls": []}

        mock_request.side_effect = [transcript_response] + [
            empty_details
        ] * GongConnector.MAX_CALL_DETAILS_ATTEMPTS

        checkpoint = GongConnectorCheckpoint(
            has_more=True,
            workspace_ids=[None],
            workspace_index=0,
        )

        failures: list[ConnectorFailure] = []
        docs: list[Document] = []

        with patch("onyx.connectors.gong.connector.time.sleep"):
            generator = connector.load_from_checkpoint(0, time.time(), checkpoint)
            try:
                while True:
                    item = next(generator)
                    if isinstance(item, ConnectorFailure):
                        failures.append(item)
                    elif isinstance(item, Document):
                        docs.append(item)
            except StopIteration as e:
                checkpoint = e.value

        assert len(docs) == 0
        assert len(failures) == 1
        assert failures[0].failed_document is not None
        assert failures[0].failed_document.document_id == "call1"
        assert checkpoint.has_more is False

    @patch.object(GongConnector, "_throttled_request")
    def test_multi_workspace_iteration(
        self,
        mock_request: MagicMock,
        connector: GongConnector,
    ) -> None:
        """Checkpoint iterates through multiple workspaces."""
        # Workspace 1: one call
        ws1_transcript = MagicMock()
        ws1_transcript.status_code = 200
        ws1_transcript.json.return_value = {
            "callTranscripts": [_make_transcript("call_ws1")],
            "records": {},
        }
        ws1_details = MagicMock()
        ws1_details.status_code = 200
        ws1_details.json.return_value = {
            "calls": [_make_call_detail("call_ws1", "WS1 Call")]
        }

        # Workspace 2: one call
        ws2_transcript = MagicMock()
        ws2_transcript.status_code = 200
        ws2_transcript.json.return_value = {
            "callTranscripts": [_make_transcript("call_ws2")],
            "records": {},
        }
        ws2_details = MagicMock()
        ws2_details.status_code = 200
        ws2_details.json.return_value = {
            "calls": [_make_call_detail("call_ws2", "WS2 Call")]
        }

        mock_request.side_effect = [
            ws1_transcript,
            ws1_details,
            ws2_transcript,
            ws2_details,
        ]

        checkpoint = GongConnectorCheckpoint(
            has_more=True,
            workspace_ids=["ws1_id", "ws2_id"],
            workspace_index=0,
        )

        all_docs: list[Document] = []

        # Checkpoint call 1 — workspace 1
        generator = connector.load_from_checkpoint(0, time.time(), checkpoint)
        try:
            while True:
                item = next(generator)
                if isinstance(item, Document):
                    all_docs.append(item)
        except StopIteration as e:
            checkpoint = e.value

        assert checkpoint.workspace_index == 1
        assert checkpoint.has_more is True

        # Checkpoint call 2 — workspace 2
        generator = connector.load_from_checkpoint(0, time.time(), checkpoint)
        try:
            while True:
                item = next(generator)
                if isinstance(item, Document):
                    all_docs.append(item)
        except StopIteration as e:
            checkpoint = e.value

        assert len(all_docs) == 2
        assert all_docs[0].semantic_identifier == "WS1 Call"
        assert all_docs[1].semantic_identifier == "WS2 Call"
        assert checkpoint.has_more is False
        assert checkpoint.workspace_index == 2

    @patch.object(GongConnector, "_throttled_request")
    def test_empty_workspace_404(
        self,
        mock_request: MagicMock,
        connector: GongConnector,
    ) -> None:
        """404 from transcript API means no calls — workspace exhausted."""
        response_404 = MagicMock()
        response_404.status_code = 404

        mock_request.return_value = response_404

        checkpoint = GongConnectorCheckpoint(
            has_more=True,
            workspace_ids=[None],
            workspace_index=0,
        )

        generator = connector.load_from_checkpoint(0, time.time(), checkpoint)
        try:
            while True:
                next(generator)
        except StopIteration as e:
            checkpoint = e.value

        assert checkpoint.has_more is False
        assert checkpoint.workspace_index == 1

    @patch.object(GongConnector, "_throttled_request")
    def test_retry_only_fetches_missing_ids(
        self,
        mock_request: MagicMock,
        connector: GongConnector,
    ) -> None:
        """Retry for missing call details should only re-request the missing IDs."""
        transcript_response = MagicMock()
        transcript_response.status_code = 200
        transcript_response.json.return_value = {
            "callTranscripts": [
                _make_transcript("call1"),
                _make_transcript("call2"),
            ],
            "records": {},
        }

        # First fetch: returns call1 but not call2
        partial_details = MagicMock()
        partial_details.status_code = 200
        partial_details.json.return_value = {
            "calls": [_make_call_detail("call1", "Call One")]
        }

        # Second fetch (retry): returns call2
        missing_details = MagicMock()
        missing_details.status_code = 200
        missing_details.json.return_value = {
            "calls": [_make_call_detail("call2", "Call Two")]
        }

        mock_request.side_effect = [
            transcript_response,
            partial_details,
            missing_details,
        ]

        checkpoint = GongConnectorCheckpoint(
            has_more=True,
            workspace_ids=[None],
            workspace_index=0,
        )

        docs: list[Document] = []
        with patch("onyx.connectors.gong.connector.time.sleep"):
            generator = connector.load_from_checkpoint(0, time.time(), checkpoint)
            try:
                while True:
                    item = next(generator)
                    if isinstance(item, Document):
                        docs.append(item)
            except StopIteration:
                pass

        assert len(docs) == 2
        assert docs[0].semantic_identifier == "Call One"
        assert docs[1].semantic_identifier == "Call Two"

        # Verify: 3 API calls total (1 transcript + 1 full details + 1 retry for missing only)
        assert mock_request.call_count == 3
        # The retry call should only request call2, not both
        retry_call_body = mock_request.call_args_list[2][1]["json"]
        assert retry_call_body["filter"]["callIds"] == ["call2"]

    @patch.object(GongConnector, "_throttled_request")
    def test_expired_cursor_restarts_workspace(
        self,
        mock_request: MagicMock,
        connector: GongConnector,
    ) -> None:
        """Expired pagination cursor resets checkpoint to restart the workspace."""
        expired_response = MagicMock()
        expired_response.status_code = 400
        expired_response.ok = False
        expired_response.text = '{"requestId":"abc","errors":["cursor has expired"]}'

        mock_request.return_value = expired_response

        # Checkpoint mid-pagination with a (now-expired) cursor
        checkpoint = GongConnectorCheckpoint(
            has_more=True,
            workspace_ids=[None],
            workspace_index=0,
            cursor="stale-cursor",
        )

        docs: list[Document] = []
        generator = connector.load_from_checkpoint(0, time.time(), checkpoint)
        try:
            while True:
                item = next(generator)
                if isinstance(item, Document):
                    docs.append(item)
        except StopIteration as e:
            checkpoint = e.value

        assert len(docs) == 0
        # Cursor reset so next call restarts the workspace from scratch
        assert checkpoint.cursor is None
        assert checkpoint.workspace_index == 0
        assert checkpoint.has_more is True
