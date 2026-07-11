"""Pins how created_at_range / updated_at_range turn into range clauses and
when undated documents are included, via `DocumentQuery._get_search_filters`
(a pure DSL builder, no live OpenSearch). Intent-to-range mapping:
document_index/FILTER_SEMANTICS.md ("Time filtering").
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from onyx.context.search.models import TimeRange
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.constants import ASSUMED_DOCUMENT_AGE_DAYS
from onyx.document_index.opensearch.schema import CREATED_AT_FIELD_NAME
from onyx.document_index.opensearch.schema import LAST_UPDATED_FIELD_NAME
from onyx.document_index.opensearch.search import DocumentQuery
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def _build_filters(
    created_at_range: TimeRange | None = None,
    updated_at_range: TimeRange | None = None,
) -> list[dict[str, Any]]:
    """Build the filter clauses with only the time ranges set. ACL and the
    hidden clause are suppressed so the time clauses (if any) are the sole
    result."""
    return DocumentQuery._get_search_filters(
        tenant_state=TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False),
        include_hidden=True,
        access_control_list=None,
        source_types=[],
        tags=[],
        document_sets=[],
        project_id_filter=None,
        persona_id_filter=None,
        created_at_range=created_at_range,
        updated_at_range=updated_at_range,
        min_chunk_index=None,
        max_chunk_index=None,
        max_chunk_size=None,
        document_id=None,
        attached_document_ids=None,
        hierarchy_node_ids=None,
    )


def _clause_for_field(
    filter_clauses: list[dict[str, Any]], field_name: str
) -> dict[str, Any] | None:
    """Locate a date range clause: a bool/should whose first element is a
    `range` on the given field."""
    for clause in filter_clauses:
        should = clause.get("bool", {}).get("should")
        if should and "range" in should[0] and field_name in should[0]["range"]:
            return clause
    return None


def _range_bounds(clause: dict[str, Any], field_name: str) -> dict[str, int]:
    return clause["bool"]["should"][0]["range"][field_name]


def _includes_undated(clause: dict[str, Any]) -> bool:
    """Whether the clause ORs in documents that have no value for its field."""
    return any(
        isinstance(sub.get("bool"), dict) and "must_not" in sub["bool"]
        for sub in clause["bool"]["should"]
    )


def _old() -> datetime:
    """A lower bound older than the undated-inclusion threshold."""
    return datetime.now(timezone.utc) - timedelta(days=ASSUMED_DOCUMENT_AGE_DAYS + 10)


def test_no_time_filter_produces_no_clause() -> None:
    assert _clause_for_field(_build_filters(), LAST_UPDATED_FIELD_NAME) is None
    assert _clause_for_field(_build_filters(), CREATED_AT_FIELD_NAME) is None


def test_created_in_window_bounds_created_at_on_both_ends() -> None:
    """'created between X and Y' -> a single created_at range with both bounds.
    Documents with no created_at are always kept (over-extend)."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 3, 31, tzinfo=timezone.utc)
    clauses = _build_filters(created_at_range=TimeRange(start=start, end=end))

    created = _clause_for_field(clauses, CREATED_AT_FIELD_NAME)
    assert created is not None
    assert _range_bounds(created, CREATED_AT_FIELD_NAME) == {
        "gte": int(start.timestamp()),
        "lte": int(end.timestamp()),
    }
    assert _includes_undated(created)
    # A created-intent query must not touch last_updated.
    assert _clause_for_field(clauses, LAST_UPDATED_FIELD_NAME) is None


