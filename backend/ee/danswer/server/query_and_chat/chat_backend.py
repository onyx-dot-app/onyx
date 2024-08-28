import re

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from danswer.auth.users import current_user
from danswer.chat.chat_utils import create_chat_chain
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import LLMRelevanceFilterResponse
from danswer.chat.models import QADocsResponse
from danswer.chat.models import StreamingError
from danswer.chat.process_message import stream_chat_message_objects
from danswer.configs.constants import MessageType
from danswer.configs.danswerbot_configs import DANSWER_BOT_TARGET_CHUNK_PERCENTAGE
from danswer.db.chat import create_chat_session
from danswer.db.chat import create_new_chat_message
from danswer.db.chat import get_or_create_root_message
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.llm.factory import get_llms_for_persona
from danswer.llm.utils import get_max_input_tokens
from danswer.natural_language_processing.utils import get_tokenizer
from danswer.one_shot_answer.qa_utils import combine_message_thread
from danswer.search.models import OptionalSearchSetting
from danswer.search.models import RetrievalDetails
from danswer.secondary_llm_flows.query_expansion import thread_based_query_rephrase
from danswer.server.query_and_chat.models import ChatMessageDetail
from danswer.server.query_and_chat.models import CreateChatMessageRequest
from danswer.utils.logger import setup_logger
from ee.danswer.server.query_and_chat.models import BasicCreateChatMessageRequest
from ee.danswer.server.query_and_chat.models import (
    BasicCreateChatMessageWithHistoryRequest,
)
from ee.danswer.server.query_and_chat.models import ChatBasicResponse
from ee.danswer.server.query_and_chat.models import SimpleDoc

logger = setup_logger()

router = APIRouter(prefix="/chat")


def translate_doc_response_to_simple_doc(
    doc_response: QADocsResponse,
) -> list[SimpleDoc]:
    return [
        SimpleDoc(
            id=doc.document_id,
            semantic_identifier=doc.semantic_identifier,
            link=doc.link,
            blurb=doc.blurb,
            match_highlights=[
                highlight for highlight in doc.match_highlights if highlight
            ],
            source_type=doc.source_type,
            metadata=doc.metadata,
        )
        for doc in doc_response.top_documents
    ]


def remove_answer_citations(answer: str) -> str:
    pattern = r"\s*\[\[\d+\]\]\(http[s]?://[^\s]+\)"

    return re.sub(pattern, "", answer)


