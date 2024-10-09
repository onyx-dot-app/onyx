from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from danswer.db.index_attempt import IndexAttempt
from danswer.indexing.indexing_heartbeat import IndexingHeartbeat


@pytest.fixture
def mock_db_session() -> MagicMock:
    return MagicMock(spec=Session)


@pytest.fixture
def mock_index_attempt() -> MagicMock:
    return MagicMock(spec=IndexAttempt)


def test_indexing_heartbeat(
    mock_db_session: MagicMock, mock_index_attempt: MagicMock
) -> None:
    with patch(
        "danswer.indexing.indexing_heartbeat.get_index_attempt"
    ) as mock_get_index_attempt:
        mock_get_index_attempt.return_value = mock_index_attempt

        heartbeat = IndexingHeartbeat(
            index_attempt_id=1, db_session=mock_db_session, freq=5
        )

        # Test that heartbeat doesn't update before freq is reached
        for _ in range(4):
            heartbeat.heartbeat()

        mock_db_session.commit.assert_not_called()

        # Test that heartbeat updates when freq is reached
        heartbeat.heartbeat()

        mock_get_index_attempt.assert_called_once_with(
            db_session=mock_db_session, index_attempt_id=1
        )
        assert mock_index_attempt.time_updated is not None
        mock_db_session.commit.assert_called_once()

        # Reset mock calls
        mock_db_session.reset_mock()
        mock_get_index_attempt.reset_mock()

        # Test that heartbeat updates again after freq more calls
        for _ in range(5):
            heartbeat.heartbeat()

        mock_get_index_attempt.assert_called_once()
        mock_db_session.commit.assert_called_once()


def test_indexing_heartbeat_not_found(mock_db_session: MagicMock) -> None:
    with patch(
        "danswer.indexing.indexing_heartbeat.get_index_attempt"
    ) as mock_get_index_attempt, patch(
        "danswer.indexing.indexing_heartbeat.logger"
    ) as mock_logger:
        mock_get_index_attempt.return_value = None

        heartbeat = IndexingHeartbeat(
            index_attempt_id=1, db_session=mock_db_session, freq=1
        )

        heartbeat.heartbeat()

        mock_get_index_attempt.assert_called_once_with(
            db_session=mock_db_session, index_attempt_id=1
        )
        mock_logger.error.assert_called_once_with(
            "Index attempt not found, this should not happen!"
        )
        mock_db_session.commit.assert_not_called()
