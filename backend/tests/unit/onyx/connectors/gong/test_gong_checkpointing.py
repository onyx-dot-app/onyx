"""Unit tests for the Gong checkpointed connector.

Tests cover:
- Checkpoint model serialisation / validation
- build_dummy_checkpoint
- load_from_checkpoint: single page, multi-page, multi-workspace, 404 handling,
  call-details retry, continue_on_fail flag, and hide_user_info flag.
"""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests

from onyx.connectors.gong.connector import GongConnector
from onyx.connectors.gong.connector import GongConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector,
)
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector_from_checkpoint,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_FAKE_CREDENTIALS = {
    "gong_access_key": "key",
    "gong_access_key_secret": "secret",
}

_START: float = 0.0
_END: float = 1_700_000_000.0  # arbitrary fixed end timestamp


def _make_transcript(call_id: str) -> dict[str, Any]:
    return {
        "callId": call_id,
        "transcript": [
            {
                "speakerId": "s1",
                "sentences": [{"text": "Hello world"}],
            }
        ],
    }


def _make_call_detail(call_id: str, title: str = "Test Call") -> dict[str, Any]:
    return {
        "metaData": {
            "id": call_id,
            "title": title,
            "started": "2024-01-15T10:00:00Z",
            "url": f"https://app.gong.io/call?id={call_id}",
            "purpose": "",
            "system": "Zoom",
        },
        "parties": [
            {
                "speakerId": "s1",
                "name": "Alice",
                "emailAddress": "alice@example.com",
            }
        ],
    }


