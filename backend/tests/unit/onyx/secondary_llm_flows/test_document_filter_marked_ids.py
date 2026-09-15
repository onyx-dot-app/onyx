from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk, InferenceSection
from onyx.llm.interfaces import LLM
from onyx.secondary_llm_flows.document_filter import select_sections_for_expansion


@contextmanager
def _noop_span(*_args: object, **_kwargs: object) -> Iterator[MagicMock]:
    yield MagicMock()


def _make_section(index: int) -> InferenceSection:
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
        center_chunk=chunk,
        chunks=[chunk],
        combined_content=chunk.content,
    )


@pytest.mark.parametrize(
    ("response_text", "expected_indices", "expected_full_document_ids"),
    [
        ("0!, 2!, 1!, 4", [0, 2, 1, 4], ["doc-0", "doc-2", "doc-1"]),
        ("[0!, 2!, 1!, 4]", [0, 2, 1, 4], ["doc-0", "doc-2", "doc-1"]),
        ("0, 2, 1, 4", [0, 2, 1, 4], None),
        ("[0, 2, 1, 4]", [0, 2, 1, 4], None),
    ],
)
@patch("onyx.secondary_llm_flows.document_filter.record_llm_response")
@patch(
    "onyx.secondary_llm_flows.document_filter.llm_generation_span",
    side_effect=_noop_span,
)
def test_select_sections_parses_complete_marked_and_unmarked_lists(
    _span: MagicMock,
    _record: MagicMock,
    response_text: str,
    expected_indices: list[int],
    expected_full_document_ids: list[str] | None,
) -> None:
    sections = [_make_section(index) for index in range(5)]
    response = MagicMock()
    response.choice.message.content = response_text
    llm = MagicMock(spec=LLM)
    llm.invoke = MagicMock(return_value=response)

    selected, full_document_ids = select_sections_for_expansion(
        sections=sections,
        user_query="query",
        llm=llm,
        max_sections=5,
    )

    assert [sections.index(section) for section in selected] == expected_indices
    assert full_document_ids == expected_full_document_ids
