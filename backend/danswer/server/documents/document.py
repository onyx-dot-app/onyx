from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from sqlalchemy.orm import Session

from danswer.auth.users import current_user
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.document_index.factory import get_default_document_index
from danswer.llm.utils import get_default_llm_token_encode
from danswer.prompts.prompt_utils import build_doc_context_str
from danswer.search.models import IndexFilters
from danswer.search.preprocessing.access_filters import build_access_filters_for_user
from danswer.server.documents.models import ChunkInfo
from danswer.server.documents.models import DocumentInfo


router = APIRouter(prefix="/document")


# Have to use a query parameter as FastAPI is interpreting the URL type document_ids
# as a different path
@router.get("/document-size-info")
def get_document_info(
    document_id: str = Query(...),
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DocumentInfo:
    embedding_model = get_current_db_embedding_model(db_session)

    document_index = get_default_document_index(
        primary_index_name=embedding_model.index_name, secondary_index_name=None
    )

    user_acl_filters = build_access_filters_for_user(user, db_session)
    filters = IndexFilters(access_control_list=user_acl_filters)

    inference_chunks = document_index.id_based_retrieval(
        document_id=document_id,
        min_chunk_ind=None,
        max_chunk_ind=None,
        filters=filters,
    )

    if not inference_chunks:
        raise HTTPException(status_code=404, detail="Document not found")

    contents = [chunk.content for chunk in inference_chunks]

    combined_contents = "\n".join(contents)

    # get actual document context used for LLM
    first_chunk = inference_chunks[0]
    tokenizer_encode = get_default_llm_token_encode()
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


@router.get("/chunk-info")
def get_chunk_info(
    document_id: str = Query(...),
    chunk_id: int = Query(...),
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChunkInfo:
    embedding_model = get_current_db_embedding_model(db_session)

    document_index = get_default_document_index(
        primary_index_name=embedding_model.index_name, secondary_index_name=None
    )

    user_acl_filters = build_access_filters_for_user(user, db_session)
    filters = IndexFilters(access_control_list=user_acl_filters)

    inference_chunks = document_index.id_based_retrieval(
        document_id=document_id,
        min_chunk_ind=chunk_id,
        max_chunk_ind=chunk_id,
        filters=filters,
    )

    if not inference_chunks:
        raise HTTPException(status_code=404, detail="Chunk not found")

    chunk_content = inference_chunks[0].content

    tokenizer_encode = get_default_llm_token_encode()

    return ChunkInfo(
        content=chunk_content, num_tokens=len(tokenizer_encode(chunk_content))
    )
