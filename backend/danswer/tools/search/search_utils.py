from danswer.chat.models import LlmDoc
from danswer.prompts.prompt_utils import clean_up_source


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
