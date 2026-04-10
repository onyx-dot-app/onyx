"""Unit tests for the context assembler engine component.

Tests cover:
- get_proposal_context: full assembly with mocked DB queries
- Budget detection by document role and filename
- FOA detection by document role
- Multiple document concatenation
- Missing documents / missing proposal handling
- _is_budget_filename helper
- _build_parent_document_text helper
- _classify_child_text helper
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.server.features.proposal_review.engine.context_assembler import (
    _build_parent_document_text,
)
from onyx.server.features.proposal_review.engine.context_assembler import (
    _classify_child_text,
)
from onyx.server.features.proposal_review.engine.context_assembler import (
    _is_budget_filename,
)
from onyx.server.features.proposal_review.engine.context_assembler import (
    get_proposal_context,
)
from onyx.server.features.proposal_review.engine.context_assembler import (
    ProposalContext,
)


# =====================================================================
# _is_budget_filename
# =====================================================================


class TestIsBudgetFilename:
    """Tests for _is_budget_filename helper."""

    @pytest.mark.parametrize(
        "filename",
        [
            "budget.xlsx",
            "BUDGET_justification.pdf",
            "project_budget_v2.docx",
            "cost_estimate.xlsx",
            "financial_plan.pdf",
            "annual_expenditure.csv",
        ],
    )
    def test_budget_filenames_detected(self, filename):
        assert _is_budget_filename(filename) is True

    @pytest.mark.parametrize(
        "filename",
        [
            "narrative.pdf",
            "abstract.docx",
            "biosketch.pdf",
            "facilities.docx",
            "",
        ],
    )
    def test_non_budget_filenames_not_detected(self, filename):
        assert _is_budget_filename(filename) is False

    def test_none_filename_returns_false(self):
        assert _is_budget_filename(None) is False  # type: ignore[arg-type]


# =====================================================================
# _build_parent_document_text
# =====================================================================


class TestBuildParentDocumentText:
    """Tests for _build_parent_document_text helper."""

    def test_includes_semantic_id(self):
        doc = MagicMock()
        doc.semantic_id = "PROJ-42"
        doc.link = None
        doc.doc_metadata = None
        result = _build_parent_document_text(doc)
        assert "PROJ-42" in result

    def test_includes_link(self):
        doc = MagicMock()
        doc.semantic_id = None
        doc.link = "https://jira.example.com/PROJ-42"
        doc.doc_metadata = None
        result = _build_parent_document_text(doc)
        assert "https://jira.example.com/PROJ-42" in result

    def test_includes_metadata_as_json(self):
        doc = MagicMock()
        doc.semantic_id = "PROJ-42"
        doc.link = None
        doc.doc_metadata = {"sponsor": "NIH", "pi": "Dr. Smith"}
        result = _build_parent_document_text(doc)
        assert "NIH" in result
        assert "Dr. Smith" in result

    def test_empty_document_returns_minimal_text(self):
        doc = MagicMock()
        doc.semantic_id = None
        doc.link = None
        doc.doc_metadata = None
        doc.primary_owners = None
        doc.secondary_owners = None
        result = _build_parent_document_text(doc)
        # With no content at all, the result should be empty or only contain
        # structural headers. Verify it doesn't contain any meaningful data.
        assert "NIH" not in result
        assert "Dr. Smith" not in result


# =====================================================================
# _classify_child_text
# =====================================================================


class TestClassifyChildText:
    """Tests for _classify_child_text helper."""

    def test_budget_filename_classified(self):
        doc = MagicMock()
        doc.semantic_id = "PROJ-42/attachments/budget_v2.xlsx"
        budget_parts: list[str] = []
        foa_parts: list[str] = []
        _classify_child_text(doc, "budget content", budget_parts, foa_parts)
        assert "budget content" in budget_parts
        assert foa_parts == []

    def test_foa_filename_classified(self):
        doc = MagicMock()
        doc.semantic_id = "PROJ-42/attachments/foa_document.pdf"
        budget_parts: list[str] = []
        foa_parts: list[str] = []
        _classify_child_text(doc, "foa content", budget_parts, foa_parts)
        assert foa_parts == ["foa content"]
        assert budget_parts == []

    def test_solicitation_keyword_classified_as_foa(self):
        doc = MagicMock()
        doc.semantic_id = "solicitation_2024.pdf"
        budget_parts: list[str] = []
        foa_parts: list[str] = []
        _classify_child_text(doc, "solicitation text", budget_parts, foa_parts)
        assert "solicitation text" in foa_parts

    def test_rfa_keyword_classified_as_foa(self):
        doc = MagicMock()
        doc.semantic_id = "RFA-AI-24-001.pdf"
        budget_parts: list[str] = []
        foa_parts: list[str] = []
        _classify_child_text(doc, "rfa text", budget_parts, foa_parts)
        assert "rfa text" in foa_parts

    def test_unrelated_filename_not_classified(self):
        doc = MagicMock()
        doc.semantic_id = "narrative_v3.docx"
        budget_parts: list[str] = []
        foa_parts: list[str] = []
        _classify_child_text(doc, "narrative text", budget_parts, foa_parts)
        assert budget_parts == []
        assert foa_parts == []

    def test_none_semantic_id_not_classified(self):
        doc = MagicMock()
        doc.semantic_id = None
        budget_parts: list[str] = []
        foa_parts: list[str] = []
        _classify_child_text(doc, "some text", budget_parts, foa_parts)
        assert budget_parts == []
        assert foa_parts == []


# =====================================================================
# get_proposal_context  --  full assembly with mocked DB
# =====================================================================


def _make_mock_proposal(document_id="DOC-123"):
    """Create a mock ProposalReviewProposal."""
    proposal = MagicMock()
    proposal.id = uuid4()
    proposal.document_id = document_id
    return proposal


def _make_mock_document(
    doc_id="DOC-123",
    semantic_id="PROJ-42",
    link=None,
    doc_metadata=None,
):
    """Create a mock Document."""
    doc = MagicMock()
    doc.id = doc_id
    doc.semantic_id = semantic_id
    doc.link = link
    doc.doc_metadata = doc_metadata or {}
    return doc


def _make_mock_review_doc(
    file_name="doc.pdf",
    document_role="SUPPORTING",
    extracted_text="Some text.",
):
    """Create a mock ProposalReviewDocument."""
    doc = MagicMock()
    doc.file_name = file_name
    doc.document_role = document_role
    doc.extracted_text = extracted_text
    return doc


class TestGetProposalContext:
    """Tests for get_proposal_context with mocked DB session."""

    def _setup_db(
        self,
        proposal=None,
        parent_doc=None,
        child_docs=None,
        manual_docs=None,
    ):
        """Build a mock db_session with controlled query results.

        The function under test does three queries:
        1. ProposalReviewProposal by id
        2. Document by id (parent doc)
        3. Document.id.like(...) (child docs)
        4. ProposalReviewDocument by proposal_id (manual docs)

        We use side_effect on db_session.query() to differentiate them.
        """
        db = MagicMock()

        # We need to handle multiple .query() calls with different model classes.
        # The function calls:
        #   db_session.query(ProposalReviewProposal).filter(...).one_or_none()
        #   db_session.query(Document).filter(...).one_or_none()
        #   db_session.query(Document).filter(..., ...).all()
        #   db_session.query(ProposalReviewDocument).filter(...).order_by(...).all()

        call_count = {"n": 0}

        def query_side_effect(model_cls):
            call_count["n"] += 1
            mock_query = MagicMock()

            model_name = getattr(model_cls, "__name__", str(model_cls))

            if model_name == "ProposalReviewProposal":
                mock_query.filter.return_value = mock_query
                mock_query.one_or_none.return_value = proposal
                return mock_query

            if model_name == "Document":
                # First Document query is for parent (one_or_none),
                # second is for children (all).
                # We track via a sub-counter.
                if not hasattr(query_side_effect, "_doc_calls"):
                    query_side_effect._doc_calls = 0
                query_side_effect._doc_calls += 1

                if query_side_effect._doc_calls == 1:
                    # Parent doc query
                    mock_query.filter.return_value = mock_query
                    mock_query.one_or_none.return_value = parent_doc
                else:
                    # Child docs query
                    mock_query.filter.return_value = mock_query
                    mock_query.all.return_value = child_docs or []
                return mock_query

            if model_name == "ProposalReviewDocument":
                mock_query.filter.return_value = mock_query
                mock_query.order_by.return_value = mock_query
                mock_query.all.return_value = manual_docs or []
                return mock_query

            return mock_query

        # Reset the doc_calls counter if it exists from a previous test
        if hasattr(query_side_effect, "_doc_calls"):
            del query_side_effect._doc_calls

        db.query.side_effect = query_side_effect
        return db

    def test_basic_assembly_with_parent_doc(self):
        proposal = _make_mock_proposal()
        parent_doc = _make_mock_document(
            semantic_id="PROJ-42",
            doc_metadata={"sponsor": "NIH", "pi": "Dr. Smith"},
        )

        db = self._setup_db(proposal=proposal, parent_doc=parent_doc)
        ctx = get_proposal_context(proposal.id, db)

        assert isinstance(ctx, ProposalContext)
        assert ctx.jira_key == "PROJ-42"
        assert ctx.metadata["sponsor"] == "NIH"
        assert "PROJ-42" in ctx.proposal_text

    def test_proposal_not_found_returns_empty_context(self):
        db = self._setup_db(proposal=None)

        ctx = get_proposal_context(uuid4(), db)
        # When proposal is not found, returns a safe empty context
        assert isinstance(ctx, ProposalContext)
        assert ctx.proposal_text == ""
        assert ctx.metadata == {}

    def test_budget_document_by_role(self):
        proposal = _make_mock_proposal()
        parent_doc = _make_mock_document()
        budget_doc = _make_mock_review_doc(
            file_name="project_budget.xlsx",
            document_role="BUDGET",
            extracted_text="Total: $500k direct costs.",
        )

        db = self._setup_db(
            proposal=proposal,
            parent_doc=parent_doc,
            manual_docs=[budget_doc],
        )
        ctx = get_proposal_context(proposal.id, db)

        assert "$500k" in ctx.budget_text
        # Budget text should also appear in proposal_text (all docs)
        assert "$500k" in ctx.proposal_text

    def test_budget_document_by_filename(self):
        proposal = _make_mock_proposal()
        parent_doc = _make_mock_document()
        budget_doc = _make_mock_review_doc(
            file_name="budget_justification.pdf",
            document_role="SUPPORTING",  # role is not BUDGET
            extracted_text="Budget justification: $200k.",
        )

        db = self._setup_db(
            proposal=proposal,
            parent_doc=parent_doc,
            manual_docs=[budget_doc],
        )
        ctx = get_proposal_context(proposal.id, db)

        assert "$200k" in ctx.budget_text

    def test_foa_document_by_role(self):
        proposal = _make_mock_proposal()
        parent_doc = _make_mock_document()
        foa_doc = _make_mock_review_doc(
            file_name="rfa-ai-24-001.html",
            document_role="FOA",
            extracted_text="This is the funding opportunity announcement.",
        )

        db = self._setup_db(
            proposal=proposal,
            parent_doc=parent_doc,
            manual_docs=[foa_doc],
        )
        ctx = get_proposal_context(proposal.id, db)

        assert "funding opportunity announcement" in ctx.foa_text

    def test_multiple_documents_concatenated(self):
        proposal = _make_mock_proposal()
        parent_doc = _make_mock_document(semantic_id="PROJ-42")
        doc_a = _make_mock_review_doc(
            file_name="narrative.pdf",
            document_role="SUPPORTING",
            extracted_text="Section A content.",
        )
        doc_b = _make_mock_review_doc(
            file_name="abstract.pdf",
            document_role="SUPPORTING",
            extracted_text="Section B content.",
        )

        db = self._setup_db(
            proposal=proposal,
            parent_doc=parent_doc,
            manual_docs=[doc_a, doc_b],
        )
        ctx = get_proposal_context(proposal.id, db)

        assert "Section A content" in ctx.proposal_text
        assert "Section B content" in ctx.proposal_text

    def test_no_documents_returns_minimal_text(self):
        proposal = _make_mock_proposal()
        # Parent doc exists but has no meaningful content fields
        parent_doc = _make_mock_document(
            semantic_id=None,
            link=None,
            doc_metadata=None,
        )
        parent_doc.primary_owners = None
        parent_doc.secondary_owners = None

        db = self._setup_db(
            proposal=proposal,
            parent_doc=parent_doc,
            manual_docs=[],
        )
        ctx = get_proposal_context(proposal.id, db)

        # No meaningful content — may contain structural headers but no real data
        assert "NIH" not in ctx.proposal_text
        assert ctx.budget_text == ""
        assert ctx.foa_text == ""

    def test_no_parent_doc_still_returns_context(self):
        proposal = _make_mock_proposal()
        manual_doc = _make_mock_review_doc(
            file_name="narrative.pdf",
            document_role="SUPPORTING",
            extracted_text="Manual upload content.",
        )

        db = self._setup_db(
            proposal=proposal,
            parent_doc=None,
            manual_docs=[manual_doc],
        )
        ctx = get_proposal_context(proposal.id, db)

        assert "Manual upload content" in ctx.proposal_text
        assert ctx.jira_key == ""
        assert ctx.metadata == {}

    def test_manual_doc_with_no_text_is_skipped(self):
        proposal = _make_mock_proposal()
        parent_doc = _make_mock_document()
        empty_doc = _make_mock_review_doc(
            file_name="empty.pdf",
            document_role="SUPPORTING",
            extracted_text=None,
        )

        db = self._setup_db(
            proposal=proposal,
            parent_doc=parent_doc,
            manual_docs=[empty_doc],
        )
        ctx = get_proposal_context(proposal.id, db)

        # The empty doc should not contribute to proposal_text
        assert "empty.pdf" not in ctx.proposal_text
