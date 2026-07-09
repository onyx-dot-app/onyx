"""Tests for OpenSearch assistant knowledge filter construction.

These tests verify that when an assistant (persona) has knowledge attached,
the search filter includes the appropriate scope filters with OR logic (not AND),
ensuring documents are discoverable across knowledge types like attached documents,
hierarchy nodes, document sets, and persona/project user files.
"""

from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.schema import ANCESTOR_HIERARCHY_NODE_IDS_FIELD_NAME
from onyx.document_index.opensearch.schema import DOCUMENT_ID_FIELD_NAME
from onyx.document_index.opensearch.schema import DOCUMENT_SETS_FIELD_NAME
from onyx.document_index.opensearch.schema import PERSONAS_FIELD_NAME
from onyx.document_index.opensearch.schema import USER_PROJECTS_FIELD_NAME
from onyx.document_index.opensearch.search import DocumentQuery
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

ATTACHED_DOCUMENT_ID = "https://docs.google.com/document/d/test-doc-id"
HIERARCHY_NODE_ID = 42
PERSONA_ID = 7
PROJECT_ID = 99
KNOWLEDGE_FILTER_SCHEMA_FIELDS = {
    DOCUMENT_ID_FIELD_NAME,
    ANCESTOR_HIERARCHY_NODE_IDS_FIELD_NAME,
    DOCUMENT_SETS_FIELD_NAME,
    PERSONAS_FIELD_NAME,
    USER_PROJECTS_FIELD_NAME,
}


def _get_search_filters(
    source_types: list[DocumentSource],
    attached_document_ids: list[str] | None,
    hierarchy_node_ids: list[int] | None,
    persona_id_filter: int | None = None,
    document_sets: list[str] | None = None,
    project_id_filter: int | None = None,
) -> list[dict[str, Any]]:
    return DocumentQuery._get_search_filters(
        tenant_state=TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False),
        include_hidden=False,
        access_control_list=["user_email:test@example.com"],
        source_types=source_types,
        tags=[],
        document_sets=document_sets or [],
        project_id_filter=project_id_filter,
        persona_id_filter=persona_id_filter,
        time_cutoff=None,
        time_cutoff_upper=None,
        min_chunk_index=None,
        max_chunk_index=None,
        max_chunk_size=None,
        document_id=None,
        attached_document_ids=attached_document_ids,
        hierarchy_node_ids=hierarchy_node_ids,
    )


