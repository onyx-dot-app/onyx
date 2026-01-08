"""Unit tests for tenant usage tracking and limits."""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.db.usage import check_usage_limit
from onyx.db.usage import get_current_window_start
from onyx.db.usage import get_or_create_tenant_usage
from onyx.db.usage import get_tenant_usage_stats
from onyx.db.usage import increment_usage
from onyx.db.usage import TenantUsageStats
from onyx.db.usage import UsageLimitExceededError
from onyx.db.usage import UsageType


class TestGetCurrentWindowStart:
    """Tests for get_current_window_start function."""

    def test_weekly_window_aligns_to_monday(self) -> None:
        """Test that weekly windows align to Monday 00:00 UTC."""
        with patch("onyx.db.usage.USAGE_LIMIT_WINDOW_SECONDS", 604800):  # 1 week
            window_start = get_current_window_start()

            # Window should be on a Monday
            assert window_start.weekday() == 0  # Monday

            # Window should be at midnight UTC
            assert window_start.hour == 0
            assert window_start.minute == 0
            assert window_start.second == 0
            assert window_start.microsecond == 0

    def test_window_start_is_timezone_aware(self) -> None:
        """Test that window start is timezone-aware."""
        window_start = get_current_window_start()
        assert window_start.tzinfo is not None


class TestGetOrCreateTenantUsage:
    """Tests for get_or_create_tenant_usage function."""

    def test_creates_or_gets_usage_record(self) -> None:
        """Test that get_or_create returns a usage record via atomic upsert."""
        mock_usage = MagicMock()
        mock_usage.llm_cost_cents = 0.0
        mock_usage.chunks_indexed = 0

        mock_session = MagicMock()
        # The new implementation uses INSERT ... ON CONFLICT with RETURNING
        # which calls execute().scalar_one()
        mock_session.execute.return_value.scalar_one.return_value = mock_usage

        window_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        usage = get_or_create_tenant_usage(mock_session, window_start)

        # Verify execute was called (with the INSERT ... ON CONFLICT statement)
        mock_session.execute.assert_called_once()
        mock_session.flush.assert_called_once()
        assert usage == mock_usage

    def test_returns_usage_record_from_atomic_upsert(self) -> None:
        """Test that the returned usage record comes from the atomic upsert."""
        mock_usage = MagicMock()
        mock_usage.llm_cost_cents = 100.0
        mock_usage.chunks_indexed = 500

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one.return_value = mock_usage

        window_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        usage = get_or_create_tenant_usage(mock_session, window_start)

        assert usage == mock_usage
        assert usage.llm_cost_cents == 100.0
        assert usage.chunks_indexed == 500


class TestGetTenantUsageStats:
    """Tests for get_tenant_usage_stats function."""

    def test_returns_zero_stats_when_no_record_exists(self) -> None:
        """Test that zero stats are returned when no usage record exists."""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        window_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        stats = get_tenant_usage_stats(mock_session, window_start)

        assert stats.llm_cost_cents == 0.0
        assert stats.chunks_indexed == 0
        assert stats.api_calls == 0
        assert stats.non_streaming_api_calls == 0

    def test_returns_actual_stats_when_record_exists(self) -> None:
        """Test that actual stats are returned when usage record exists."""
        mock_usage = MagicMock()
        mock_usage.window_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_usage.llm_cost_cents = 250.5
        mock_usage.chunks_indexed = 1000
        mock_usage.api_calls = 50
        mock_usage.non_streaming_api_calls = 10

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_usage

        stats = get_tenant_usage_stats(mock_session)

        assert stats.llm_cost_cents == 250.5
        assert stats.chunks_indexed == 1000
        assert stats.api_calls == 50
        assert stats.non_streaming_api_calls == 10


class TestIncrementUsage:
    """Tests for increment_usage function."""

    def test_increments_llm_cost(self) -> None:
        """Test that LLM cost is incremented correctly."""
        mock_usage = MagicMock()
        mock_usage.llm_cost_cents = 100.0

        mock_session = MagicMock()

        with patch("onyx.db.usage.get_or_create_tenant_usage", return_value=mock_usage):
            increment_usage(mock_session, UsageType.LLM_COST, 50.5)

        assert mock_usage.llm_cost_cents == 150.5
        mock_session.flush.assert_called_once()

    def test_increments_chunks_indexed(self) -> None:
        """Test that chunks indexed is incremented correctly."""
        mock_usage = MagicMock()
        mock_usage.chunks_indexed = 500

        mock_session = MagicMock()

        with patch("onyx.db.usage.get_or_create_tenant_usage", return_value=mock_usage):
            increment_usage(mock_session, UsageType.CHUNKS_INDEXED, 100)

        assert mock_usage.chunks_indexed == 600

    def test_increments_api_calls(self) -> None:
        """Test that API calls is incremented correctly."""
        mock_usage = MagicMock()
        mock_usage.api_calls = 10

        mock_session = MagicMock()

        with patch("onyx.db.usage.get_or_create_tenant_usage", return_value=mock_usage):
            increment_usage(mock_session, UsageType.API_CALLS, 1)

        assert mock_usage.api_calls == 11

    def test_increments_non_streaming_calls(self) -> None:
        """Test that non-streaming API calls is incremented correctly."""
        mock_usage = MagicMock()
        mock_usage.non_streaming_api_calls = 5

        mock_session = MagicMock()

        with patch("onyx.db.usage.get_or_create_tenant_usage", return_value=mock_usage):
            increment_usage(mock_session, UsageType.NON_STREAMING_API_CALLS, 1)

        assert mock_usage.non_streaming_api_calls == 6