@router.post("/send-message-simple-api")
def handle_simplified_chat_message(
    chat_message_req: BasicCreateChatMessageRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatBasicResponse:
    """This is a Non-Streaming version that only gives back a minimal set of information"""
    logger.notice(f"Received new simple api chat message: {chat_message_req.message}")

    if not chat_message_req.message:
        raise HTTPException(status_code=400, detail="Empty chat message is invalid")

    try:
        parent_message, _ = create_chat_chain(
            chat_session_id=chat_message_req.chat_session_id, db_session=db_session
        )
    except Exception:
        parent_message = get_or_create_root_message(
            chat_session_id=chat_message_req.chat_session_id, db_session=db_session
        )

    if (
        chat_message_req.retrieval_options is None
        and chat_message_req.search_doc_ids is None
    ):
        retrieval_options: RetrievalDetails | None = RetrievalDetails(
            run_search=OptionalSearchSetting.ALWAYS,
            real_time=False,
        )
    else:
        retrieval_options = chat_message_req.retrieval_options

    full_chat_msg_info = CreateChatMessageRequest(
        chat_session_id=chat_message_req.chat_session_id,
        parent_message_id=parent_message.id,
        message=chat_message_req.message,
        file_descriptors=[],
        prompt_id=None,
        search_doc_ids=chat_message_req.search_doc_ids,
        retrieval_options=retrieval_options,
        query_override=chat_message_req.query_override,
        # Currently only applies to search flow not chat
        chunks_above=0,
        chunks_below=0,
        full_doc=chat_message_req.full_doc,
    )

    packets = stream_chat_message_objects(
        new_msg_req=full_chat_msg_info,
        user=user,
        db_session=db_session,
    )

    response = ChatBasicResponse()

    answer = ""
    for packet in packets:
        if isinstance(packet, DanswerAnswerPiece) and packet.answer_piece:
            answer += packet.answer_piece
        elif isinstance(packet, QADocsResponse):
            response.simple_search_docs = translate_doc_response_to_simple_doc(packet)
        elif isinstance(packet, StreamingError):
            response.error_msg = packet.error
        elif isinstance(packet, ChatMessageDetail):
            response.message_id = packet.message_id

    response.answer = answer
    if answer:
        response.answer_citationless = remove_answer_citations(answer)

    return response


@router.post("/send-message-simple-with-history")
def handle_send_message_simple_with_history(
    req: BasicCreateChatMessageWithHistoryRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatBasicResponse:
    """This is a Non-Streaming version that only gives back a minimal set of information.
    takes in chat history maintained by the caller
    and does query rephrasing similar to answer-with-quote"""

    if len(req.messages) == 0:
        raise HTTPException(status_code=400, detail="Messages cannot be zero length")

    expected_role = MessageType.USER
    for msg in req.messages:
        if not msg.message:
            raise HTTPException(
                status_code=400, detail="One or more chat messages were empty"
            )

        if msg.role != expected_role:
            raise HTTPException(
                status_code=400,
                detail="Message roles must start and end with MessageType.USER and alternate in-between.",
            )
        if expected_role == MessageType.USER:
            expected_role = MessageType.ASSISTANT
        else:
            expected_role = MessageType.USER

    query = req.messages[-1].message
    msg_history = req.messages[:-1]

    logger.notice(f"Received new simple with history chat message: {query}")

    user_id = user.id if user is not None else None
    chat_session = create_chat_session(
        db_session=db_session,
        description="handle_send_message_simple_with_history",
        user_id=user_id,
        persona_id=req.persona_id,
        one_shot=False,
    )

    llm, _ = get_llms_for_persona(persona=chat_session.persona)

    llm_tokenizer = get_tokenizer(
        model_name=llm.config.model_name,
        provider_type=llm.config.model_provider,
    )

    input_tokens = get_max_input_tokens(
        model_name=llm.config.model_name, model_provider=llm.config.model_provider
    )
    max_history_tokens = int(input_tokens * DANSWER_BOT_TARGET_CHUNK_PERCENTAGE)

    # Every chat Session begins with an empty root message
    root_message = get_or_create_root_message(
        chat_session_id=chat_session.id, db_session=db_session
    )

    chat_message = root_message
    for msg in msg_history:
        chat_message = create_new_chat_message(
            chat_session_id=chat_session.id,
            parent_message=chat_message,
            prompt_id=req.prompt_id,
            message=msg.message,
            token_count=len(llm_tokenizer.encode(msg.message)),
            message_type=msg.role,
            db_session=db_session,
            commit=False,
        )
    db_session.commit()

    history_str = combine_message_thread(
        messages=msg_history,
        max_tokens=max_history_tokens,
        llm_tokenizer=llm_tokenizer,
    )

    rephrased_query = req.query_override or thread_based_query_rephrase(
        user_query=query,
        history_str=history_str,
    )

    full_chat_msg_info = CreateChatMessageRequest(
        chat_session_id=chat_session.id,
        parent_message_id=chat_message.id,
        message=query,
        file_descriptors=[],
        prompt_id=req.prompt_id,
        search_doc_ids=None,
        retrieval_options=req.retrieval_options,
        query_override=rephrased_query,
        chunks_above=0,
        chunks_below=0,
        full_doc=req.full_doc,
    )

    packets = stream_chat_message_objects(
        new_msg_req=full_chat_msg_info,
        user=user,
        db_session=db_session,
    )

    response = ChatBasicResponse()

    answer = ""
    for packet in packets:
        if isinstance(packet, DanswerAnswerPiece) and packet.answer_piece:
            answer += packet.answer_piece
        elif isinstance(packet, QADocsResponse):
            response.simple_search_docs = translate_doc_response_to_simple_doc(packet)
        elif isinstance(packet, StreamingError):
            response.error_msg = packet.error
        elif isinstance(packet, ChatMessageDetail):
            response.message_id = packet.message_id
        elif isinstance(packet, LLMRelevanceFilterResponse):
            response.llm_chunks_indices = packet.relevant_chunk_indices

    response.answer = answer
    if answer:
        response.answer_citationless = remove_answer_citations(answer)

    return response
