from datetime import datetime
from datetime import timezone
from unittest.mock import patch

from onyx.connectors.fireflies.connector import _FIREFLIES_POLL_OVERLAP_SECONDS
from onyx.connectors.fireflies.connector import FirefliesConnector


def _fmt(epoch_seconds: int) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def test_poll_source_subtracts_overlap_from_start() -> None:
    """poll_source must look back by the overlap so transcripts that became
    available after their start-time window was first polled are still fetched."""
    connector = FirefliesConnector()
    connector.load_credentials({"fireflies_api_key": "test-key"})

    start = 1_700_000_000
    end = start + 3600

    with patch.object(
        FirefliesConnector, "_process_transcripts", side_effect=lambda *_: iter([])
    ) as mock_proc:
        list(connector.poll_source(start, end))

    mock_proc.assert_called_once()
    start_datetime, end_datetime = mock_proc.call_args.args
    assert start_datetime == _fmt(start - _FIREFLIES_POLL_OVERLAP_SECONDS)
    assert end_datetime == _fmt(end)


def test_poll_source_clamps_overlap_at_epoch() -> None:
    """A start within the overlap of epoch 0 must not go negative."""
    connector = FirefliesConnector()
    connector.load_credentials({"fireflies_api_key": "test-key"})

    with patch.object(
        FirefliesConnector, "_process_transcripts", side_effect=lambda *_: iter([])
    ) as mock_proc:
        list(connector.poll_source(100, 200))

    start_datetime, _ = mock_proc.call_args.args
    assert start_datetime == _fmt(0)
