"""Unit tests for the OpenSearch time-cutoff filter construction.

These exercise `DocumentQuery._get_search_filters` directly (a pure DSL builder,
no live OpenSearch) to pin how `time_cutoff` / `time_cutoff_upper` turn into the
`last_updated` range clause, and when undated documents are included. Mirrors the
Vespa coverage in `tests/unit/onyx/utils/test_vespa_query.py`.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.constants import ASSUMED_DOCUMENT_AGE_DAYS
from onyx.document_index.opensearch.schema import LAST_UPDATED_FIELD_NAME
from onyx.document_index.opensearch.search import DocumentQuery
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def _build_time_filters(
    time_cutoff: datetime | None,
    time_cutoff_upper: datetime | None,
) -> list[dict[str, Any]]:
    """Build the filter clauses with only the time bounds set. ACL and the
    hidden clause are suppressed so the time clause (if any) is the sole result."""
    return DocumentQuery._get_search_filters(
        tenant_state=TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False),
        include_hidden=True,
        access_control_list=None,
        source_types=[],
        tags=[],
        document_sets=[],
        project_id_filter=None,
        persona_id_filter=None,
        time_cutoff=time_cutoff,
        time_cutoff_upper=time_cutoff_upper,
        min_chunk_index=None,
        max_chunk_index=None,
        max_chunk_size=None,
        document_id=None,
        attached_document_ids=None,
        hierarchy_node_ids=None,
    )


def _time_clause(filter_clauses: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Locate the time-cutoff clause: a bool/should whose first element is a
    `range` on the last-updated field."""
    for clause in filter_clauses:
        should = clause.get("bool", {}).get("should")
        if (
            should
            and "range" in should[0]
            and LAST_UPDATED_FIELD_NAME in should[0]["range"]
        ):
            return clause
    return None


def _range_bounds(clause: dict[str, Any]) -> dict[str, int]:
    return clause["bool"]["should"][0]["range"][LAST_UPDATED_FIELD_NAME]


def _includes_undated(clause: dict[str, Any]) -> bool:
    """Whether the clause ORs in documents that have no last-updated value."""
    return any(
        isinstance(sub.get("bool"), dict) and "must_not" in sub["bool"]
        for sub in clause["bool"]["should"]
    )


def _old() -> datetime:
    """A lower bound older than the undated-inclusion threshold."""
    return datetime.now(timezone.utc) - timedelta(days=ASSUMED_DOCUMENT_AGE_DAYS + 10)


def test_no_time_filter_produces_no_clause() -> None:
    assert _time_clause(_build_time_filters(None, None)) is None


def test_recent_lower_bound_excludes_undated() -> None:
    """A recent lower bound is a strict `gte`; undated docs are not assumed
    recent, so they are excluded."""
    start = datetime.now(timezone.utc) - timedelta(days=1)
    clause = _time_clause(_build_time_filters(start, None))
    assert clause is not None
    assert _range_bounds(clause) == {"gte": int(start.timestamp())}
    assert not _includes_undated(clause)


def test_old_open_ended_lower_bound_includes_undated() -> None:
    """An old, open-ended lower bound assumes undated docs may be that old, so
    they are OR'd in via a `must_not exists` should-element."""
    start = _old()
    clause = _time_clause(_build_time_filters(start, None))
    assert clause is not None
    assert _range_bounds(clause) == {"gte": int(start.timestamp())}
    assert _includes_undated(clause)


def test_upper_bound_only() -> None:
    """An upper bound alone is a strict `lte`; undated docs are excluded (there
    is no lower bound that could vouch for them)."""
    end = datetime(2023, 6, 1, tzinfo=timezone.utc)
    clause = _time_clause(_build_time_filters(None, end))
    assert clause is not None
    assert _range_bounds(clause) == {"lte": int(end.timestamp())}
    assert not _includes_undated(clause)


def test_bounded_range_excludes_undated_even_when_lower_bound_is_old() -> None:
    """A bounded range emits both `gte` and `lte`. Undated docs are excluded even
    though the lower bound is old — an undated doc cannot be shown to fall within
    a closed range."""
    start = _old()
    end = datetime.now(timezone.utc) - timedelta(days=1)
    clause = _time_clause(_build_time_filters(start, end))
    assert clause is not None
    assert _range_bounds(clause) == {
        "gte": int(start.timestamp()),
        "lte": int(end.timestamp()),
    }
    assert not _includes_undated(clause)