def _find_knowledge_filter(
    filter_clauses: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Locate the knowledge-scope clause.

    It is the bool/should clause with ``minimum_should_match == 1`` where ANY
    should-element targets a knowledge field. Scanning every element (not just
    the first) keeps detection robust to clause reordering — the ACL and
    time-cutoff clauses use non-knowledge fields, so they are never matched.
    """
    for clause in filter_clauses:
        bool_clause = clause.get("bool")
        if not isinstance(bool_clause, dict):
            continue
        should = bool_clause.get("should")
        if not should or bool_clause.get("minimum_should_match") != 1:
            continue
        for sub in should:
            for key in ("term", "terms"):
                field = sub.get(key)
                if field and next(iter(field), None) in KNOWLEDGE_FILTER_SCHEMA_FIELDS:
                    return clause
    return None


class TestAssistantKnowledgeFilter:
    """Tests for assistant knowledge filter construction in OpenSearch queries."""

    def test_persona_id_filter_added_when_knowledge_scope_exists(self) -> None:
        """persona_id_filter should be OR'd into the knowledge scope filter
        when explicit knowledge attachments (attached_document_ids,
        hierarchy_node_ids, document_sets) are present."""
        filter_clauses = _get_search_filters(
            source_types=[DocumentSource.FILE],
            attached_document_ids=[ATTACHED_DOCUMENT_ID],
            hierarchy_node_ids=[HIERARCHY_NODE_ID],
            persona_id_filter=PERSONA_ID,
        )

        knowledge_filter = _find_knowledge_filter(filter_clauses)

        assert knowledge_filter is not None, (
            "Expected to find an assistant knowledge filter with "
            "'minimum_should_match: 1'"
        )

        should_clauses = knowledge_filter["bool"]["should"]
        persona_found = any(
            clause.get("term", {}).get(PERSONAS_FIELD_NAME, {}).get("value")
            == PERSONA_ID
            for clause in should_clauses
        )
        assert persona_found, (
            f"Expected persona_id={PERSONA_ID} filter on {PERSONAS_FIELD_NAME} "
            f"in should clauses. Got: {should_clauses}"
        )

    def test_persona_id_filter_alone_creates_knowledge_scope(self) -> None:
        """persona_id_filter IS a primary knowledge scope trigger — a persona
        with user files is explicit knowledge, so it should restrict
        search on its own."""
        filter_clauses = _get_search_filters(
            source_types=[],
            attached_document_ids=None,
            hierarchy_node_ids=None,
            persona_id_filter=PERSONA_ID,
        )

        knowledge_filter = _find_knowledge_filter(filter_clauses)

        assert knowledge_filter is not None, (
            "Expected persona_id_filter alone to create a knowledge scope filter"
        )
        persona_found = any(
            clause.get("term", {}).get(PERSONAS_FIELD_NAME, {}).get("value")
            == PERSONA_ID
            for clause in knowledge_filter["bool"]["should"]
        )
        assert persona_found, (
            f"Expected persona_id={PERSONA_ID} filter in knowledge scope. "
            f"Got: {knowledge_filter}"
        )

    def test_knowledge_filter_with_document_sets_and_persona_filter(self) -> None:
        """document_sets and persona_id_filter should be OR'd together in
        the knowledge scope filter."""
        filter_clauses = _get_search_filters(
            source_types=[],
            attached_document_ids=None,
            hierarchy_node_ids=None,
            persona_id_filter=PERSONA_ID,
            document_sets=["engineering"],
        )

        knowledge_filter = _find_knowledge_filter(filter_clauses)

        assert knowledge_filter is not None, (
            "Expected knowledge filter when document_sets is provided"
        )

        filter_str = str(knowledge_filter)
        assert "engineering" in filter_str, (
            "Expected document_set 'engineering' in knowledge filter"
        )
        assert str(PERSONA_ID) in filter_str, (
            f"Expected persona_id_filter {PERSONA_ID} in knowledge filter"
        )

    def test_project_id_filter_alone_creates_knowledge_scope(self) -> None:
        """project_id_filter IS a primary knowledge scope trigger — a chat
        inside a project is scoped to that project, so project_id_filter alone
        should restrict the search to the project's files (project chats do not
        search team knowledge)."""
        filter_clauses = _get_search_filters(
            source_types=[],
            attached_document_ids=None,
            hierarchy_node_ids=None,
            project_id_filter=PROJECT_ID,
        )

        knowledge_filter = _find_knowledge_filter(filter_clauses)

        assert knowledge_filter is not None, (
            "Expected project_id_filter alone to create a knowledge scope filter "
            "that restricts search to the project's files"
        )
        project_found = any(
            clause.get("term", {}).get(USER_PROJECTS_FIELD_NAME, {}).get("value")
            == PROJECT_ID
            for clause in knowledge_filter["bool"]["should"]
        )
        assert project_found, (
            f"Expected project_id={PROJECT_ID} filter on {USER_PROJECTS_FIELD_NAME} "
            f"in knowledge scope. Got: {knowledge_filter}"
        )

    def test_knowledge_filter_with_document_sets_and_project_filter(self) -> None:
        """document_sets and project_id_filter should be OR'd together in the
        knowledge scope filter (the default-persona-with-document-sets-in-a-
        project path) — both participate as a single should-list, widening the
        scope rather than intersecting."""
        filter_clauses = _get_search_filters(
            source_types=[],
            attached_document_ids=None,
            hierarchy_node_ids=None,
            document_sets=["engineering"],
            project_id_filter=PROJECT_ID,
        )

        knowledge_filter = _find_knowledge_filter(filter_clauses)
        assert knowledge_filter is not None, (
            "Expected knowledge filter when document_sets and project_id_filter "
            "are both provided"
        )

        should_clauses = knowledge_filter["bool"]["should"]
        document_set_found = any(
            "engineering" in str(clause) for clause in should_clauses
        )
        project_found = any(
            clause.get("term", {}).get(USER_PROJECTS_FIELD_NAME, {}).get("value")
            == PROJECT_ID
            for clause in should_clauses
        )
        assert document_set_found, (
            f"Expected document_set 'engineering' OR'd into the knowledge scope. "
            f"Got: {should_clauses}"
        )
        assert project_found, (
            f"Expected project_id={PROJECT_ID} OR'd into the knowledge scope. "
            f"Got: {should_clauses}"
        )

    def test_no_knowledge_scope_when_all_filters_empty(self) -> None:
        """When no knowledge-scope inputs are set, NO knowledge bool/should
        clause should be produced — the search is unrestricted (subject to ACL).

        Guards against a regression that would append an empty should-list with
        ``minimum_should_match: 1`` (which would match nothing)."""
        filter_clauses = _get_search_filters(
            source_types=[],
            attached_document_ids=None,
            hierarchy_node_ids=None,
            persona_id_filter=None,
            document_sets=None,
            project_id_filter=None,
        )

        assert _find_knowledge_filter(filter_clauses) is None, (
            "No knowledge-scope clause should be produced when every knowledge "
            "input is empty/None"
        )
