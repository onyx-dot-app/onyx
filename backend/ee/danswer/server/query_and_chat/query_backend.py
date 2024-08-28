from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from danswer.auth.users import current_user
from danswer.configs.danswerbot_configs import DANSWER_BOT_TARGET_CHUNK_PERCENTAGE
from danswer.danswerbot.slack.handlers.handle_standard_answers import (
    oneoff_standard_answers,
)
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.db.persona import get_persona_by_id
from danswer.llm.answering.prompts.citations_prompt import (
    compute_max_document_tokens_for_persona,
)
from danswer.llm.factory import get_default_llms
from danswer.llm.factory import get_llms_for_persona
from danswer.llm.factory import get_main_llm_from_tuple
from danswer.llm.utils import get_max_input_tokens
from danswer.one_shot_answer.answer_question import get_search_answer
from danswer.one_shot_answer.models import DirectQARequest
from danswer.one_shot_answer.models import OneShotQAResponse
from danswer.search.models import SavedSearchDocWithContent
from danswer.search.models import SearchRequest
from danswer.search.pipeline import SearchPipeline
from danswer.search.utils import dedupe_documents
from danswer.search.utils import drop_llm_indices
from danswer.search.utils import relevant_sections_to_indices
from danswer.utils.logger import setup_logger
from ee.danswer.server.query_and_chat.models import DocumentSearchRequest
from ee.danswer.server.query_and_chat.models import StandardAnswerRequest
from ee.danswer.server.query_and_chat.models import StandardAnswerResponse


logger = setup_logger()
basic_router = APIRouter(prefix="/query")


class DocumentSearchResponse(BaseModel):
    top_documents: list[SavedSearchDocWithContent]
    llm_indices: list[int]


@basic_router.post("/document-search")
def handle_search_request(
    search_request: DocumentSearchRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DocumentSearchResponse:
    """Simple search endpoint, does not create a new message or records in the DB"""
    query = search_request.message
    logger.notice(f"Received document search query: {query}")

    llm, fast_llm = get_default_llms()

    search_pipeline = SearchPipeline(
        search_request=SearchRequest(
            query=query,
            search_type=search_request.search_type,
            human_selected_filters=search_request.retrieval_options.filters,
            enable_auto_detect_filters=search_request.retrieval_options.enable_auto_detect_filters,
            persona=None,  # For simplicity, default settings should be good for this search
            offset=search_request.retrieval_options.offset,
            limit=search_request.retrieval_options.limit,
            rerank_settings=search_request.rerank_settings,
            evaluation_type=search_request.evaluation_type,
            chunks_above=search_request.chunks_above,
            chunks_below=search_request.chunks_below,
            full_doc=search_request.full_doc,
        ),
        user=user,
        llm=llm,
        fast_llm=fast_llm,
        db_session=db_session,
        bypass_acl=False,
    )
    top_sections = search_pipeline.reranked_sections
    relevance_sections = search_pipeline.section_relevance
    top_docs = [
        SavedSearchDocWithContent(
            document_id=section.center_chunk.document_id,
            chunk_ind=section.center_chunk.chunk_id,
            content=section.center_chunk.content,
            semantic_identifier=section.center_chunk.semantic_identifier or "Unknown",
            link=section.center_chunk.source_links.get(0)
            if section.center_chunk.source_links
            else None,
            blurb=section.center_chunk.blurb,
            source_type=section.center_chunk.source_type,
            boost=section.center_chunk.boost,
            hidden=section.center_chunk.hidden,
            metadata=section.center_chunk.metadata,
            score=section.center_chunk.score or 0.0,
            match_highlights=section.center_chunk.match_highlights,
            updated_at=section.center_chunk.updated_at,
            primary_owners=section.center_chunk.primary_owners,
            secondary_owners=section.center_chunk.secondary_owners,
            is_internet=False,
            db_doc_id=0,
        )
        for section in top_sections
    ]

    # Deduping happens at the last step to avoid harming quality by dropping content early on
    deduped_docs = top_docs
    dropped_inds = None

    if search_request.retrieval_options.dedupe_docs:
        deduped_docs, dropped_inds = dedupe_documents(top_docs)

    llm_indices = relevant_sections_to_indices(
        relevance_sections=relevance_sections, items=deduped_docs
    )

    if dropped_inds:
        llm_indices = drop_llm_indices(
            llm_indices=llm_indices,
            search_docs=deduped_docs,
            dropped_indices=dropped_inds,
        )

    return DocumentSearchResponse(top_documents=deduped_docs, llm_indices=llm_indices)


@basic_router.post("/answer-with-quote")
def get_answer_with_quote(
    query_request: DirectQARequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> OneShotQAResponse:
    query = query_request.messages[0].message
    logger.notice(f"Received query for one shot answer API with quotes: {query}")

    persona = get_persona_by_id(
        persona_id=query_request.persona_id,
        user=user,
        db_session=db_session,
        is_for_edit=False,
    )

    llm = get_main_llm_from_tuple(
        get_default_llms() if not persona else get_llms_for_persona(persona)
    )
    input_tokens = get_max_input_tokens(
        model_name=llm.config.model_name, model_provider=llm.config.model_provider
    )
    max_history_tokens = int(input_tokens * DANSWER_BOT_TARGET_CHUNK_PERCENTAGE)

    remaining_tokens = input_tokens - max_history_tokens

    max_document_tokens = compute_max_document_tokens_for_persona(
        persona=persona,
        actual_user_input=query,
        max_llm_token_override=remaining_tokens,
    )

    answer_details = get_search_answer(
        query_req=query_request,
        user=user,
        max_document_tokens=max_document_tokens,
        max_history_tokens=max_history_tokens,
        db_session=db_session,
    )

    return answer_details


@basic_router.get("/standard-answer")
def get_standard_answer(
    request: StandardAnswerRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_user),
) -> StandardAnswerResponse:
    try:
        standard_answers = oneoff_standard_answers(
            message=request.message,
            slack_bot_categories=request.slack_bot_categories,
            db_session=db_session,
        )
        return StandardAnswerResponse(standard_answers=standard_answers)
    except Exception as e:
        logger.error(f"Error in get_standard_answer: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred")