def _transcript_response(
    transcripts: list[dict[str, Any]], cursor: str | None = None
) -> MagicMock:
    """Build a mock requests.Response for /v2/calls/transcript."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    records: dict[str, Any] = {}
    if cursor:
        records["cursor"] = cursor
    mock_resp.json.return_value = {
        "callTranscripts": transcripts,
        "records": records,
    }
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def _extensive_response(call_details: list[dict[str, Any]]) -> MagicMock:
    """Build a mock requests.Response for /v2/calls/extensive."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"calls": call_details}
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def _not_found_response() -> MagicMock:
    """Build a 404 mock response."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 404
    return mock_resp


@pytest.fixture
def connector() -> GongConnector:
    c = GongConnector()
    c.load_credentials(_FAKE_CREDENTIALS)
    return c


# ---------------------------------------------------------------------------
# Checkpoint model tests
# ---------------------------------------------------------------------------


def test_build_dummy_checkpoint(connector: GongConnector) -> None:
    cp = connector.build_dummy_checkpoint()
    assert cp.has_more is True
    assert cp.cursor is None
    assert cp.workspace_index == 0


def test_validate_checkpoint_json(connector: GongConnector) -> None:
    cp = GongConnectorCheckpoint(has_more=True, cursor="abc", workspace_index=2)
    json_str = cp.model_dump_json()
    restored = connector.validate_checkpoint_json(json_str)
    assert restored == cp


def test_checkpoint_round_trip_no_cursor(connector: GongConnector) -> None:
    cp = GongConnectorCheckpoint(has_more=False, cursor=None, workspace_index=0)
    restored = connector.validate_checkpoint_json(cp.model_dump_json())
    assert restored == cp


# ---------------------------------------------------------------------------
# Single-page, single-workspace (no cursor in response)
# ---------------------------------------------------------------------------


def test_load_from_checkpoint_single_page(connector: GongConnector) -> None:
    """All transcripts fit in one page → has_more=False."""
    transcripts = [_make_transcript("c1"), _make_transcript("c2")]
    details = [_make_call_detail("c1", "Call 1"), _make_call_detail("c2", "Call 2")]

    with patch.object(connector._session, "post") as mock_post:
        mock_post.side_effect = [
            _transcript_response(transcripts, cursor=None),
            _extensive_response(details),
        ]

        outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    assert len(outputs) == 1
    batch = outputs[0]
    assert batch.next_checkpoint.has_more is False
    assert batch.next_checkpoint.cursor is None
    docs = [item for item in batch.items if isinstance(item, Document)]
    assert len(docs) == 2
    assert {d.id for d in docs} == {"c1", "c2"}
    assert docs[0].semantic_identifier == "Call 1"


# ---------------------------------------------------------------------------
# Multi-page, single workspace
# ---------------------------------------------------------------------------


def test_load_from_checkpoint_multi_page(connector: GongConnector) -> None:
    """Two pages of results → two load_from_checkpoint calls."""
    page1_transcripts = [_make_transcript("c1")]
    page2_transcripts = [_make_transcript("c2")]

    with patch.object(connector._session, "post") as mock_post:
        mock_post.side_effect = [
            # Call 1: transcript page 1 (returns cursor)
            _transcript_response(page1_transcripts, cursor="cursor_page2"),
            _extensive_response([_make_call_detail("c1", "Call 1")]),
            # Call 2: transcript page 2 (no cursor → done)
            _transcript_response(page2_transcripts, cursor=None),
            _extensive_response([_make_call_detail("c2", "Call 2")]),
        ]

        outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    assert len(outputs) == 2

    # After first call: checkpoint should carry the cursor
    cp1 = outputs[0].next_checkpoint
    assert cp1.has_more is True
    assert cp1.cursor == "cursor_page2"
    assert cp1.workspace_index == 0

    docs1 = [i for i in outputs[0].items if isinstance(i, Document)]
    assert len(docs1) == 1
    assert docs1[0].id == "c1"

    # After second call: done
    cp2 = outputs[1].next_checkpoint
    assert cp2.has_more is False
    assert cp2.cursor is None

    docs2 = [i for i in outputs[1].items if isinstance(i, Document)]
    assert len(docs2) == 1
    assert docs2[0].id == "c2"


# ---------------------------------------------------------------------------
# cursor is passed to the API on resume
# ---------------------------------------------------------------------------


def test_cursor_is_sent_on_resume(connector: GongConnector) -> None:
    """Verify the cursor from the checkpoint is forwarded to the next API call."""
    resume_checkpoint = GongConnectorCheckpoint(
        has_more=True, cursor="my_cursor", workspace_index=0
    )

    with patch.object(connector._session, "post") as mock_post:
        mock_post.side_effect = [
            _transcript_response([_make_transcript("c1")], cursor=None),
            _extensive_response([_make_call_detail("c1")]),
        ]

        outputs = load_everything_from_checkpoint_connector_from_checkpoint(
            connector, _START, _END, resume_checkpoint
        )

    assert len(outputs) == 1
    # Check that the transcript request included the cursor
    transcript_call = mock_post.call_args_list[0]
    sent_body = transcript_call.kwargs.get("json") or transcript_call.args[1]
    assert sent_body.get("cursor") == "my_cursor"


# ---------------------------------------------------------------------------
# Multi-workspace
# ---------------------------------------------------------------------------


def test_load_from_checkpoint_multi_workspace(connector: GongConnector) -> None:
    """Two workspaces, one page each → two load_from_checkpoint calls."""
    connector.workspaces = ["ws-A", "ws-B"]

    workspace_resp = MagicMock(spec=requests.Response)
    workspace_resp.status_code = 200
    workspace_resp.raise_for_status.return_value = None
    workspace_resp.json.return_value = {
        "workspaces": [
            {"id": "id-A", "name": "ws-A"},
            {"id": "id-B", "name": "ws-B"},
        ]
    }

    with patch.object(connector._session, "get", return_value=workspace_resp):
        with patch.object(connector._session, "post") as mock_post:
            mock_post.side_effect = [
                # Workspace A: one page, no cursor
                _transcript_response([_make_transcript("cA")], cursor=None),
                _extensive_response([_make_call_detail("cA", "Call A")]),
                # Workspace B: one page, no cursor
                _transcript_response([_make_transcript("cB")], cursor=None),
                _extensive_response([_make_call_detail("cB", "Call B")]),
            ]

            outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    # Two calls: one per workspace
    assert len(outputs) == 2

    cp1 = outputs[0].next_checkpoint
    assert cp1.workspace_index == 1
    assert cp1.has_more is True

    cp2 = outputs[1].next_checkpoint
    assert cp2.workspace_index == 2
    assert cp2.has_more is False

    all_doc_ids = {
        i.id for output in outputs for i in output.items if isinstance(i, Document)
    }
    assert all_doc_ids == {"cA", "cB"}


# ---------------------------------------------------------------------------
# 404 workspace skipping
# ---------------------------------------------------------------------------


def test_404_workspace_skipped_and_next_processed(connector: GongConnector) -> None:
    """A 404 for workspace A should be skipped; workspace B processed in the same call."""
    connector.workspaces = ["ws-A", "ws-B"]

    workspace_resp = MagicMock(spec=requests.Response)
    workspace_resp.status_code = 200
    workspace_resp.raise_for_status.return_value = None
    workspace_resp.json.return_value = {
        "workspaces": [
            {"id": "id-A", "name": "ws-A"},
            {"id": "id-B", "name": "ws-B"},
        ]
    }

    with patch.object(connector._session, "get", return_value=workspace_resp):
        with patch.object(connector._session, "post") as mock_post:
            mock_post.side_effect = [
                # Workspace A: 404
                _not_found_response(),
                # Workspace B: one page
                _transcript_response([_make_transcript("cB")], cursor=None),
                _extensive_response([_make_call_detail("cB", "Call B")]),
            ]

            outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    # Both workspaces handled in a single load_from_checkpoint call
    assert len(outputs) == 1
    cp = outputs[0].next_checkpoint
    assert cp.has_more is False
    docs = [i for i in outputs[0].items if isinstance(i, Document)]
    assert len(docs) == 1
    assert docs[0].id == "cB"


def test_all_workspaces_404_returns_no_more(connector: GongConnector) -> None:
    """If every workspace returns 404 the checkpoint should have has_more=False."""
    connector.workspaces = ["ws-A"]

    workspace_resp = MagicMock(spec=requests.Response)
    workspace_resp.status_code = 200
    workspace_resp.raise_for_status.return_value = None
    workspace_resp.json.return_value = {"workspaces": [{"id": "id-A", "name": "ws-A"}]}

    with patch.object(connector._session, "get", return_value=workspace_resp):
        with patch.object(connector._session, "post") as mock_post:
            mock_post.return_value = _not_found_response()

            outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    assert len(outputs) == 1
    assert outputs[0].next_checkpoint.has_more is False
    assert outputs[0].items == []


def test_no_workspaces_404_returns_no_more(connector: GongConnector) -> None:
    """Default (no workspaces) with 404 → done."""
    with patch.object(connector._session, "post") as mock_post:
        mock_post.return_value = _not_found_response()

        outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    assert len(outputs) == 1
    assert outputs[0].next_checkpoint.has_more is False


# ---------------------------------------------------------------------------
# Invalid / unknown workspace
# ---------------------------------------------------------------------------


def test_invalid_workspace_continue_on_fail(connector: GongConnector) -> None:
    """An unresolved workspace name with continue_on_fail=True is skipped."""
    connector.workspaces = ["unknown-ws"]
    connector.continue_on_fail = True

    workspace_resp = MagicMock(spec=requests.Response)
    workspace_resp.status_code = 200
    workspace_resp.raise_for_status.return_value = None
    workspace_resp.json.return_value = {"workspaces": [{"id": "id-A", "name": "ws-A"}]}

    with patch.object(connector._session, "get", return_value=workspace_resp):
        outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    assert len(outputs) == 1
    assert outputs[0].next_checkpoint.has_more is False
    assert outputs[0].items == []


def test_invalid_workspace_raises_when_not_continue_on_fail(
    connector: GongConnector,
) -> None:
    """An unresolved workspace name with continue_on_fail=False raises ValueError."""
    connector.workspaces = ["unknown-ws"]
    connector.continue_on_fail = False

    workspace_resp = MagicMock(spec=requests.Response)
    workspace_resp.status_code = 200
    workspace_resp.raise_for_status.return_value = None
    workspace_resp.json.return_value = {"workspaces": [{"id": "id-A", "name": "ws-A"}]}

    with patch.object(connector._session, "get", return_value=workspace_resp):
        with pytest.raises(ValueError, match="Invalid workspace"):
            list(
                connector.load_from_checkpoint(
                    _START, _END, connector.build_dummy_checkpoint()
                )
            )


# ---------------------------------------------------------------------------
# ConnectorFailure for missing call details
# ---------------------------------------------------------------------------


def test_missing_call_detail_yields_failure_when_continue_on_fail(
    connector: GongConnector,
) -> None:
    """If a call_id is in the transcript page but absent from the details map,
    a ConnectorFailure is yielded when continue_on_fail=True.

    We patch _fetch_call_details_with_retry directly so the retry loop does not
    consume extra mock responses.
    """
    connector.continue_on_fail = True
    transcripts = [_make_transcript("c1"), _make_transcript("c2")]

    # Simulate _fetch_call_details_with_retry returning only c1 (c2 is absent)
    partial_details_map = {"c1": _make_call_detail("c1", "Call 1")}

    with (
        patch.object(connector._session, "post") as mock_post,
        patch.object(
            connector,
            "_fetch_call_details_with_retry",
            return_value=partial_details_map,
        ),
    ):
        mock_post.side_effect = [
            _transcript_response(transcripts, cursor=None),
        ]

        outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    assert len(outputs) == 1
    items = outputs[0].items
    docs = [i for i in items if isinstance(i, Document)]
    failures = [i for i in items if isinstance(i, ConnectorFailure)]
    assert len(docs) == 1
    assert docs[0].id == "c1"
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == "c2"


def test_missing_call_detail_raises_when_not_continue_on_fail(
    connector: GongConnector,
) -> None:
    """If a call_id is missing from the details map and continue_on_fail=False, raise."""
    connector.continue_on_fail = False
    transcripts = [_make_transcript("c1"), _make_transcript("c2")]

    # Simulate _fetch_call_details_with_retry returning only c1
    partial_details_map = {"c1": _make_call_detail("c1", "Call 1")}

    with (
        patch.object(connector._session, "post") as mock_post,
        patch.object(
            connector,
            "_fetch_call_details_with_retry",
            return_value=partial_details_map,
        ),
    ):
        mock_post.side_effect = [
            _transcript_response(transcripts, cursor=None),
        ]

        with pytest.raises(RuntimeError, match="Couldn't get call information"):
            list(
                connector.load_from_checkpoint(
                    _START, _END, connector.build_dummy_checkpoint()
                )
            )


# ---------------------------------------------------------------------------
# hide_user_info
# ---------------------------------------------------------------------------


def test_hide_user_info_anonymises_speakers(connector: GongConnector) -> None:
    """With hide_user_info=True, speaker names should be 'User N'."""
    connector.hide_user_info = True
    transcripts = [
        {
            "callId": "c1",
            "transcript": [
                {"speakerId": "s1", "sentences": [{"text": "Hello"}]},
                {"speakerId": "s2", "sentences": [{"text": "World"}]},
            ],
        }
    ]
    details = [_make_call_detail("c1", "Hidden Call")]

    with patch.object(connector._session, "post") as mock_post:
        mock_post.side_effect = [
            _transcript_response(transcripts, cursor=None),
            _extensive_response(details),
        ]

        outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    docs = [i for i in outputs[0].items if isinstance(i, Document)]
    assert len(docs) == 1
    text = docs[0].sections[0].text
    assert "User 1" in text
    assert "User 2" in text
    assert "Alice" not in text


def test_hide_user_info_false_shows_real_names(connector: GongConnector) -> None:
    """With hide_user_info=False (default), real speaker names appear."""
    connector.hide_user_info = False
    transcripts = [
        {
            "callId": "c1",
            "transcript": [
                {"speakerId": "s1", "sentences": [{"text": "Hello"}]},
            ],
        }
    ]
    details = [_make_call_detail("c1", "Visible Call")]

    with patch.object(connector._session, "post") as mock_post:
        mock_post.side_effect = [
            _transcript_response(transcripts, cursor=None),
            _extensive_response(details),
        ]

        outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    docs = [i for i in outputs[0].items if isinstance(i, Document)]
    text = docs[0].sections[0].text
    assert "Alice (alice@example.com)" in text


# ---------------------------------------------------------------------------
# _compute_time_range
# ---------------------------------------------------------------------------


def test_compute_time_range_applies_one_day_buffer(connector: GongConnector) -> None:
    from datetime import datetime, timezone

    start_ts = datetime(2024, 1, 10, tzinfo=timezone.utc).timestamp()
    end_ts = datetime(2024, 1, 15, tzinfo=timezone.utc).timestamp()

    with patch("onyx.connectors.gong.connector.GONG_CONNECTOR_START_TIME", None):
        start_str, end_str = connector._compute_time_range(start_ts, end_ts)

    start_dt = datetime.fromisoformat(start_str)
    end_dt = datetime.fromisoformat(end_str)

    assert start_dt.date().isoformat() == "2024-01-09"  # 1 day before start
    assert end_dt.date().isoformat() == "2024-01-15"


def test_compute_time_range_respects_gong_start_time(connector: GongConnector) -> None:
    from datetime import datetime, timezone

    start_ts = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    end_ts = datetime(2024, 1, 15, tzinfo=timezone.utc).timestamp()
    # GONG_CONNECTOR_START_TIME set to Jan 10 → effective start cannot be before Jan 10
    gong_start = "2024-01-10"

    with patch("onyx.connectors.gong.connector.GONG_CONNECTOR_START_TIME", gong_start):
        start_str, end_str = connector._compute_time_range(start_ts, end_ts)

    start_dt = datetime.fromisoformat(start_str)
    # After applying the special start (Jan 10) and 1-day offset: Jan 9
    assert start_dt.date().isoformat() == "2024-01-09"


# ---------------------------------------------------------------------------
# Document fields
# ---------------------------------------------------------------------------


def test_document_fields_are_populated(connector: GongConnector) -> None:
    """Ensure the Document has the expected id, source, and metadata."""
    from onyx.configs.constants import DocumentSource

    transcripts = [_make_transcript("c1")]
    details = [_make_call_detail("c1", "My Call")]

    with patch.object(connector._session, "post") as mock_post:
        mock_post.side_effect = [
            _transcript_response(transcripts, cursor=None),
            _extensive_response(details),
        ]

        outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    docs = [i for i in outputs[0].items if isinstance(i, Document)]
    assert len(docs) == 1
    doc = docs[0]

    assert doc.id == "c1"
    assert doc.source == DocumentSource.GONG
    assert doc.semantic_identifier == "My Call"
    assert doc.sections[0].link == "https://app.gong.io/call?id=c1"
    assert doc.metadata.get("client") == "Zoom"


def test_call_purpose_prepended_to_transcript(connector: GongConnector) -> None:
    """Call purpose/description is prepended to the transcript text."""
    transcripts = [
        {
            "callId": "c1",
            "transcript": [
                {"speakerId": "s1", "sentences": [{"text": "Hi there"}]},
            ],
        }
    ]
    call_detail = _make_call_detail("c1", "Purpose Call")
    call_detail["metaData"]["purpose"] = "Quarterly review"

    with patch.object(connector._session, "post") as mock_post:
        mock_post.side_effect = [
            _transcript_response(transcripts, cursor=None),
            _extensive_response([call_detail]),
        ]

        outputs = load_everything_from_checkpoint_connector(connector, _START, _END)

    docs = [i for i in outputs[0].items if isinstance(i, Document)]
    text = docs[0].sections[0].text
    assert text.startswith("Call Description: Quarterly review")
