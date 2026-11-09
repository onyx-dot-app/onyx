from datetime import datetime

from onyx.chat.tool_results import tool_result_sources
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.tools.models import CustomToolCallSummary


def search_doc(document_id: str) -> SearchDoc:
    return SearchDoc(
        document_id=document_id,
        chunk_ind=0,
        semantic_identifier=f"Title {document_id}",
        link=f"https://example.com/{document_id}",
        blurb="blurb",
        source_type=DocumentSource.WEB,
        boost=1,
        hidden=False,
        metadata={},
        match_highlights=[],
        updated_at=datetime(2026, 1, 1),
    )


DOC_A = search_doc("alpha")
DOC_B = search_doc("beta")


def test_search_results_show_their_displayed_documents_and_resolve_citations() -> None:
    sources = tool_result_sources(
        SearchDocsResponse(
            search_docs=[DOC_A, DOC_B],
            displayed_docs=[DOC_B],
            citation_mapping={3: "alpha", 4: "missing"},
        )
    )
    assert sources is not None
    assert sources.documents == [DOC_A, DOC_B]
    assert sources.displayed == [DOC_B]
    assert sources.citations == {3: DOC_A}


def test_research_results_cite_documents_without_showing_them() -> None:
    sources = tool_result_sources(
        ResearchAgentCallResult(
            intermediate_report="report", citation_mapping={5: DOC_B}
        )
    )
    assert sources is not None
    assert (sources.documents, sources.citations) == ([DOC_B], {5: DOC_B})
    assert sources.displayed is None


def test_results_without_documents_have_no_sources() -> None:
    custom = CustomToolCallSummary(
        tool_name="lookup", response_type="json", tool_result={"value": 1}
    )
    assert tool_result_sources(custom) is None
    assert tool_result_sources(None) is None
