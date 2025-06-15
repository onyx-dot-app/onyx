import pytest

from onyx.chat.prune_and_merge import _merge_sections
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.utils import inference_section_from_chunks


# This large test accounts for all of the following:
# 1. Merging of adjacent sections
# 2. Merging of non-adjacent sections
# 3. Merging of sections where there are multiple documents
# 4. Verifying the contents of merged sections
# 5. Verifying the order/score of the merged sections


def create_inference_chunk(
    document_id: str, chunk_id: int, content: str, score: float | None
) -> InferenceChunk:
    """
    Create an InferenceChunk with hardcoded values for testing purposes.
    """
    return InferenceChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        semantic_identifier=f"{document_id}_{chunk_id}",
        title="whatever",
        blurb=f"{document_id}_{chunk_id}",
        content=content,
        source_links={0: "fake_link"},
        section_continuation=False,
        source_type=DocumentSource.WEB,
        boost=0,
        recency_bias=1.0,
        score=score,
        hidden=False,
        metadata={},
        match_highlights=[],
        updated_at=None,
        image_file_id=None,
        doc_summary="",
        chunk_context="",
    )


# Document 1, top connected sections
DOC_1_FILLER_1 = create_inference_chunk("doc1", 2, "Content 2", 1.0)
DOC_1_FILLER_2 = create_inference_chunk("doc1", 3, "Content 3", 2.0)
DOC_1_TOP_CHUNK = create_inference_chunk("doc1", 4, "Content 4", None)
DOC_1_MID_CHUNK = create_inference_chunk("doc1", 5, "Content 5", 4.0)
DOC_1_FILLER_3 = create_inference_chunk("doc1", 6, "Content 6", 5.0)
DOC_1_FILLER_4 = create_inference_chunk("doc1", 7, "Content 7", 6.0)
# This chunk below has the top score for testing
DOC_1_BOTTOM_CHUNK = create_inference_chunk("doc1", 8, "Content 8", 70.0)
DOC_1_FILLER_5 = create_inference_chunk("doc1", 9, "Content 9", None)
DOC_1_FILLER_6 = create_inference_chunk("doc1", 10, "Content 10", 9.0)
# Document 1, separate section
DOC_1_FILLER_7 = create_inference_chunk("doc1", 13, "Content 13", 10.0)
DOC_1_FILLER_8 = create_inference_chunk("doc1", 14, "Content 14", 11.0)
DOC_1_DISCONNECTED = create_inference_chunk("doc1", 15, "Content 15", 12.0)
DOC_1_FILLER_9 = create_inference_chunk("doc1", 16, "Content 16", 13.0)
DOC_1_FILLER_10 = create_inference_chunk("doc1", 17, "Content 17", 14.0)
# Document 2
DOC_2_FILLER_1 = create_inference_chunk("doc2", 1, "Doc 2 Content 1", 15.0)
DOC_2_FILLER_2 = create_inference_chunk("doc2", 2, "Doc 2 Content 2", 16.0)
# This chunk below has top score for testing
DOC_2_TOP_CHUNK = create_inference_chunk("doc2", 3, "Doc 2 Content 3", 170.0)
DOC_2_FILLER_3 = create_inference_chunk("doc2", 4, "Doc 2 Content 4", 18.0)
DOC_2_BOTTOM_CHUNK = create_inference_chunk("doc2", 5, "Doc 2 Content 5", 19.0)
DOC_2_FILLER_4 = create_inference_chunk("doc2", 6, "Doc 2 Content 6", 20.0)
DOC_2_FILLER_5 = create_inference_chunk("doc2", 7, "Doc 2 Content 7", 21.0)


# Doc 2 has the highest score so it comes first
EXPECTED_CONTENT_1 = """
Doc 2 Content 1
Doc 2 Content 2
Doc 2 Content 3
Doc 2 Content 4
Doc 2 Content 5
Doc 2 Content 6
Doc 2 Content 7
""".strip()


EXPECTED_CONTENT_2 = """
Content 2
Content 3
Content 4
Content 5
Content 6
Content 7
Content 8
Content 9
Content 10

...

Content 13
Content 14
Content 15
Content 16
Content 17
""".strip()


