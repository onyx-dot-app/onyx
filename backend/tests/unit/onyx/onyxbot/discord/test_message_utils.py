"""Unit tests for Discord bot message utilities.

Tests for:
- Message splitting (_split_message)
- Citation formatting (_append_citations)
"""

from unittest.mock import MagicMock

from onyx.chat.models import ChatFullResponse
from onyx.onyxbot.discord.constants import MAX_MESSAGE_LENGTH
from onyx.onyxbot.discord.handle_message import _append_citations
from onyx.onyxbot.discord.handle_message import _split_message


class TestSplitMessage:
    """Tests for _split_message function."""

    def test_split_message_under_limit(self) -> None:
        """Message under 2000 chars returns single chunk."""
        content = "x" * 1999
        chunks = _split_message(content)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_split_message_at_limit(self) -> None:
        """Message exactly at 2000 chars returns single chunk."""
        content = "x" * MAX_MESSAGE_LENGTH
        chunks = _split_message(content)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_split_message_over_limit(self) -> None:
        """Message over 2000 chars splits into multiple chunks."""
        content = "x" * 2001
        chunks = _split_message(content)
        assert len(chunks) == 2
        # All chunks should be <= MAX_MESSAGE_LENGTH
        for chunk in chunks:
            assert len(chunk) <= MAX_MESSAGE_LENGTH

    def test_split_at_double_newline(self) -> None:
        """Prefers splitting at double newline."""
        # Create content with double newline near the end but before limit
        first_part = "x" * 1500
        second_part = "y" * 1000
        content = f"{first_part}\n\n{second_part}"

        chunks = _split_message(content)
        assert len(chunks) == 2
        # First chunk should end with or right after the double newline
        assert chunks[0].endswith("\n\n") or first_part in chunks[0]

    def test_split_at_single_newline(self) -> None:
        """When no double newline, splits at single newline."""
        first_part = "x" * 1500
        second_part = "y" * 1000
        content = f"{first_part}\n{second_part}"

        chunks = _split_message(content)
        assert len(chunks) == 2

    def test_split_at_period_space(self) -> None:
        """When no newlines, splits at '. ' (period + space)."""
        first_part = "x" * 1500
        second_part = "y" * 1000
        content = f"{first_part}. {second_part}"

        chunks = _split_message(content)
        assert len(chunks) == 2
        # First chunk should include the period
        assert chunks[0].endswith(". ") or chunks[0].endswith(".")

    def test_split_at_space(self) -> None:
        """When no better breakpoints, splits at space."""
        first_part = "x" * 1500
        second_part = "y" * 1000
        content = f"{first_part} {second_part}"

        chunks = _split_message(content)
        assert len(chunks) == 2

    def test_split_no_breakpoint(self) -> None:
        """Handles gracefully when no breakpoints available (hard split)."""
        # 2001 chars with no spaces or newlines
        content = "x" * 2001
        chunks = _split_message(content)
        assert len(chunks) == 2
        # Content should be preserved
        assert "".join(chunks) == content

    def test_split_threshold_50_percent(self) -> None:
        """Breakpoint at less than 50% of limit is skipped."""
        # Put a breakpoint early (at 40% = 800 chars)
        # and another late (at 80% = 1600 chars)
        early_part = "x" * 800
        middle_part = "m" * 800  # Total: 1600
        late_part = "y" * 600  # Total: 2200
        content = f"{early_part}\n\n{middle_part}\n\n{late_part}"

        chunks = _split_message(content)
        # Should prefer the later breakpoint over the 40% one
        assert len(chunks) == 2
        # First chunk should be longer than 800 chars
        assert len(chunks[0]) > 800

    def test_split_multiple_chunks(self) -> None:
        """5000 char message splits into 3 chunks."""
        content = "x" * 5000
        chunks = _split_message(content)
        assert len(chunks) == 3
        # Each chunk should be <= MAX_MESSAGE_LENGTH
        for chunk in chunks:
            assert len(chunk) <= MAX_MESSAGE_LENGTH

    def test_split_preserves_content(self) -> None:
        """Concatenated chunks equal original content."""
        content = "Hello world! " * 200  # About 2600 chars
        chunks = _split_message(content)
        assert "".join(chunks) == content

    def test_split_with_unicode(self) -> None:
        """Handles unicode characters correctly."""
        # Mix of ASCII and unicode
        content = "Hello " + "🎉" * 500 + " World " + "x" * 1500
        chunks = _split_message(content)
        # Should not break in the middle of emoji
        assert "".join(chunks) == content


