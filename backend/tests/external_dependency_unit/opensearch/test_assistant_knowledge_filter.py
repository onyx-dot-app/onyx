"""Tests for OpenSearch assistant knowledge filter construction.

These tests verify that when an assistant (persona) has user files attached,
the search filter includes those user file IDs in the assistant knowledge filter
with OR logic (not AND), ensuring user files are discoverable alongside other
knowledge types like attached documents and hierarchy nodes.

This prevents a regression where user_file_ids were added as a separate AND
filter, making it impossible to find user files when the assistant also had
attached documents or hierarchy nodes (since no document could match both).
"""

from typing import Any
from uuid import UUID

from onyx.configs.constants import DocumentSource
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.schema import DOCUMENT_ID_FIELD_NAME
from onyx.document_index.opensearch.search import DocumentQuery
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

USER_FILE_ID = UUID("6ad84e45-4450-406c-9d36-fcb5e74aca6b")
ATTACHED_DOCUMENT_ID = "https://docs.google.com/document/d/test-doc-id"
HIERARCHY_NODE_ID = 42


def _get_search_filters(
    source_types: list[DocumentSource],
    user_file_ids: list[UUID],
    attached_document_ids: list[str] | None,
    hierarchy_node_ids: list[int] | None,
) -> list[dict[str, Any]]:
    return DocumentQuery._get_search_filters(
        tenant_state=TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False),
        include_hidden=False,
        access_control_list=["user_email:test@example.com"],
        source_types=source_types,
        tags=[],
        document_sets=[],
        project_id=None,
        persona_id=None,
        time_cutoff=None,
        min_chunk_index=None,
        max_chunk_index=None,
        max_chunk_size=None,
        document_id=None,
        user_file_ids=user_file_ids,
        attached_document_ids=attached_document_ids,
        hierarchy_node_ids=hierarchy_node_ids,
    )


class TestAssistantKnowledgeFilter:
    """Tests for assistant knowledge filter construction in OpenSearch queries."""

    def test_user_file_ids_included_in_assistant_knowledge_filter(self) -> None:
        """
        Tests that user_file_ids are included in the assistant knowledge filter
        with OR logic when the assistant has both user files and attached documents.

        This prevents the regression where user files were ANDed with other
        knowledge types, making them unfindable.
        """

        # Under test: Call the filter construction method directly
        filter_clauses = _get_search_filters(
            source_types=[DocumentSource.FILE, DocumentSource.USER_FILE],
            user_file_ids=[USER_FILE_ID],
            attached_document_ids=[ATTACHED_DOCUMENT_ID],
            hierarchy_node_ids=[HIERARCHY_NODE_ID],
        )

        # Postcondition: Find the assistant knowledge filter (bool with should clauses)
        knowledge_filter = None
        for clause in filter_clauses:
            if "bool" in clause and "should" in clause["bool"]:
                # Check if this is the knowledge filter (has minimum_should_match=1)
                if clause["bool"].get("minimum_should_match") == 1:
                    knowledge_filter = clause
                    break

        assert (
            knowledge_filter is not None
        ), "Expected to find an assistant knowledge filter with 'minimum_should_match: 1'"

        # The knowledge filter should have 3 should clauses (user files, attached docs, hierarchy nodes)
        should_clauses = knowledge_filter["bool"]["should"]
        assert len(should_clauses) == 3, (
            f"Expected 3 should clauses (user_file, attached_doc, hierarchy_node), "
            f"got {len(should_clauses)}"
        )

        # Verify user_file_id is in one of the should clauses
        user_file_filter_found = False
        for should_clause in should_clauses:
            # The user file filter uses a nested bool with should for each file ID
            if "bool" in should_clause and "should" in should_clause["bool"]:
                for term_clause in should_clause["bool"]["should"]:
                    if "term" in term_clause:
                        term_value = term_clause["term"].get(DOCUMENT_ID_FIELD_NAME, {})
                        if term_value.get("value") == str(USER_FILE_ID):
                            user_file_filter_found = True
                            break

        assert user_file_filter_found, (
            f"Expected user_file_id {USER_FILE_ID} to be in the assistant knowledge "
            f"filter's should clauses. Filter structure: {knowledge_filter}"
        )

    def test_user_file_ids_only_creates_knowledge_filter(self) -> None:
        """
        Tests that when only user_file_ids are provided (no attached_documents or
        hierarchy_nodes), the assistant knowledge filter is still created with the
        user file IDs.
        """
        # Precondition

        filter_clauses = _get_search_filters(
            source_types=[DocumentSource.USER_FILE],
            user_file_ids=[USER_FILE_ID],
            attached_document_ids=None,
            hierarchy_node_ids=None,
        )

        # Postcondition: Find filter that contains our user file ID
        user_file_filter_found = False
        for clause in filter_clauses:
            clause_str = str(clause)
            if str(USER_FILE_ID) in clause_str:
                user_file_filter_found = True
                break

        assert user_file_filter_found, (
            f"Expected user_file_id {USER_FILE_ID} to be in the filter clauses. "
            f"Got: {filter_clauses}"
        )

    def test_no_separate_user_file_filter_when_assistant_has_knowledge(self) -> None:
        """
        Tests that user_file_ids are NOT added as a separate AND filter when the
        assistant has other knowledge attached (attached_documents or hierarchy_nodes).
        """

        filter_clauses = _get_search_filters(
            source_types=[DocumentSource.FILE, DocumentSource.USER_FILE],
            user_file_ids=[USER_FILE_ID],
            attached_document_ids=[ATTACHED_DOCUMENT_ID],
            hierarchy_node_ids=None,
        )

        # Postcondition: Count how many times user_file_id appears in filter clauses
        # It should appear exactly once (in the knowledge filter), not twice
        user_file_id_str = str(USER_FILE_ID)
        occurrences = 0
        for clause in filter_clauses:
            if user_file_id_str in str(clause):
                occurrences += 1

        assert occurrences == 1, (
            f"Expected user_file_id to appear exactly once in filter clauses "
            f"(inside the assistant knowledge filter), but found {occurrences} "
            f"occurrences. This suggests user_file_ids is being added as both a "
            f"separate AND filter and inside the knowledge filter. "
            f"Filter clauses: {filter_clauses}"
        )

    def test_multiple_user_files_all_included_in_filter(self) -> None:
        """
        Tests that when multiple user files are attached to an assistant,
        all of them are included in the filter.
        """
        # Precondition
        user_file_ids = [
            UUID("6ad84e45-4450-406c-9d36-fcb5e74aca6b"),
            UUID("7be95f56-5561-517d-ae47-acd6f85bdb7c"),
            UUID("8cf06a67-6672-628e-bf58-ade7a96cec8d"),
        ]

        filter_clauses = _get_search_filters(
            source_types=[DocumentSource.USER_FILE],
            user_file_ids=user_file_ids,
            attached_document_ids=[ATTACHED_DOCUMENT_ID],
            hierarchy_node_ids=None,
        )

        # Postcondition: All user file IDs should be in the filter
        filter_str = str(filter_clauses)
        for user_file_id in user_file_ids:
            assert (
                str(user_file_id) in filter_str
            ), f"Expected user_file_id {user_file_id} to be in the filter clauses"
