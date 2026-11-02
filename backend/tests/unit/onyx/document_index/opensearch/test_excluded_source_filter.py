"""The clause that withholds a source from a query.

A caller that retrieves a source through a lane of its own needs the default
lane to leave it alone. The clause must intersect with every other filter
rather than widen one, so asking for one source cannot bring an excluded one
back.
"""

from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch.schema import SOURCE_TYPE_FIELD_NAME
from onyx.document_index.opensearch.search import DocumentQuery
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

WITHHELD = DocumentSource.MOCK_CONNECTOR


def _build_filters(
    source_types: list[DocumentSource] | None = None,
    excluded_source_types: list[DocumentSource] | None = None,
) -> list[dict[str, Any]]:
    return DocumentQuery._get_search_filters(
        tenant_state=TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False),
        include_hidden=True,
        access_control_list=None,
        cc_pair_access=None,
        source_types=source_types or [],
        excluded_source_types=excluded_source_types or [],
        tags=[],
        document_sets=[],
        project_id_filter=None,
        persona_id_filter=None,
        created_at_range=None,
        updated_at_range=None,
        min_chunk_index=None,
        max_chunk_index=None,
    )


def _must_not_sources(clauses: list[dict[str, Any]]) -> list[list[str]]:
    return [
        inner["terms"][SOURCE_TYPE_FIELD_NAME]
        for clause in clauses
        if "bool" in clause
        for inner in clause["bool"].get("must_not", [])
        if "terms" in inner
    ]


def test_no_exclusion_adds_no_clause() -> None:
    assert _build_filters() == []


def test_a_withheld_source_becomes_a_must_not_clause() -> None:
    clauses = _build_filters(excluded_source_types=[WITHHELD])

    assert _must_not_sources(clauses) == [[WITHHELD.value]]


def test_the_exclusion_is_its_own_clause_beside_an_inclusion() -> None:
    """Separate clauses are ANDed, so asking for one source cannot bring a
    withheld one back."""
    clauses = _build_filters(
        source_types=[DocumentSource.WEB], excluded_source_types=[WITHHELD]
    )

    assert len(clauses) == 2
    assert _must_not_sources(clauses) == [[WITHHELD.value]]
