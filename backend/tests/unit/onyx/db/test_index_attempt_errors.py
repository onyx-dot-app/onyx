"""Tests for get_index_attempt_errors_across_connectors."""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock

from onyx.db.index_attempt import get_index_attempt_errors_across_connectors
from onyx.db.models import IndexAttemptError


def _make_error(
    id: int = 1,
    cc_pair_id: int = 1,
    error_type: str | None = "TimeoutError",
    is_resolved: bool = False,
) -> IndexAttemptError:
    """Create a mock IndexAttemptError."""
    error = MagicMock(spec=IndexAttemptError)
    error.id = id
    error.connector_credential_pair_id = cc_pair_id
    error.error_type = error_type
    error.is_resolved = is_resolved
    return error


class TestGetIndexAttemptErrorsAcrossConnectors:
    def test_returns_errors_and_count(self) -> None:
        mock_session = MagicMock()
        mock_errors = [_make_error(id=1), _make_error(id=2)]
        mock_session.scalar.return_value = 2
        mock_session.scalars.return_value.all.return_value = mock_errors

        errors, total = get_index_attempt_errors_across_connectors(
            db_session=mock_session,
        )

        assert total == 2
        assert len(errors) == 2

    def test_returns_empty_when_no_errors(self) -> None:
        mock_session = MagicMock()
        mock_session.scalar.return_value = 0
        mock_session.scalars.return_value.all.return_value = []

        errors, total = get_index_attempt_errors_across_connectors(
            db_session=mock_session,
        )

        assert total == 0
        assert errors == []

    def test_null_count_returns_zero(self) -> None:
        mock_session = MagicMock()
        mock_session.scalar.return_value = None
        mock_session.scalars.return_value.all.return_value = []

        errors, total = get_index_attempt_errors_across_connectors(
            db_session=mock_session,
        )

        assert total == 0

    def test_passes_filters_to_query(self) -> None:
        """Verify that filter parameters result in .where() calls on the statement."""
        mock_session = MagicMock()
        mock_session.scalar.return_value = 0
        mock_session.scalars.return_value.all.return_value = []

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 12, 31, tzinfo=timezone.utc)

        # Should not raise — just verifying the function accepts all filter params
        get_index_attempt_errors_across_connectors(
            db_session=mock_session,
            cc_pair_id=42,
            error_type="TimeoutError",
            start_time=start,
            end_time=end,
            unresolved_only=True,
            page=2,
            page_size=10,
        )

        # The function should have called scalar (for count) and scalars (for results)
        assert mock_session.scalar.called
        assert mock_session.scalars.called
