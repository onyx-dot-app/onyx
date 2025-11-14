import json
from collections.abc import Generator

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.onyxbot.slack.handlers.handle_standard_answers import (
    oneoff_standard_answers,
)
from ee.onyx.server.query_and_chat.models import DocumentSearchRequest
from ee.onyx.server.query_and_chat.models import OneShotQARequest
from ee.onyx.server.query_and_chat.models import OneShotQAResponse
from ee.onyx.server.query_and_chat.models import StandardAnswerRequest
from ee.onyx.server.query_and_chat.models import StandardAnswerResponse
from onyx.auth.users import current_user
from onyx.chat.chat_utils import combine_message_thread
from onyx.chat.chat_utils import prepare_chat_message_request
from onyx.chat.models import AnswerStream
from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.models import QADocsResponse
from onyx.chat.process_message import gather_stream
from onyx.chat.process_message import stream_chat_message_objects
from onyx.configs.onyxbot_configs import MAX_THREAD_CONTEXT_PERCENTAGE
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import InferenceChunk
from onyx.context.search.pipeline import search_pipeline
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.llm.factory import get_default_llms
from onyx.llm.factory import get_llms_for_persona
from onyx.llm.factory import get_main_llm_from_tuple
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.utils import get_json_line
from onyx.utils.logger import setup_logger


logger = setup_logger()
basic_router = APIRouter(prefix="/query")


class DocumentSearchPagination(BaseModel):
    offset: int
    limit: int
    returned_count: int
    has_more: bool
    next_offset: int | None = None


class DocumentSearchResponse(BaseModel):
    top_chunks: list[InferenceChunk]


def _translate_search_request(
    search_request: DocumentSearchRequest,
) -> ChunkSearchRequest:
    return ChunkSearchRequest(
        query=search_request.query,
        hybrid_alpha=search_request.hybrid_alpha,
        recency_bias_multiplier=search_request.recency_bias_multiplier,
        query_keywords=search_request.query_keywords,
        limit=search_request.limit,
        offset=search_request.offset,
        user_selected_filters=search_request.user_selected_filters,
        # No bypass_acl, not allowed for this endpoint
    )


@basic_router.post("/document-search")
def handle_search_request(
    search_request: DocumentSearchRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DocumentSearchResponse:
    """Simple search endpoint, does not create a new message or records in the DB"""
    query = search_request.query
    logger.notice(f"Received document search query: {query}")

    llm, _ = get_default_llms()

    search_settings = get_current_search_settings(db_session)
    document_index = get_default_document_index(
        search_settings=search_settings,
        secondary_search_settings=None,
    )

    retrieved_chunks = search_pipeline(
        chunk_search_request=_translate_search_request(search_request),
        document_index=document_index,
        user=user,
        persona=None,
        db_session=db_session,
        auto_detect_filters=False,
        llm=llm,
    )

    return DocumentSearchResponse(top_chunks=retrieved_chunks)


def get_answer_stream(
    query_request: OneShotQARequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AnswerStream:
    query = query_request.messages[0].message
    logger.notice(f"Received query for Answer API: {query}")

    if (
        query_request.persona_override_config is None
        and query_request.persona_id is None
    ):
        raise KeyError("Must provide persona ID or Persona Config")

    persona_info: Persona | PersonaOverrideConfig | None = None
    if query_request.persona_override_config is not None:
        persona_info = query_request.persona_override_config
    elif query_request.persona_id is not None:
        persona_info = get_persona_by_id(
            persona_id=query_request.persona_id,
            user=user,
            db_session=db_session,
            is_for_edit=False,
        )

    llm = get_main_llm_from_tuple(get_llms_for_persona(persona=persona_info, user=user))

    llm_tokenizer = get_tokenizer(
        model_name=llm.config.model_name,
        provider_type=llm.config.model_provider,
    )

    max_history_tokens = int(
        llm.config.max_input_tokens * MAX_THREAD_CONTEXT_PERCENTAGE
    )

    combined_message = combine_message_thread(
        messages=query_request.messages,
        max_tokens=max_history_tokens,
        llm_tokenizer=llm_tokenizer,
    )

    # Also creates a new chat session
    request = prepare_chat_message_request(
        message_text=combined_message,
        user=user,
        persona_id=query_request.persona_id,
        persona_override_config=query_request.persona_override_config,
        message_ts_to_respond_to=None,
        retrieval_details=query_request.retrieval_options,
        rerank_settings=query_request.rerank_settings,
        db_session=db_session,
        use_agentic_search=query_request.use_agentic_search,
        skip_gen_ai_answer_generation=query_request.skip_gen_ai_answer_generation,
    )

    packets = stream_chat_message_objects(
        new_msg_req=request,
        user=user,
        db_session=db_session,
    )

    return packets


@basic_router.post("/answer-with-citation")
def get_answer_with_citation(
    request: OneShotQARequest,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> OneShotQAResponse:
    try:
        packets = get_answer_stream(request, user, db_session)
        answer = gather_stream(packets)

        if answer.error_msg:
            raise RuntimeError(answer.error_msg)

        return OneShotQAResponse(
            answer=answer.answer,
            chat_message_id=answer.message_id,
            error_msg=answer.error_msg,
            citations=[
                CitationInfo(citation_number=i, document_id=doc_id)
                for i, doc_id in answer.cited_documents.items()
            ],
            docs=QADocsResponse(
                top_documents=answer.top_documents,
                predicted_flow=None,
                predicted_search=None,
                applied_source_filters=None,
                applied_time_cutoff=None,
                recency_bias_multiplier=0.0,
            ),
        )
    except Exception as e:
        logger.error(f"Error in get_answer_with_citation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred")


@basic_router.post("/stream-answer-with-citation")
def stream_answer_with_citation(
    request: OneShotQARequest,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> StreamingResponse:
    def stream_generator() -> Generator[str, None, None]:
        try:
            for packet in get_answer_stream(request, user, db_session):
                serialized = get_json_line(packet.model_dump())
                yield serialized
        except Exception as e:
            logger.exception("Error in answer streaming")
            yield json.dumps({"error": str(e)})

    return StreamingResponse(stream_generator(), media_type="application/json")


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
