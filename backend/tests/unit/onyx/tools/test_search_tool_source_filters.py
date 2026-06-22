from onyx.configs.constants import DocumentSource
from onyx.context.search.models import BaseFilters
from onyx.tools.tool_implementations.search.search_tool import _parse_llm_source_types
from onyx.tools.tool_implementations.search.search_tool import (
    _with_llm_source_type_filter,
)


def test_parse_llm_source_types_normalizes_known_sources() -> None:
    assert _parse_llm_source_types(["JIRA", "confluence"]) == [
        DocumentSource.JIRA,
        DocumentSource.CONFLUENCE,
    ]


def test_parse_llm_source_types_ignores_unknown_sources() -> None:
    assert _parse_llm_source_types(["jira", "not-a-source"]) == [DocumentSource.JIRA]


def test_llm_source_filter_initializes_empty_filters() -> None:
    filters = _with_llm_source_type_filter(None, [DocumentSource.JIRA])

    assert filters == BaseFilters(source_type=[DocumentSource.JIRA])


def test_llm_source_filter_preserves_existing_filters() -> None:
    base_filters = BaseFilters(
        source_type=[DocumentSource.JIRA, DocumentSource.CONFLUENCE],
        document_set=["Engineering"],
    )

    filters = _with_llm_source_type_filter(base_filters, [DocumentSource.JIRA])

    assert filters == BaseFilters(
        source_type=[DocumentSource.JIRA],
        document_set=["Engineering"],
    )


def test_llm_source_filter_keeps_existing_scope_on_disjoint_sources() -> None:
    base_filters = BaseFilters(source_type=[DocumentSource.CONFLUENCE])

    filters = _with_llm_source_type_filter(base_filters, [DocumentSource.JIRA])

    assert filters == BaseFilters(source_type=[DocumentSource.CONFLUENCE])
