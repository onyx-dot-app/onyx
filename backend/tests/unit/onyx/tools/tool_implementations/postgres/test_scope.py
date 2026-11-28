from datetime import datetime, timezone

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import BaseFilters, PersonaSearchInfo, TimeRange
from onyx.db.postgres_tool_models import DocumentScope
from onyx.tools.tool_implementations.postgres.scope import build_document_scope

_FLOOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
_PERSONA = PersonaSearchInfo(
    document_set_names=["Eng"],
    search_start_date=_FLOOR,
    attached_document_ids=["doc-1"],
    hierarchy_node_ids=[7],
)


def test_persona_knowledge_without_request_filters() -> None:
    scope = build_document_scope(_PERSONA, None, None, None)
    assert scope == DocumentScope(
        document_set_names=["Eng"],
        attached_document_ids=["doc-1"],
        hierarchy_node_ids=[7],
        updated_at_range=TimeRange(start=_FLOOR),
    )
    assert not scope.matches_no_documents


def test_request_document_sets_replace_the_personas() -> None:
    scope = build_document_scope(
        _PERSONA, BaseFilters(document_set=["Sales"]), None, None
    )
    assert scope.document_set_names == ["Sales"]
    assert scope.attached_document_ids == ["doc-1"]


def test_request_cannot_loosen_the_start_floor() -> None:
    earlier = datetime(2025, 1, 1, tzinfo=timezone.utc)
    later = datetime(2026, 6, 1, tzinfo=timezone.utc)
    loosened = build_document_scope(
        _PERSONA, BaseFilters(updated_at_range=TimeRange(start=earlier)), None, None
    )
    assert loosened.updated_at_range == TimeRange(start=_FLOOR)
    raised = build_document_scope(
        _PERSONA, BaseFilters(updated_at_range=TimeRange(start=later)), None, None
    )
    assert raised.updated_at_range == TimeRange(start=later)


def test_request_source_types_pass_through() -> None:
    scope = build_document_scope(
        None, BaseFilters(source_type=[DocumentSource.SLACK]), None, None
    )
    assert scope.source_types == [DocumentSource.SLACK]
    assert not scope.restricts_knowledge
    assert build_document_scope(
        None, BaseFilters(source_type=[]), None, None
    ).matches_no_documents


def test_project_only_search_matches_no_documents() -> None:
    scope = build_document_scope(
        _PERSONA, BaseFilters(source_type=[DocumentSource.SLACK]), 3, None
    )
    assert scope == DocumentScope(includes_user_files=True)
    assert scope.matches_no_documents


def test_persona_files_join_the_persona_knowledge() -> None:
    scope = build_document_scope(_PERSONA, None, 3, 5)
    assert scope.includes_user_files
    assert scope.has_document_knowledge
    assert not scope.matches_no_documents


def test_no_persona_and_no_filters_is_unrestricted() -> None:
    assert build_document_scope(None, None, None, None).is_unrestricted
