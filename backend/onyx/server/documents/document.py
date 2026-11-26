from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from onyx.access.access import censor_chunks_for_user
from onyx.auth.permissions import require_permission
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.context.search.models import IndexFilters
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.utils import inference_section_from_chunks
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import DocumentSectionRequest
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.prompts.prompt_utils import build_doc_context_str
from onyx.server.documents.models import (
    DOCUMENT_CONTENT_MAX_CHARS,
    DOCUMENT_CONTENT_MAX_CHUNKS,
    ChunkInfo,
    DocumentContent,
    DocumentInfo,
)
from onyx.server.utils_vector_db import require_vector_db

router = APIRouter(prefix="/document")


# Have to use a query parameter as FastAPI is interpreting the URL type document_ids
# as a different path
@router.get("/document-size-info", dependencies=[Depends(require_vector_db)])
def get_document_info(
    document_id: str = Query(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> DocumentInfo:
    search_settings = get_current_search_settings(db_session)
    document_index = get_default_document_index(search_settings, None)

    user_access_filters = build_access_filters_for_user(user, db_session)
    inference_chunks = censor_chunks_for_user(
        document_index.id_based_retrieval(
            chunk_requests=[DocumentSectionRequest(document_id=document_id)],
            filters=IndexFilters(
                access_control_list=user_access_filters.access_control_list,
                cc_pair_access=user_access_filters.cc_pair_access,
            ),
        ),
        user,
    )

    if not inference_chunks:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Document not found")

    contents = [chunk.content for chunk in inference_chunks]

    combined_contents = "\n".join(contents)

    # get actual document context used for LLM
    first_chunk = inference_chunks[0]
    tokenizer_encode = get_tokenizer(
        provider_type=search_settings.provider_type,
        model_name=search_settings.model_name,
    ).encode
    full_context_str = build_doc_context_str(
        semantic_identifier=first_chunk.semantic_identifier,
        source_type=first_chunk.source_type,
        content=combined_contents,
        metadata_dict=first_chunk.metadata,
        updated_at=first_chunk.updated_at,
        ind=0,
    )

    return DocumentInfo(
        num_chunks=len(inference_chunks),
        num_tokens=len(tokenizer_encode(full_context_str)),
    )


@router.get("/chunk-info", dependencies=[Depends(require_vector_db)])
def get_chunk_info(
    document_id: str = Query(...),
    chunk_id: int = Query(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ChunkInfo:
    search_settings = get_current_search_settings(db_session)
    document_index = get_default_document_index(search_settings, None)

    user_access_filters = build_access_filters_for_user(user, db_session)
    chunk_request = DocumentSectionRequest(
        document_id=document_id,
        min_chunk_ind=chunk_id,
        max_chunk_ind=chunk_id,
    )

    inference_chunks = censor_chunks_for_user(
        document_index.id_based_retrieval(
            chunk_requests=[chunk_request],
            filters=IndexFilters(
                access_control_list=user_access_filters.access_control_list,
                cc_pair_access=user_access_filters.cc_pair_access,
            ),
            batch_retrieval=True,
        ),
        user,
    )

    if not inference_chunks:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Chunk not found")

    chunk_content = inference_chunks[0].content

    tokenizer_encode = get_tokenizer(
        provider_type=search_settings.provider_type,
        model_name=search_settings.model_name,
    ).encode

    return ChunkInfo(
        content=chunk_content, num_tokens=len(tokenizer_encode(chunk_content))
    )


@router.get(
    "/content",
    dependencies=[Depends(require_vector_db)],
    tags=PUBLIC_API_TAGS,
)
def get_document_content(
    document_id: str = Query(...),
    user: User = Depends(require_permission(Permission.READ_SEARCH)),
    db_session: Session = Depends(get_session),
) -> DocumentContent:
    """
    Read the indexed text of one document by the `document_id` that search
    returns. The response is filtered by the calling user's document
    permissions: a document the user cannot access is reported as not found.
    """
    document_index = get_default_document_index(
        get_current_search_settings(db_session), None
    )
    user_access_filters = build_access_filters_for_user(user, db_session)
    chunks = censor_chunks_for_user(
        document_index.id_based_retrieval(
            chunk_requests=[
                DocumentSectionRequest(
                    document_id=document_id,
                    max_chunk_ind=DOCUMENT_CONTENT_MAX_CHUNKS,
                )
            ],
            filters=IndexFilters(
                access_control_list=user_access_filters.access_control_list,
                cc_pair_access=user_access_filters.cc_pair_access,
            ),
        ),
        user,
    )
    chunks.sort(key=lambda chunk: chunk.chunk_id)
    section = inference_section_from_chunks(chunks[0], chunks) if chunks else None
    if section is None:
        raise OnyxError(OnyxErrorCode.DOCUMENT_NOT_FOUND, "Document not found")
    if (
        len(chunks) > DOCUMENT_CONTENT_MAX_CHUNKS
        or len(section.combined_content) > DOCUMENT_CONTENT_MAX_CHARS
    ):
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"Document is larger than the {DOCUMENT_CONTENT_MAX_CHARS} character "
            "read limit. Use search results for its relevant sections.",
        )
    first = section.center_chunk
    return DocumentContent(
        document_id=first.document_id,
        title=first.semantic_identifier,
        content=section.combined_content,
        link=next(iter(first.source_links.values()), None)
        if first.source_links
        else None,
        source_type=first.source_type,
        updated_at=first.updated_at,
        metadata=first.metadata,
    )