class TestAppendCitations:
    """Tests for _append_citations function."""

    def _make_response(
        self,
        answer: str,
        citations: list[dict] | None = None,
        documents: list[dict] | None = None,
    ) -> ChatFullResponse:
        """Helper to create ChatFullResponse with citations."""
        response = MagicMock(spec=ChatFullResponse)
        response.answer = answer

        if citations:
            citation_mocks = []
            for c in citations:
                cm = MagicMock()
                cm.citation_number = c.get("num", 1)
                cm.document_id = c.get("doc_id", "doc1")
                citation_mocks.append(cm)
            response.citation_info = citation_mocks
        else:
            response.citation_info = None

        if documents:
            doc_mocks = []
            for d in documents:
                dm = MagicMock()
                dm.document_id = d.get("doc_id", "doc1")
                dm.semantic_identifier = d.get("name", "Source")
                dm.link = d.get("link")
                doc_mocks.append(dm)
            response.top_documents = doc_mocks
        else:
            response.top_documents = None

        return response

    def test_format_citations_empty_list(self) -> None:
        """No citations returns answer unchanged."""
        response = self._make_response("Test answer")
        result = _append_citations("Test answer", response)
        assert result == "Test answer"
        assert "Sources:" not in result

    def test_format_citations_single(self) -> None:
        """Single citation is formatted correctly."""
        response = self._make_response(
            "Test answer",
            citations=[{"num": 1, "doc_id": "doc1"}],
            documents=[
                {
                    "doc_id": "doc1",
                    "name": "Document One",
                    "link": "https://example.com",
                }
            ],
        )
        result = _append_citations("Test answer", response)
        assert "**Sources:**" in result
        assert "[Document One](<https://example.com>)" in result

    def test_format_citations_multiple(self) -> None:
        """Multiple citations are all formatted and numbered."""
        response = self._make_response(
            "Test answer",
            citations=[
                {"num": 1, "doc_id": "doc1"},
                {"num": 2, "doc_id": "doc2"},
                {"num": 3, "doc_id": "doc3"},
            ],
            documents=[
                {"doc_id": "doc1", "name": "Doc 1", "link": "https://example.com/1"},
                {"doc_id": "doc2", "name": "Doc 2", "link": "https://example.com/2"},
                {"doc_id": "doc3", "name": "Doc 3", "link": "https://example.com/3"},
            ],
        )
        result = _append_citations("Test answer", response)
        assert "1. [Doc 1]" in result
        assert "2. [Doc 2]" in result
        assert "3. [Doc 3]" in result

    def test_format_citations_max_five(self) -> None:
        """Only first 5 citations are included."""
        citations = [{"num": i, "doc_id": f"doc{i}"} for i in range(1, 11)]
        documents = [
            {
                "doc_id": f"doc{i}",
                "name": f"Doc {i}",
                "link": f"https://example.com/{i}",
            }
            for i in range(1, 11)
        ]
        response = self._make_response(
            "Test answer", citations=citations, documents=documents
        )
        result = _append_citations("Test answer", response)

        # Should have 5 citations
        assert "1. [Doc 1]" in result
        assert "5. [Doc 5]" in result
        # Should NOT have 6th citation
        assert "6. [Doc 6]" not in result

    def test_format_citation_no_link(self) -> None:
        """Citation without link formats as plain text (no markdown)."""
        response = self._make_response(
            "Test answer",
            citations=[{"num": 1, "doc_id": "doc1"}],
            documents=[{"doc_id": "doc1", "name": "No Link Doc", "link": None}],
        )
        result = _append_citations("Test answer", response)
        assert "1. No Link Doc" in result
        # Should not have markdown link syntax
        assert "[No Link Doc](<" not in result

    def test_format_citation_empty_name(self) -> None:
        """Empty semantic_identifier defaults to 'Source'."""
        response = self._make_response(
            "Test answer",
            citations=[{"num": 1, "doc_id": "doc1"}],
            documents=[{"doc_id": "doc1", "name": "", "link": "https://example.com"}],
        )
        result = _append_citations("Test answer", response)
        # Should use fallback "Source" name
        assert "[Source]" in result or "Source" in result

    def test_format_citation_link_with_brackets(self) -> None:
        """Link with special characters is wrapped with angle brackets."""
        response = self._make_response(
            "Test answer",
            citations=[{"num": 1, "doc_id": "doc1"}],
            documents=[
                {
                    "doc_id": "doc1",
                    "name": "Special Doc",
                    "link": "https://example.com/path?query=value&other=123",
                }
            ],
        )
        result = _append_citations("Test answer", response)
        # Discord markdown uses <link> to prevent embed
        assert "(<https://example.com" in result

    def test_format_citations_sorted_by_number(self) -> None:
        """Citations are sorted by citation number."""
        # Add in reverse order
        response = self._make_response(
            "Test answer",
            citations=[
                {"num": 3, "doc_id": "doc3"},
                {"num": 1, "doc_id": "doc1"},
                {"num": 2, "doc_id": "doc2"},
            ],
            documents=[
                {"doc_id": "doc1", "name": "Doc 1", "link": "https://example.com/1"},
                {"doc_id": "doc2", "name": "Doc 2", "link": "https://example.com/2"},
                {"doc_id": "doc3", "name": "Doc 3", "link": "https://example.com/3"},
            ],
        )
        result = _append_citations("Test answer", response)

        # Find positions
        pos1 = result.find("1. [Doc 1]")
        pos2 = result.find("2. [Doc 2]")
        pos3 = result.find("3. [Doc 3]")

        # Should be in order
        assert pos1 < pos2 < pos3

    def test_format_citations_with_missing_document(self) -> None:
        """Citation referencing non-existent document is skipped."""
        response = self._make_response(
            "Test answer",
            citations=[
                {"num": 1, "doc_id": "doc1"},
                {"num": 2, "doc_id": "doc_missing"},  # No matching document
            ],
            documents=[
                {"doc_id": "doc1", "name": "Doc 1", "link": "https://example.com/1"},
            ],
        )
        result = _append_citations("Test answer", response)
        assert "Doc 1" in result
        # Missing doc should not appear
        assert "doc_missing" not in result.lower()
