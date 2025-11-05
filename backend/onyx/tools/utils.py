import json

from sqlalchemy.orm import Session

from onyx.configs.app_configs import AZURE_DALLE_API_KEY
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import IndexFilters
from onyx.context.search.postprocessing.postprocessing import cleanup_chunks
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.utils import inference_section_from_chunks
from onyx.db.connector import check_connectors_exist
from onyx.db.document import check_docs_exist
from onyx.db.models import LLMProvider
from onyx.db.models import User
from onyx.document_index.factory import get_current_primary_default_document_index
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.llm.utils import find_model_obj
from onyx.llm.utils import get_model_map
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.tools.models import ContextCompleteness
from onyx.tools.models import DocumentResult
from onyx.tools.models import DocumentRetrievalType
from onyx.tools.tool import Tool


def explicit_tool_calling_supported(model_provider: str, model_name: str) -> bool:
    model_map = get_model_map()
    model_obj = find_model_obj(
        model_map=model_map,
        provider=model_provider,
        model_name=model_name,
    )

    model_supports = (
        model_obj.get("supports_function_calling", False) if model_obj else False
    )
    return model_supports


def compute_tool_tokens(tool: Tool, llm_tokenizer: BaseTokenizer) -> int:
    return len(llm_tokenizer.encode(json.dumps(tool.tool_definition())))


def compute_all_tool_tokens(tools: list[Tool], llm_tokenizer: BaseTokenizer) -> int:
    return sum(compute_tool_tokens(tool, llm_tokenizer) for tool in tools)


def is_image_generation_available(db_session: Session) -> bool:
    providers = db_session.query(LLMProvider).all()
    for provider in providers:
        if provider.provider == "openai":
            return True

    return bool(AZURE_DALLE_API_KEY)


def is_document_search_available(db_session: Session) -> bool:
    docs_exist = check_docs_exist(db_session)
    connectors_exist = check_connectors_exist(db_session)
    return docs_exist or connectors_exist


def get_full_document_by_id(
    document_id: str,
    url: str,
    source_type: DocumentSource,
    source_method: str,
    db_session: Session,
    user: User | None = None,
    use_access_filters: bool = True,
) -> DocumentResult:
    """
    Generic method to retrieve full document content by document ID.

    Args:
        document_id: The document ID to retrieve
        url: The URL of the document
        source_type: The source type (e.g., DocumentSource.GOOGLE_DRIVE)
        source_method: How the document was accessed (e.g., "indexed", "federated")
        db_session: Database session
        user: User object for access control (optional)
        use_access_filters: Whether to apply user access filters (default: True)

    Returns:
        DocumentResult with full document content
    """
    try:
        # Get document index
        document_index = get_current_primary_default_document_index(db_session)

        # Build access filters if user is provided and filters are enabled
        access_filters = None
        if use_access_filters and user:
            access_filters = build_access_filters_for_user(
                user=user,
                session=db_session,
            )

        index_filters = IndexFilters(access_control_list=access_filters)

        # Create chunk request
        chunk_request = VespaChunkRequest(
            document_id=document_id, min_chunk_ind=None, max_chunk_ind=None
        )

        # Retrieve all chunks for the document
        retrieved_chunks = document_index.id_based_retrieval(
            chunk_requests=[chunk_request],
            filters=index_filters,
            batch_retrieval=False,
        )

        # Process chunks into full document
        result = process_chunks_to_document_result(
            chunks=retrieved_chunks,
            url=url,
            source_type=source_type,
            source_method=source_method,
            document_id=document_id,
        )
        return result

    except Exception as e:
        # Fallback: return empty result with error info
        return DocumentResult(
            title="Error",
            content=f"Failed to retrieve document content: {str(e)}",
            source=DocumentRetrievalType.INTERNAL,
            url=url,
            metadata={
                "error": str(e),
                "document_id": document_id,
                "access_method": "error_fallback",
            },
            completeness=ContextCompleteness.NO_CONTEXT,
        )


def process_chunks_to_document_result(
    chunks: list,
    url: str,
    source_type: DocumentSource,
    source_method: str,
    document_id: str | None = None,
) -> DocumentResult:
    """Shared utility to process chunks into full document content using existing infrastructure"""
    if not chunks:
        return DocumentResult(
            title="Unknown",
            content="No content available",
            source=DocumentRetrievalType.INTERNAL,
            url=url,
            metadata={"access_method": "no_chunks_found"},
            completeness=ContextCompleteness.NO_CONTEXT,
        )

    # Clean up chunks and use existing inference_section_from_chunks method
    cleaned_chunks = cleanup_chunks(chunks)

    if cleaned_chunks:
        section = inference_section_from_chunks(
            center_chunk=cleaned_chunks[0],
            chunks=cleaned_chunks,
        )

        if section:
            return DocumentResult(
                title=section.center_chunk.semantic_identifier,
                content=section.combined_content,  # Full document content from existing method
                source=DocumentRetrievalType.INTERNAL,
                url=url,
                metadata={
                    "source_type": section.center_chunk.source_type.value,
                    "total_chunks": str(len(section.chunks)),
                    "access_method": f"{source_method}_full_document",
                    "document_id": section.center_chunk.document_id,
                },
                completeness=ContextCompleteness.FULL_CONTEXT,
            )

    # Fallback to first chunk if combination fails
    chunk = chunks[0]

    # Handle both InferenceChunk and other chunk types
    title = getattr(chunk, "semantic_identifier", None) or getattr(
        getattr(chunk, "document", None), "semantic_identifier", "Unknown"
    )
    chunk_source_type = getattr(chunk, "source_type", None) or getattr(
        getattr(chunk, "document", None), "source", source_type
    )
    chunk_doc_id = getattr(chunk, "document_id", None) or getattr(
        getattr(chunk, "document", None), "id", document_id
    )

    return DocumentResult(
        title=title or "Unknown",
        content=chunk.content,
        source=DocumentRetrievalType.INTERNAL,
        url=url,
        metadata={
            "source_type": (
                chunk_source_type.value
                if chunk_source_type and hasattr(chunk_source_type, "value")
                else str(chunk_source_type) if chunk_source_type else "unknown"
            ),
            "chunk_id": str(chunk.chunk_id) if chunk.chunk_id else "",
            "access_method": f"{source_method}_single_chunk_fallback",
            "document_id": str(chunk_doc_id) if chunk_doc_id else "",
        },
        completeness=ContextCompleteness.PARTIAL_CONTEXT,
    )
