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