@pytest.mark.parametrize(
    "sections,expected_contents,expected_center_chunks",
    [
        (
            # Sections
            [
                # Document 1, top/middle/bot connected + disconnected section
                inference_section_from_chunks(
                    center_chunk=DOC_1_TOP_CHUNK,
                    chunks=[
                        DOC_1_FILLER_1,
                        DOC_1_FILLER_2,
                        DOC_1_TOP_CHUNK,
                        DOC_1_MID_CHUNK,
                        DOC_1_FILLER_3,
                    ],
                ),
                inference_section_from_chunks(
                    center_chunk=DOC_1_MID_CHUNK,
                    chunks=[
                        DOC_1_FILLER_2,
                        DOC_1_TOP_CHUNK,
                        DOC_1_MID_CHUNK,
                        DOC_1_FILLER_3,
                        DOC_1_FILLER_4,
                    ],
                ),
                inference_section_from_chunks(
                    center_chunk=DOC_1_BOTTOM_CHUNK,
                    chunks=[
                        DOC_1_FILLER_3,
                        DOC_1_FILLER_4,
                        DOC_1_BOTTOM_CHUNK,
                        DOC_1_FILLER_5,
                        DOC_1_FILLER_6,
                    ],
                ),
                inference_section_from_chunks(
                    center_chunk=DOC_1_DISCONNECTED,
                    chunks=[
                        DOC_1_FILLER_7,
                        DOC_1_FILLER_8,
                        DOC_1_DISCONNECTED,
                        DOC_1_FILLER_9,
                        DOC_1_FILLER_10,
                    ],
                ),
                inference_section_from_chunks(
                    center_chunk=DOC_2_TOP_CHUNK,
                    chunks=[
                        DOC_2_FILLER_1,
                        DOC_2_FILLER_2,
                        DOC_2_TOP_CHUNK,
                        DOC_2_FILLER_3,
                        DOC_2_BOTTOM_CHUNK,
                    ],
                ),
                inference_section_from_chunks(
                    center_chunk=DOC_2_BOTTOM_CHUNK,
                    chunks=[
                        DOC_2_TOP_CHUNK,
                        DOC_2_FILLER_3,
                        DOC_2_BOTTOM_CHUNK,
                        DOC_2_FILLER_4,
                        DOC_2_FILLER_5,
                    ],
                ),
            ],
            # Expected Content
            [EXPECTED_CONTENT_1, EXPECTED_CONTENT_2],
            # Expected Center Chunks (highest scores)
            [DOC_2_TOP_CHUNK, DOC_1_BOTTOM_CHUNK],
        ),
    ],
)
def test_merge_sections(
    sections: list[InferenceSection],
    expected_contents: list[str],
    expected_center_chunks: list[InferenceChunk],
) -> None:
    sections.sort(key=lambda section: section.center_chunk.score or 0, reverse=True)
    merged_sections = _merge_sections(sections)
    assert merged_sections[0].combined_content == expected_contents[0]
    assert merged_sections[1].combined_content == expected_contents[1]
    assert merged_sections[0].center_chunk == expected_center_chunks[0]
    assert merged_sections[1].center_chunk == expected_center_chunks[1]


@pytest.mark.parametrize(
    "sections,expected_content,expected_center_chunk",
    [
        (
            # Sections
            [
                inference_section_from_chunks(
                    center_chunk=DOC_1_TOP_CHUNK,
                    chunks=[DOC_1_TOP_CHUNK],
                ),
                inference_section_from_chunks(
                    center_chunk=DOC_1_MID_CHUNK,
                    chunks=[DOC_1_MID_CHUNK],
                ),
            ],
            # Expected Content
            "Content 4\nContent 5",
            # Expected Center Chunks (highest scores)
            DOC_1_MID_CHUNK,
        ),
    ],
)
def test_merge_minimal_sections(
    sections: list[InferenceSection],
    expected_content: str,
    expected_center_chunk: InferenceChunk,
) -> None:
    sections.sort(key=lambda section: section.center_chunk.score or 0, reverse=True)
    merged_sections = _merge_sections(sections)
    assert merged_sections[0].combined_content == expected_content
    assert merged_sections[0].center_chunk == expected_center_chunk