def test_updated_in_past_window_uses_overlap_not_strict_last_updated() -> None:
    """'updated in [S, E]' is the overlap (last_updated >= S AND created_at <= E),
    not a strict last_updated range — a strict upper bound would drop docs
    edited again after E whose earlier in-window edit is unstored."""
    start = datetime.now(timezone.utc) - timedelta(days=7 * 30)
    end = datetime.now(timezone.utc) - timedelta(days=4 * 30)
    clauses = _build_filters(
        created_at_range=TimeRange(end=end),
        updated_at_range=TimeRange(start=start),
    )

    updated = _clause_for_field(clauses, LAST_UPDATED_FIELD_NAME)
    assert updated is not None
    assert _range_bounds(updated, LAST_UPDATED_FIELD_NAME) == {
        "gte": int(start.timestamp())
    }
    # No upper bound on last_updated -> a later stored edit does not exclude.
    assert "lte" not in _range_bounds(updated, LAST_UPDATED_FIELD_NAME)

    created = _clause_for_field(clauses, CREATED_AT_FIELD_NAME)
    assert created is not None
    assert _range_bounds(created, CREATED_AT_FIELD_NAME) == {
        "lte": int(end.timestamp())
    }

    # The scenario doc (created 8mo, latest edit 2mo) satisfies both clauses.
    created_8mo = int((datetime.now(timezone.utc) - timedelta(days=8 * 30)).timestamp())
    updated_2mo = int((datetime.now(timezone.utc) - timedelta(days=2 * 30)).timestamp())
    assert updated_2mo >= _range_bounds(updated, LAST_UPDATED_FIELD_NAME)["gte"]
    assert created_8mo <= _range_bounds(created, CREATED_AT_FIELD_NAME)["lte"]


def test_updated_since_recent_excludes_undated() -> None:
    """'changed since a day ago' -> last_updated >= start; a recent, open-ended
    lower bound excludes undated docs (they are not assumed recent)."""
    start = datetime.now(timezone.utc) - timedelta(days=1)
    clauses = _build_filters(updated_at_range=TimeRange(start=start))

    updated = _clause_for_field(clauses, LAST_UPDATED_FIELD_NAME)
    assert updated is not None
    assert _range_bounds(updated, LAST_UPDATED_FIELD_NAME) == {
        "gte": int(start.timestamp())
    }
    assert not _includes_undated(updated)


def test_updated_since_old_open_bound_includes_undated() -> None:
    """An old, open-ended last_updated lower bound ORs in undated docs."""
    start = _old()
    clauses = _build_filters(updated_at_range=TimeRange(start=start))

    updated = _clause_for_field(clauses, LAST_UPDATED_FIELD_NAME)
    assert updated is not None
    assert _includes_undated(updated)


def test_active_in_window_splits_across_fields() -> None:
    """'active in [S, E]' (e.g. "what was Dane working on last Thursday") ->
    last_updated >= S AND created_at <= E. Approximates activity in the window
    from a document's [created_at, last_updated] span."""
    start = datetime(2025, 7, 3, tzinfo=timezone.utc)
    end = datetime(2025, 7, 4, tzinfo=timezone.utc)
    clauses = _build_filters(
        created_at_range=TimeRange(end=end),
        updated_at_range=TimeRange(start=start),
    )

    updated = _clause_for_field(clauses, LAST_UPDATED_FIELD_NAME)
    assert updated is not None
    assert _range_bounds(updated, LAST_UPDATED_FIELD_NAME) == {
        "gte": int(start.timestamp())
    }

    created = _clause_for_field(clauses, CREATED_AT_FIELD_NAME)
    assert created is not None
    assert _range_bounds(created, CREATED_AT_FIELD_NAME) == {
        "lte": int(end.timestamp())
    }
    # created_at-less docs are always kept, regardless of the other clause.
    assert _includes_undated(created)


def test_naive_bounds_are_treated_as_utc() -> None:
    """Naive (timezone-less) bounds coerce to UTC at model construction, so
    downstream aware-datetime comparisons (e.g. the persona floor fold) and
    epoch conversions cannot fail or drift."""
    time_range = TimeRange(start=datetime(2024, 1, 1), end=datetime(2024, 3, 31))
    assert time_range.start is not None and time_range.start.tzinfo == timezone.utc
    assert time_range.end is not None and time_range.end.tzinfo == timezone.utc
    # Comparable against aware datetimes (this raised TypeError when naive).
    assert time_range.start < datetime.now(timezone.utc)
    # Aware bounds pass through untouched.
    aware = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert TimeRange(start=aware).start == aware


def test_empty_range_is_skipped() -> None:
    """A range with neither bound set contributes no clause."""
    clauses = _build_filters(created_at_range=TimeRange())
    assert _clause_for_field(clauses, CREATED_AT_FIELD_NAME) is None
