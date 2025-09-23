from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ee.onyx.server.query_and_chat.models import BasicCreateChatMessageRequest
from ee.onyx.server.query_and_chat.models import (
    BasicCreateChatMessageWithHistoryRequest,
)
from onyx.auth.users import current_user
from onyx.chat.chat_utils import combine_message_thread
from onyx.chat.chat_utils import create_chat_chain
from onyx.chat.models import ChatBasicResponse
from onyx.chat.process_message import gather_stream
from onyx.chat.process_message import stream_chat_message_objects
from onyx.configs.chat_configs import CHAT_TARGET_CHUNK_PERCENTAGE
from onyx.configs.constants import MessageType
from onyx.context.search.models import OptionalSearchSetting
from onyx.context.search.models import RetrievalDetails
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.llm.factory import get_llms_for_persona
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.secondary_llm_flows.query_expansion import thread_based_query_rephrase
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/chat")


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

    # Handle chat session creation if chat_session_id is not provided
    if chat_message_req.chat_session_id is None:
        if chat_message_req.persona_id is None:
            raise HTTPException(
                status_code=400,
                detail="Either chat_session_id or persona_id must be provided",
            )

        # Create a new chat session with the provided persona_id
        try:
            new_chat_session = create_chat_session(
                db_session=db_session,
                description="",  # Leave empty for simple API
                user_id=user.id if user else None,
                persona_id=chat_message_req.persona_id,
            )
            chat_session_id = new_chat_session.id
        except Exception as e:
            logger.exception(e)
            raise HTTPException(status_code=400, detail="Invalid Persona provided.")
    else:
        chat_session_id = chat_message_req.chat_session_id

    try:
        parent_message, _ = create_chat_chain(
            chat_session_id=chat_session_id, db_session=db_session
        )
    except Exception:
        parent_message = get_or_create_root_message(
            chat_session_id=chat_session_id, db_session=db_session
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
        chat_session_id=chat_session_id,
        parent_message_id=parent_message.id,
        message=chat_message_req.message,
        file_descriptors=[],
        search_doc_ids=chat_message_req.search_doc_ids,
        retrieval_options=retrieval_options,
        # Simple API does not support reranking, hide complexity from user
        rerank_settings=None,
        query_override=chat_message_req.query_override,
        # Currently only applies to search flow not chat
        chunks_above=0,
        chunks_below=0,
        full_doc=chat_message_req.full_doc,
        structured_response_format=chat_message_req.structured_response_format,
        use_agentic_search=chat_message_req.use_agentic_search,
    )

    packets = stream_chat_message_objects(
        new_msg_req=full_chat_msg_info,
        user=user,
        db_session=db_session,
        enforce_chat_session_id_for_search_docs=False,
    )

    return gather_stream(packets)


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

    # This is a sanity check to make sure the chat history is valid
    # It must start with a user message and alternate beteen user and assistant
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
    )

    llm, _ = get_llms_for_persona(persona=chat_session.persona)

    llm_tokenizer = get_tokenizer(
        model_name=llm.config.model_name,
        provider_type=llm.config.model_provider,
    )

    max_history_tokens = int(llm.config.max_input_tokens * CHAT_TARGET_CHUNK_PERCENTAGE)

    # Every chat Session begins with an empty root message
    root_message = get_or_create_root_message(
        chat_session_id=chat_session.id, db_session=db_session
    )

    chat_message = root_message
    for msg in msg_history:
        chat_message = create_new_chat_message(
            chat_session_id=chat_session.id,
            parent_message=chat_message,
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

    if req.retrieval_options is None and req.search_doc_ids is None:
        retrieval_options: RetrievalDetails | None = RetrievalDetails(
            run_search=OptionalSearchSetting.ALWAYS,
            real_time=False,
        )
    else:
        retrieval_options = req.retrieval_options

    full_chat_msg_info = CreateChatMessageRequest(
        chat_session_id=chat_session.id,
        parent_message_id=chat_message.id,
        message=query,
        file_descriptors=[],
        search_doc_ids=req.search_doc_ids,
        retrieval_options=retrieval_options,
        # Simple API does not support reranking, hide complexity from user
        rerank_settings=None,
        query_override=rephrased_query,
        chunks_above=0,
        chunks_below=0,
        full_doc=req.full_doc,
        structured_response_format=req.structured_response_format,
        use_agentic_search=req.use_agentic_search,
    )

    packets = stream_chat_message_objects(
        new_msg_req=full_chat_msg_info,
        user=user,
        db_session=db_session,
        enforce_chat_session_id_for_search_docs=False,
    )

    return gather_stream(packets)