class TestCheckUsageLimit:
    """Tests for check_usage_limit function."""

    def test_passes_when_under_limit(self) -> None:
        """Test that check passes when usage is under the limit."""
        mock_session = MagicMock()

        mock_stats = TenantUsageStats(
            window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            llm_cost_cents=100.0,
            chunks_indexed=500,
            api_calls=10,
            non_streaming_api_calls=5,
        )

        with patch("onyx.db.usage.get_tenant_usage_stats", return_value=mock_stats):
            # Should not raise
            check_usage_limit(
                mock_session,
                UsageType.LLM_COST,
                limit=500,
                pending_amount=0,
            )

    def test_passes_when_exactly_at_limit(self) -> None:
        """Test that check passes when usage is exactly at the limit."""
        mock_session = MagicMock()

        mock_stats = TenantUsageStats(
            window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            llm_cost_cents=500.0,
            chunks_indexed=500,
            api_calls=10,
            non_streaming_api_calls=5,
        )

        with patch("onyx.db.usage.get_tenant_usage_stats", return_value=mock_stats):
            # Should not raise - at limit but not over
            check_usage_limit(
                mock_session,
                UsageType.LLM_COST,
                limit=500,
                pending_amount=0,
            )

    def test_fails_when_over_limit(self) -> None:
        """Test that check fails when usage exceeds the limit."""
        mock_session = MagicMock()

        mock_stats = TenantUsageStats(
            window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            llm_cost_cents=501.0,
            chunks_indexed=500,
            api_calls=10,
            non_streaming_api_calls=5,
        )

        with patch("onyx.db.usage.get_tenant_usage_stats", return_value=mock_stats):
            with pytest.raises(UsageLimitExceededError) as exc_info:
                check_usage_limit(
                    mock_session,
                    UsageType.LLM_COST,
                    limit=500,
                    pending_amount=0,
                )

            assert exc_info.value.usage_type == UsageType.LLM_COST
            assert exc_info.value.current == 501.0
            assert exc_info.value.limit == 500.0

    def test_fails_when_pending_would_exceed_limit(self) -> None:
        """Test that check fails when pending amount would exceed the limit."""
        mock_session = MagicMock()

        mock_stats = TenantUsageStats(
            window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            llm_cost_cents=400.0,
            chunks_indexed=500,
            api_calls=10,
            non_streaming_api_calls=5,
        )

        with patch("onyx.db.usage.get_tenant_usage_stats", return_value=mock_stats):
            with pytest.raises(UsageLimitExceededError) as exc_info:
                check_usage_limit(
                    mock_session,
                    UsageType.LLM_COST,
                    limit=500,
                    pending_amount=150,  # 400 + 150 = 550 > 500
                )

            assert exc_info.value.current == 550.0  # includes pending

    def test_checks_chunks_indexed_limit(self) -> None:
        """Test that chunk indexing limit is checked correctly."""
        mock_session = MagicMock()

        mock_stats = TenantUsageStats(
            window_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            llm_cost_cents=100.0,
            chunks_indexed=10001,
            api_calls=10,
            non_streaming_api_calls=5,
        )

        with patch("onyx.db.usage.get_tenant_usage_stats", return_value=mock_stats):
            with pytest.raises(UsageLimitExceededError) as exc_info:
                check_usage_limit(
                    mock_session,
                    UsageType.CHUNKS_INDEXED,
                    limit=10000,
                    pending_amount=0,
                )

            assert exc_info.value.usage_type == UsageType.CHUNKS_INDEXED


class TestUsageLimitExceededError:
    """Tests for UsageLimitExceededError exception."""

    def test_error_message_format(self) -> None:
        """Test that error message is formatted correctly."""
        error = UsageLimitExceededError(
            usage_type=UsageType.LLM_COST,
            current=150.5,
            limit=100.0,
        )

        assert "llm_cost_cents" in str(error)
        assert "150.5" in str(error)
        assert "100" in str(error)

    def test_stores_values(self) -> None:
        """Test that error stores all values correctly."""
        error = UsageLimitExceededError(
            usage_type=UsageType.API_CALLS,
            current=1001,
            limit=1000,
        )

        assert error.usage_type == UsageType.API_CALLS
        assert error.current == 1001
        assert error.limit == 1000


class TestWindowRollover:
    """Tests for window rollover behavior."""

    def test_new_window_resets_usage(self) -> None:
        """Test that a new window has zero usage even if previous window had usage."""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        # Get stats for a new window (no existing record)
        with patch(
            "onyx.db.usage.get_current_window_start",
            return_value=datetime(2024, 1, 8, tzinfo=timezone.utc),
        ):
            stats = get_tenant_usage_stats(mock_session)

        # New window should have zero usage
        assert stats.llm_cost_cents == 0.0
        assert stats.chunks_indexed == 0
        assert stats.api_calls == 0
        assert stats.non_streaming_api_calls == 0
