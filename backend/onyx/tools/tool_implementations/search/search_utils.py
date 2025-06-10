from onyx.chat.models import LlmDoc
from onyx.context.search.models import InferenceSection
from onyx.prompts.prompt_utils import clean_up_source


def llm_doc_to_dict(llm_doc: LlmDoc, doc_num: int) -> dict:
    doc_dict = {
        "document_number": doc_num + 1,
        "title": llm_doc.semantic_identifier,
        "content": llm_doc.content,
        "source": clean_up_source(llm_doc.source_type),
        "metadata": llm_doc.metadata,
    }
    if llm_doc.updated_at:
        doc_dict["updated_at"] = llm_doc.updated_at.strftime("%B %d, %Y %H:%M")
    return doc_dict


def section_to_dict(section: InferenceSection, section_num: int) -> dict:
    doc_dict = {
        "document_number": section_num + 1,
        "title": section.center_chunk.semantic_identifier,
        "content": section.combined_content,
        "source": clean_up_source(section.center_chunk.source_type),
        "metadata": section.center_chunk.metadata,
    }
    if section.center_chunk.updated_at:
        doc_dict["updated_at"] = section.center_chunk.updated_at.strftime(
            "%B %d, %Y %H:%M"
        )
    return doc_dict


def section_to_llm_doc(section: InferenceSection) -> LlmDoc:
    possible_link_chunks = [section.center_chunk] + section.chunks
    link: str | None = None
    for chunk in possible_link_chunks:
        if chunk.source_links:
            link = list(chunk.source_links.values())[0]
            break

    return LlmDoc(
        document_id=section.center_chunk.document_id,
        content=section.combined_content,
        source_type=section.center_chunk.source_type,
        semantic_identifier=section.center_chunk.semantic_identifier,
        metadata=section.center_chunk.metadata,
        updated_at=section.center_chunk.updated_at,
        blurb=section.center_chunk.blurb,
        link=link,
        source_links=section.center_chunk.source_links,
        match_highlights=section.center_chunk.match_highlights,
    )
