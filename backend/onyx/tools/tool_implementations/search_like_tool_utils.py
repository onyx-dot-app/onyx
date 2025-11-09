from onyx.connectors.models import Document
from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import Section


FINAL_CONTEXT_DOCUMENTS_ID = "final_context_documents"
FINAL_SEARCH_QUERIES_ID = "final_search_queries"
SEARCH_INFERENCE_SECTIONS_ID = "search_inference_sections"


def documents_to_indexing_documents(
    documents: list[Document],
) -> list[IndexingDocument]:
    indexing_documents = []

    for document in documents:
        processed_sections = []
        for section in document.sections:
            processed_section = Section(
                text=section.text or "",
                link=section.link,
                image_file_id=None,
            )
            processed_sections.append(processed_section)

        indexed_document = IndexingDocument(
            **document.model_dump(), processed_sections=processed_sections
        )
        indexing_documents.append(indexed_document)
    return indexing_documents
