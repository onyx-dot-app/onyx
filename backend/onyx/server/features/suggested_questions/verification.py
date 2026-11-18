"""The search test: a question is kept only when the search chat uses finds
its own document near the top, so a click gives an answer from that document.

No AI is involved: it is the same hybrid retrieval, without the LLM steps.
"""

from datetime import datetime, timezone
from uuid import uuid4

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import (
    ChunkIndexRequest,
    ChunkSearchRequest,
    IndexFilters,
    InferenceChunk,
    UserAccessFilters,
)
from onyx.context.search.pipeline import search_pipeline
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.retrieval.search_runner import search_chunks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import DocumentIndex
from onyx.natural_language_processing.english_stopwords import strip_stopwords
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.server.features.suggested_questions.config import (
    SQ_SEARCH_LIMIT,
    SQ_SEARCH_WORKERS,
    SQ_TOP_K_DOCS,
)
from onyx.server.features.suggested_questions.models import (
    DraftQuestion,
    PoolQuestion,
    QuestionKind,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.configs import MODEL_SERVER_HOST, MODEL_SERVER_PORT, MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def run_search_test(
    drafts: list[DraftQuestion], user: User | None
) -> list[PoolQuestion]:
    """Search each question and keep it when its document is among the first
    SQ_TOP_K_DOCS distinct documents. The searches run in parallel.

    A pool run passes no user and searches the whole index, so one test serves
    everyone. It is not a guarantee per person: scores are normalised over the
    documents a search can see, so a person's access filter can reorder what
    is left. Removing documents usually moves the source document up, and
    chat's own search reads more than 3 documents, so the answer still comes
    from it. A top-up passes the person and searches as them."""
    if not drafts:
        return []
    with get_session_with_current_tenant() as db_session:
        search_settings = get_current_search_settings(db_session)
        document_index = get_default_document_index(search_settings, None)
        embedding_model = EmbeddingModel.from_db_model(
            search_settings=search_settings,
            server_host=MODEL_SERVER_HOST,
            server_port=MODEL_SERVER_PORT,
        )
        # Built once: the access filters are the same for every question.
        acl_filters = build_access_filters_for_user(user, db_session) if user else None
    positions: list[int | None] = run_functions_tuples_in_parallel(
        [
            (
                _search_position,
                (draft, user, acl_filters, document_index, embedding_model),
            )
            for draft in drafts
        ],
        # Each search calls the model server, shared with indexing and chat.
        max_workers=SQ_SEARCH_WORKERS,
    )
    now = datetime.now(timezone.utc)
    passed = [
        PoolQuestion(
            id=uuid4().hex,
            text=draft.text,
            kind=(
                QuestionKind.USER_FILE
                if draft.chunk.source_type == DocumentSource.USER_FILE
                else QuestionKind.DOCUMENT
            ),
            document_id=draft.chunk.document_id,
            source_type=draft.chunk.source_type,
            search_position=position,
            best_for=draft.best_for,
            created_at=now,
        )
        for draft, position in zip(drafts, positions, strict=True)
        if position is not None
    ]
    logger.info(
        "Suggested questions: search test passed %d of %d questions",
        len(passed),
        len(drafts),
    )
    return passed


def _search_position(
    draft: DraftQuestion,
    user: User | None,
    acl_filters: UserAccessFilters | None,
    document_index: DocumentIndex,
    embedding_model: EmbeddingModel,
) -> int | None:
    """Where the question's document ranks among the first SQ_TOP_K_DOCS
    distinct documents, or None when it is not there. Positions are compared,
    not scores: hybrid scores are normalised per query."""
    chunks = (
        _search_as(user, acl_filters, draft.text, document_index, embedding_model)
        if user and acl_filters
        else _search_everything(draft.text, document_index, embedding_model)
    )
    documents = list(dict.fromkeys(chunk.document_id for chunk in chunks))
    top = documents[:SQ_TOP_K_DOCS]
    document_id = draft.chunk.document_id
    return top.index(document_id) if document_id in top else None


def _search_everything(
    query: str, document_index: DocumentIndex, embedding_model: EmbeddingModel
) -> list[InferenceChunk]:
    return search_chunks(
        query_request=ChunkIndexRequest(
            query=query,
            query_keywords=strip_stopwords(query),
            limit=SQ_SEARCH_LIMIT,
            filters=IndexFilters(
                access_control_list=None,
                tenant_id=get_current_tenant_id() if MULTI_TENANT else None,
            ),
        ),
        user_id=None,
        document_index=document_index,
        embedding_model=embedding_model,
        # No federated sources: a question must come from the index.
        prefetched_federated_retrieval_infos=[],
    )


def _search_as(
    user: User,
    acl_filters: UserAccessFilters,
    query: str,
    document_index: DocumentIndex,
    embedding_model: EmbeddingModel,
) -> list[InferenceChunk]:
    return search_pipeline(
        ChunkSearchRequest(query=query, limit=SQ_SEARCH_LIMIT),
        document_index,
        user,
        None,
        acl_filters=acl_filters,
        embedding_model=embedding_model,
        prefetched_federated_retrieval_infos=[],
    )
