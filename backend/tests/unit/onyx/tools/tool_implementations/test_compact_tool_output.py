import json
from unittest.mock import MagicMock

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk, InferenceSection
from onyx.llm.interfaces import LLM
from onyx.llm.models import AssistantMessage, TextContent
from onyx.secondary_llm_flows.document_filter import select_sections_for_expansion
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    _convert_sections_to_llm_string_with_citations,
)
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)


def _make_section(index: int = 1) -> InferenceSection:
    chunk = InferenceChunk(
        document_id=f"doc-{index}",
        chunk_id=0,
        content=f"section {index}",
        source_type=DocumentSource.MOCK_CONNECTOR,
        semantic_identifier=f"sem-doc-{index}",
        title=f"doc-{index}",
        boost=1,
        score=0.5,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
        image_file_id=None,
        source_links={},
        section_continuation=False,
        blurb="blurb",
        file_id=None,
    )
    return InferenceSection(
        center_chunk=chunk, chunks=[chunk], combined_content=chunk.content
    )


def test_search_result_json_is_compact() -> None:
    out, citation_mapping = convert_inference_sections_to_llm_string(
        [_make_section(1), _make_section(2)], note="n"
    )

    assert out == json.dumps(json.loads(out), separators=(",", ":"), ensure_ascii=False)
    assert json.loads(out)["results"]
    assert citation_mapping


def test_open_url_result_json_is_compact() -> None:
    out, citation_mapping = _convert_sections_to_llm_string_with_citations(
        [_make_section(1), _make_section(2)], {}, 1
    )

    assert out == json.dumps(json.loads(out), separators=(",", ":"), ensure_ascii=False)
    assert json.loads(out)["results"]
    assert citation_mapping


def test_document_filter_sections_are_compact() -> None:
    invoke = MagicMock(return_value=AssistantMessage(content=[TextContent(text="[0]")]))
    llm = MagicMock(spec=LLM)
    llm.invoke = invoke

    select_sections_for_expansion(
        sections=[_make_section()],
        user_query="q",
        llm=llm,
        max_sections=10,
    )

    prompt_content = invoke.call_args.args[0].messages[0].content
    marker = '"section_id"'
    idx = prompt_content.find(marker)
    assert idx != -1
    embedded = prompt_content[idx : idx + 100]
    assert "\n" not in embedded
    assert '": ' not in embedded
