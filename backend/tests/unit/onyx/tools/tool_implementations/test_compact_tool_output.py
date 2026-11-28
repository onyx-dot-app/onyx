import json
from unittest.mock import MagicMock

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk, InferenceSection
from onyx.llm.interfaces import LLM
from onyx.llm.models import AssistantMessage, TextContent
from onyx.secondary_llm_flows.document_filter import select_sections_for_expansion
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    _sections_to_search_results,
)
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)
from onyx.tools.tool_implementations.web_search.utils import TRUNCATED_CONTENT_SUFFIX


def _make_section(index: int = 1) -> InferenceSection:
    chunk: InferenceChunk = InferenceChunk(
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
    sections: list[InferenceSection] = [_make_section(1), _make_section(2)]
    out: str
    citation_mapping: dict[int, str]
    out, citation_mapping = convert_inference_sections_to_llm_string(sections, note="n")

    assert out == json.dumps(json.loads(out), separators=(",", ":"), ensure_ascii=False)
    assert json.loads(out)["results"]
    assert citation_mapping


def test_open_url_result_json_is_compact() -> None:
    sections: list[InferenceSection] = [_make_section(1), _make_section(2)]
    out: str
    citation_mapping: dict[int, str]
    results, citation_mapping = _sections_to_search_results(sections, {}, 1)
    out = results.model_dump_json()

    assert out == json.dumps(json.loads(out), separators=(",", ":"), ensure_ascii=False)
    assert json.loads(out)["results"]
    assert citation_mapping


def test_document_filter_sections_are_compact() -> None:
    invoke: MagicMock = MagicMock(
        return_value=AssistantMessage(content=[TextContent(text="[0]")])
    )
    llm: MagicMock = MagicMock(spec=LLM)
    llm.invoke = invoke

    sections: list[InferenceSection] = [_make_section()]
    select_sections_for_expansion(
        sections=sections,
        user_query="q",
        llm=llm,
        max_sections=10,
    )

    prompt_content: str = invoke.call_args.args[0].messages[0].content
    marker: str = '"section_id"'
    idx: int = prompt_content.find(marker)
    assert idx != -1
    embedded: str = prompt_content[idx : idx + 100]
    assert "\n" not in embedded
    assert '": ' not in embedded


def test_open_url_pages_stop_at_the_call_limit_with_a_marker() -> None:
    texts = [str(index) * 40_000 for index in range(1, 4)]
    sections = [
        _make_section(index).model_copy(update={"combined_content": text})
        for index, text in enumerate(texts, start=1)
    ]

    results, _ = _sections_to_search_results(
        sections, {}, 1, max_document_chars=100_000
    )

    pages = results.results
    assert [page.content for page in pages[:2]] == texts[:2]
    last = pages[2].content
    assert last.endswith(TRUNCATED_CONTENT_SUFFIX)
    assert texts[2].startswith(last.removesuffix(TRUNCATED_CONTENT_SUFFIX))
    assert sum(len(page.content) for page in pages) < 100_000 + len(
        TRUNCATED_CONTENT_SUFFIX
    )
