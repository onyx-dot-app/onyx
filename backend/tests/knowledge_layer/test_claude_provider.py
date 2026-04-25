import json
import pytest
from unittest.mock import MagicMock, patch
from knowledge_layer.providers.base import LLMProvider, IngestResult, QueryResult, WikiPageDraft, CrossRefProposal
from knowledge_layer.providers.claude import ClaudeProvider


def test_llm_provider_is_abstract():
    with pytest.raises(TypeError):
        LLMProvider()


def test_ingest_result_structure():
    page = WikiPageDraft(slug="test-slug", title="Test", content="Hello world")
    ref = CrossRefProposal(from_slug="test-slug", to_slug="other-slug", link_type="see-also")
    result = IngestResult(wiki_pages=[page], cross_refs=[ref])
    assert result.wiki_pages[0].slug == "test-slug"
    assert result.cross_refs[0].link_type == "see-also"


def test_query_result_structure():
    result = QueryResult(answer="The answer is 42.", citations=["page-one", "page-two"])
    assert "42" in result.answer
    assert len(result.citations) == 2


def test_claude_provider_ingest_call_parses_response():
    mock_response_content = json.dumps({
        "wiki_pages": [
            {"slug": "trading-signals", "title": "Trading Signals", "content": "Content here."}
        ],
        "cross_refs": []
    })
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=mock_response_content)]

    with patch("knowledge_layer.providers.claude.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = mock_message

        provider = ClaudeProvider()
        result = provider.ingest_call(
            raw_content="Some raw document content.",
            existing_pages=[],
            topic_name="trading"
        )

    assert len(result.wiki_pages) == 1
    assert result.wiki_pages[0].slug == "trading-signals"
    assert result.cross_refs == []


def test_claude_provider_query_call_parses_response():
    mock_response_content = json.dumps({
        "answer": "Trading signals are indicators used to time trades.",
        "citations": ["trading-signals"]
    })
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=mock_response_content)]

    with patch("knowledge_layer.providers.claude.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = mock_message

        provider = ClaudeProvider()
        result = provider.query_call(
            question="What are trading signals?",
            wiki_pages=[]
        )

    assert "indicators" in result.answer
    assert "trading-signals" in result.citations
