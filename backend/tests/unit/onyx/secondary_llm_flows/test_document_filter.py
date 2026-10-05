from unittest.mock import MagicMock

from onyx.configs.chat_configs import SECONDARY_LLM_FLOW_TIMEOUT_S
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import (
    ContextExpansionType,
    InferenceChunk,
    InferenceSection,
)
from onyx.llm.interfaces import LLM
from onyx.llm.models import AssistantMessage, TextContent
from onyx.llm.multi_llm import LLMTimeoutError
from onyx.secondary_llm_flows.document_filter import (
    classify_section_relevance,
    select_sections_for_expansion,
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


def _make_llm(invoke: MagicMock) -> LLM:
    llm = MagicMock(spec=LLM)
    llm.invoke = invoke
    return llm


def test_classify_section_relevance_timeout_falls_back() -> None:
    """A timed-out classification call must degrade to the safe default instead
    of propagating, so a stalled provider can't hang the worker."""
    invoke = MagicMock(side_effect=LLMTimeoutError("timed out"))
    llm = _make_llm(invoke)

    result = classify_section_relevance(
        document_title="Doc",
        section_text="body",
        user_query="q",
        llm=llm,
        # surrounding text present so the no-context post-adjustment is not applied
        section_above_text="above",
        section_below_text="below",
    )

    assert result == ContextExpansionType.MAIN_SECTION_ONLY
    # the bound that makes the call fail fast must actually be passed through
    assert (
        invoke.call_args.kwargs["context"].total_timeout_s
        == SECONDARY_LLM_FLOW_TIMEOUT_S
    )


def test_classify_section_relevance_passes_timeout_on_success() -> None:
    response = AssistantMessage(content=[TextContent(text="3")])
    invoke = MagicMock(return_value=response)
    llm = _make_llm(invoke)

    result = classify_section_relevance(
        document_title="Doc",
        section_text="body",
        user_query="q",
        llm=llm,
        section_above_text="above",
        section_below_text="below",
    )

    assert result == ContextExpansionType.FULL_DOCUMENT
    assert (
        invoke.call_args.kwargs["context"].total_timeout_s
        == SECONDARY_LLM_FLOW_TIMEOUT_S
    )


def test_select_sections_for_expansion_timeout_falls_back() -> None:
    """A timed-out selection call must degrade to returning the input sections
    (capped) instead of propagating and hanging the worker."""
    sections = [_make_section()]
    invoke = MagicMock(side_effect=LLMTimeoutError("timed out"))
    llm = _make_llm(invoke)

    selected, doc_ids = select_sections_for_expansion(
        sections=sections, user_query="q", llm=llm, max_sections=10
    )

    assert selected == sections
    assert doc_ids is None
    assert (
        invoke.call_args.kwargs["context"].total_timeout_s
        == SECONDARY_LLM_FLOW_TIMEOUT_S
    )


def test_select_sections_for_expansion_passes_timeout_on_success() -> None:
    sections = [_make_section()]
    response = AssistantMessage(content=[TextContent(text="[0]")])
    invoke = MagicMock(return_value=response)
    llm = _make_llm(invoke)

    selected, _doc_ids = select_sections_for_expansion(
        sections=sections, user_query="q", llm=llm, max_sections=10
    )

    assert selected == sections
    assert (
        invoke.call_args.kwargs["context"].total_timeout_s
        == SECONDARY_LLM_FLOW_TIMEOUT_S
    )
