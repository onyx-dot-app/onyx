"""Tests for the operator-forced document-set scope in OpenSearch query construction.

The forced scope (from FORCED_DOCUMENT_SET_NAMES) must be applied as a STANDALONE
top-level AND filter clause — distinct from the user/persona ``document_set`` scope,
which lives inside the OR-based knowledge filter. This is what makes the forced scope
INTERSECT with (restrict), rather than widen, any existing scope, while leaving ACL
enforcement intact.
"""

from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.schema import (
    ACCESS_CONTROL_LIST_FIELD_NAME,
    DOCUMENT_SETS_FIELD_NAME,
)
from onyx.document_index.opensearch.search import DocumentQuery
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def _get_search_filters(
    document_sets: list[str] | None = None,
    forced_document_sets: list[str] | None = None,
) -> list[dict[str, Any]]:
    return DocumentQuery._get_search_filters(
        tenant_state=TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False),
        include_hidden=False,
        access_control_list=["user_email:test@example.com"],
        source_types=[DocumentSource.FILE],
        tags=[],
        document_sets=document_sets or [],
        project_id_filter=None,
        persona_id_filter=None,
        created_at_range=None,
        updated_at_range=None,
        min_chunk_index=None,
        max_chunk_index=None,
        forced_document_sets=forced_document_sets,
    )


def _top_level_document_set_terms(
    filter_clauses: list[dict[str, Any]],
) -> list[list[str]]:
    """Values of every top-level (AND) ``terms`` clause on the document_sets field.

    The forced scope is emitted here; a user/persona document_set scope is NOT — it
    is nested inside the knowledge ``bool.should`` clause, so it never appears at the
    top level.
    """
    return [
        clause["terms"][DOCUMENT_SETS_FIELD_NAME]
        for clause in filter_clauses
        if "terms" in clause and DOCUMENT_SETS_FIELD_NAME in clause["terms"]
    ]


def _has_acl_clause(filter_clauses: list[dict[str, Any]]) -> bool:
    return ACCESS_CONTROL_LIST_FIELD_NAME in str(filter_clauses)


class TestForcedDocumentSetFilter:
    def test_forced_scope_is_top_level_and_clause(self) -> None:
        """A forced scope with no user scope produces exactly one top-level terms
        clause on document_sets (an AND restriction), NOT a knowledge OR-scope."""
        filter_clauses = _get_search_filters(forced_document_sets=["Forced"])

        top_level = _top_level_document_set_terms(filter_clauses)
        assert top_level == [["Forced"]], (
            f"Expected the forced set as a single top-level AND clause. Got: {filter_clauses}"
        )

    def test_forced_scope_intersects_user_document_set(self) -> None:
        """With both a user document_set and a forced scope, the user set stays in the
        OR knowledge scope while the forced set is its own top-level AND clause — so a
        document must belong to BOTH (intersection)."""
        filter_clauses = _get_search_filters(
            document_sets=["UserPicked"],
            forced_document_sets=["Forced"],
        )

        # Forced set: top-level AND clause.
        assert _top_level_document_set_terms(filter_clauses) == [["Forced"]], (
            f"Expected only the forced set at top level. Got: {filter_clauses}"
        )
        # User set: nested inside the knowledge bool/should scope (not top level).
        knowledge_should = [
            clause["bool"]["should"]
            for clause in filter_clauses
            if isinstance(clause.get("bool"), dict) and clause["bool"].get("should")
        ]
        assert any("UserPicked" in str(should) for should in knowledge_should), (
            f"Expected the user document_set inside the knowledge OR-scope. "
            f"Got: {filter_clauses}"
        )

    def test_forced_scope_preserves_acl(self) -> None:
        """The forced clause is added alongside — never in place of — the ACL clause."""
        filter_clauses = _get_search_filters(forced_document_sets=["Forced"])
        assert _has_acl_clause(filter_clauses), (
            f"ACL clause must still be present with a forced scope. Got: {filter_clauses}"
        )

    def test_no_forced_clause_when_unset(self) -> None:
        """When no forced scope is set, no top-level document_sets clause is emitted; a
        user document_set stays confined to the knowledge OR-scope."""
        for forced in (None, []):
            filter_clauses = _get_search_filters(
                document_sets=["UserPicked"], forced_document_sets=forced
            )
            assert _top_level_document_set_terms(filter_clauses) == [], (
                f"No top-level forced clause expected for forced={forced!r}. "
                f"Got: {filter_clauses}"
            )
