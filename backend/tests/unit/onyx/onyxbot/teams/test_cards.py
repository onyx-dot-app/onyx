"""Unit tests for Teams bot Adaptive Card builders."""

from unittest.mock import MagicMock

from onyx.onyxbot.teams.cards import build_answer_card
from onyx.onyxbot.teams.cards import build_error_card
from onyx.onyxbot.teams.cards import build_welcome_card


class TestBuildAnswerCard:
    """Tests for answer card generation."""

    def test_basic_answer(self) -> None:
        card = build_answer_card("Hello world")
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.3"
        assert len(card["body"]) == 1
        assert card["body"][0]["text"] == "Hello world"

    def test_answer_with_citations(self) -> None:
        mock_response = MagicMock()
        mock_citation = MagicMock()
        mock_citation.citation_number = 1
        mock_citation.document_id = "doc1"

        mock_doc = MagicMock()
        mock_doc.document_id = "doc1"
        mock_doc.semantic_identifier = "Design Doc"
        mock_doc.link = "https://example.com/doc1"

        mock_response.citation_info = [mock_citation]
        mock_response.top_documents = [mock_doc]

        card = build_answer_card("Answer text", mock_response)
        # Body should have: answer + "Sources:" header + citation
        assert len(card["body"]) == 3
        assert "Sources" in card["body"][1]["text"]
        assert "Design Doc" in card["body"][2]["text"]

    def test_answer_no_citations(self) -> None:
        mock_response = MagicMock()
        mock_response.citation_info = []
        mock_response.top_documents = []

        card = build_answer_card("Answer text", mock_response)
        assert len(card["body"]) == 1

    def test_answer_citation_without_link(self) -> None:
        mock_response = MagicMock()
        mock_citation = MagicMock()
        mock_citation.citation_number = 1
        mock_citation.document_id = "doc1"

        mock_doc = MagicMock()
        mock_doc.document_id = "doc1"
        mock_doc.semantic_identifier = "Internal Doc"
        mock_doc.link = None

        mock_response.citation_info = [mock_citation]
        mock_response.top_documents = [mock_doc]

        card = build_answer_card("Answer text", mock_response)
        assert "Internal Doc" in card["body"][2]["text"]
        # Should not contain markdown link since link is None
        assert "http" not in card["body"][2]["text"]


class TestBuildErrorCard:
    """Tests for error card generation."""

    def test_error_card(self) -> None:
        card = build_error_card("Something went wrong")
        assert card["type"] == "AdaptiveCard"
        assert card["body"][0]["text"] == "Something went wrong"
        assert card["body"][0]["color"] == "Attention"


class TestBuildWelcomeCard:
    """Tests for welcome card generation."""

    def test_welcome_card(self) -> None:
        card = build_welcome_card()
        assert card["type"] == "AdaptiveCard"
        assert len(card["body"]) == 2
        assert "Welcome" in card["body"][0]["text"]
        assert "register" in card["body"][1]["text"]
