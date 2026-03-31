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
from onyx.document_index.opensearch.search import DocumentQuery
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

ATTACHED_DOCUMENT_ID = "https://docs.google.com/document/d/test-doc-id"
HIERARCHY_NODE_ID = 42
PERSONA_ID = 7
KNOWLEDGE_FILTER_SCHEMA_FIELDS = {
    DOCUMENT_ID_FIELD_NAME,
    ANCESTOR_HIERARCHY_NODE_IDS_FIELD_NAME,
    DOCUMENT_SETS_FIELD_NAME,
    PERSONAS_FIELD_NAME,
}


def _get_search_filters(
    source_types: list[DocumentSource],
    attached_document_ids: list[str] | None,
    hierarchy_node_ids: list[int] | None,
    persona_id_filter: int | None = None,
    document_sets: list[str] | None = None,
) -> list[dict[str, Any]]:
    return DocumentQuery._get_search_filters(
        tenant_state=TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False),
        include_hidden=False,
        access_control_list=["user_email:test@example.com"],
        source_types=source_types,
        tags=[],
        document_sets=document_sets or [],
        project_id_filter=None,
        persona_id_filter=persona_id_filter,
        time_cutoff=None,
        min_chunk_index=None,
        max_chunk_index=None,
        max_chunk_size=None,
        document_id=None,
        attached_document_ids=attached_document_ids,
        hierarchy_node_ids=hierarchy_node_ids,
    )


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

        knowledge_filter = None
        for clause in filter_clauses:
            if "bool" in clause and "should" in clause["bool"]:
                if (
                    clause["bool"].get("minimum_should_match") == 1
                    and len(clause["bool"]["should"]) > 0
                    and (
                        (
                            clause["bool"]["should"][0].get("term", {}).keys()
                            and list(
                                clause["bool"]["should"][0].get("term", {}).keys()
                            )[0]
                            in KNOWLEDGE_FILTER_SCHEMA_FIELDS
                        )
                        or (
                            clause["bool"]["should"][0].get("terms", {}).keys()
                            and list(
                                clause["bool"]["should"][0].get("terms", {}).keys()
                            )[0]
                            in KNOWLEDGE_FILTER_SCHEMA_FIELDS
                        )
                    )
                ):
                    knowledge_filter = clause
                    break

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

        knowledge_filter = None
        for clause in filter_clauses:
            if "bool" in clause and "should" in clause["bool"]:
                if (
                    clause["bool"].get("minimum_should_match") == 1
                    and len(clause["bool"]["should"]) > 0
                    and (
                        (
                            clause["bool"]["should"][0].get("term", {}).keys()
                            and list(
                                clause["bool"]["should"][0].get("term", {}).keys()
                            )[0]
                            in KNOWLEDGE_FILTER_SCHEMA_FIELDS
                        )
                        or (
                            clause["bool"]["should"][0].get("terms", {}).keys()
                            and list(
                                clause["bool"]["should"][0].get("terms", {}).keys()
                            )[0]
                            in KNOWLEDGE_FILTER_SCHEMA_FIELDS
                        )
                    )
                ):
                    knowledge_filter = clause
                    break

        assert (
            knowledge_filter is not None
        ), "Expected persona_id_filter alone to create a knowledge scope filter"
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

        knowledge_filter = None
        for clause in filter_clauses:
            if "bool" in clause and "should" in clause["bool"]:
                if (
                    clause["bool"].get("minimum_should_match") == 1
                    and len(clause["bool"]["should"]) > 0
                    and (
                        (
                            clause["bool"]["should"][0].get("term", {}).keys()
                            and list(
                                clause["bool"]["should"][0].get("term", {}).keys()
                            )[0]
                            in KNOWLEDGE_FILTER_SCHEMA_FIELDS
                        )
                        or (
                            clause["bool"]["should"][0].get("terms", {}).keys()
                            and list(
                                clause["bool"]["should"][0].get("terms", {}).keys()
                            )[0]
                            in KNOWLEDGE_FILTER_SCHEMA_FIELDS
                        )
                    )
                ):
                    knowledge_filter = clause
                    break

        assert (
            knowledge_filter is not None
        ), "Expected knowledge filter when document_sets is provided"

        filter_str = str(knowledge_filter)
        assert (
            "engineering" in filter_str
        ), "Expected document_set 'engineering' in knowledge filter"
        assert (
            str(PERSONA_ID) in filter_str
        ), f"Expected persona_id_filter {PERSONA_ID} in knowledge filter"
