from onyx.connectors.models import Section
from onyx.indexing.document_chunker.section_chunker import AccumulatorState
from onyx.indexing.document_chunker.section_chunker import ChunkPayload
from onyx.indexing.document_chunker.section_chunker import SectionChunker
from onyx.indexing.document_chunker.section_chunker import SectionChunkerOutput
from onyx.utils.text_processing import clean_text


class ImageChunker(SectionChunker):
    """Per-section chunker for image sections.

    Image sections are structurally standalone: they always flush any
    pending accumulator results, then emit exactly one chunk carrying
    the `image_file_id` and the pre-generated image summary text.
    """

    def chunk_section(
        self,
        section: Section,
        accumulator: AccumulatorState,
        content_token_limit: int,  # noqa: ARG002
    ) -> SectionChunkerOutput:
        assert section.image_file_id is not None, (
            "ImageChunker.chunk_section called on a non-image section"
        )

        section_text = clean_text(str(section.text or ""))
        section_link = section.link or ""

        payloads = accumulator.flush_to_list()
        payloads.append(
            ChunkPayload(
                text=section_text,
                links={0: section_link} if section_link else {},
                image_file_id=section.image_file_id,
                is_continuation=False,
            )
        )

        return SectionChunkerOutput(
            payloads=payloads,
            accumulator=AccumulatorState(),
        )
