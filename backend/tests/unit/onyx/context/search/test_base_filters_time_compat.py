"""Wire-compat tests for the deprecated time_cutoff alias on BaseFilters.

Older API clients send time_cutoff in request bodies
(e.g. SendMessageRequest.internal_search_filters, AdminSearchRequest.filters);
it must keep filtering on document update time via updated_at_range.
"""

from datetime import datetime
from datetime import timezone

from onyx.context.search.models import BaseFilters
from onyx.context.search.models import TimeRange

_START = datetime(2025, 11, 24, tzinfo=timezone.utc)


def test_time_cutoff_folds_into_updated_at_range() -> None:
    filters = BaseFilters.model_validate({"time_cutoff": "2025-11-24T00:00:00Z"})

    assert filters.updated_at_range == TimeRange(start=_START)
    assert filters.time_cutoff is None


def test_naive_time_cutoff_treated_as_utc() -> None:
    filters = BaseFilters.model_validate({"time_cutoff": "2025-11-24T00:00:00"})

    assert filters.updated_at_range == TimeRange(start=_START)


def test_explicit_updated_at_range_wins_over_alias() -> None:
    filters = BaseFilters.model_validate(
        {
            "time_cutoff": "2020-01-01T00:00:00Z",
            "updated_at_range": {"start": "2025-11-24T00:00:00Z"},
        }
    )

    assert filters.updated_at_range == TimeRange(start=_START)


def test_alias_excluded_from_serialization() -> None:
    filters = BaseFilters.model_validate({"time_cutoff": "2025-11-24T00:00:00Z"})

    assert "time_cutoff" not in filters.model_dump()


def test_no_time_fields_stays_none() -> None:
    filters = BaseFilters()

    assert filters.updated_at_range is None
    assert filters.created_at_range is None
