import re
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ee.onyx.server.query_and_chat.models import AgentAnswer
from ee.onyx.server.query_and_chat.models import AgentSubQuery
from ee.onyx.server.query_and_chat.models import AgentSubQuestion
from ee.onyx.server.query_and_chat.models import BasicCreateChatMessageRequest
from ee.onyx.server.query_and_chat.models import (
    BasicCreateChatMessageWithHistoryRequest,
)
from ee.onyx.server.query_and_chat.models import ChatBasicResponse
from onyx.auth.users import current_user
from onyx.chat.chat_utils import combine_message_thread
from onyx.chat.chat_utils import create_chat_chain
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import AllCitations
from onyx.chat.models import ExtendedToolResponse
from onyx.chat.models import FinalUsedContextDocsResponse
from onyx.chat.models import LlmDoc
from onyx.chat.models import LLMRelevanceFilterResponse
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.models import QADocsResponse
from onyx.chat.models import RefinedAnswerImprovement
from onyx.chat.models import StreamingError
from onyx.chat.models import SubQueryPiece
from onyx.chat.models import SubQuestionIdentifier
from onyx.chat.models import SubQuestionPiece
from onyx.chat.process_message import ChatPacketStream
from onyx.chat.process_message import stream_chat_message_objects
from onyx.configs.chat_configs import CHAT_TARGET_CHUNK_PERCENTAGE
from onyx.configs.constants import MessageType
from onyx.context.search.models import OptionalSearchSetting
from onyx.context.search.models import RetrievalDetails
from onyx.context.search.models import SavedSearchDoc
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.llm.factory import get_llms_for_persona
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.secondary_llm_flows.query_expansion import thread_based_query_rephrase
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/chat")


def _get_final_context_doc_indices(
    final_context_docs: list[LlmDoc] | None,
    top_docs: list[SavedSearchDoc] | None,
) -> list[int] | None:
    """
    this function returns a list of indices of the simple search docs
    that were actually fed to the LLM.
    """
    if final_context_docs is None or top_docs is None:
        return None

    final_context_doc_ids = {doc.document_id for doc in final_context_docs}
    return [
        i for i, doc in enumerate(top_docs) if doc.document_id in final_context_doc_ids
    ]


def _convert_packet_stream_to_response(
    packets: ChatPacketStream,
) -> ChatBasicResponse:
    response = ChatBasicResponse()
    final_context_docs: list[LlmDoc] = []

    answer = ""

    # accumulate stream data with these dicts
    agent_sub_questions: dict[tuple[int, int], AgentSubQuestion] = {}
    agent_answers: dict[tuple[int, int], AgentAnswer] = {}
    agent_sub_queries: dict[tuple[int, int, int], AgentSubQuery] = {}

    for packet in packets:
        if isinstance(packet, OnyxAnswerPiece) and packet.answer_piece:
            answer += packet.answer_piece
        elif isinstance(packet, QADocsResponse):
            response.top_documents = packet.top_documents

            # This is a no-op if agent_sub_questions hasn't already been filled
            if packet.level is not None and packet.level_question_num is not None:
                id = (packet.level, packet.level_question_num)
                if id in agent_sub_questions:
                    agent_sub_questions[id].document_ids = [
                        saved_search_doc.document_id
                        for saved_search_doc in packet.top_documents
                    ]
        elif isinstance(packet, StreamingError):
            response.error_msg = packet.error
        elif isinstance(packet, ChatMessageDetail):
            response.message_id = packet.message_id
        elif isinstance(packet, LLMRelevanceFilterResponse):
            response.llm_selected_doc_indices = packet.llm_selected_doc_indices

            # TODO: deprecate `llm_chunks_indices`
            response.llm_chunks_indices = packet.llm_selected_doc_indices
        elif isinstance(packet, FinalUsedContextDocsResponse):
            final_context_docs = packet.final_context_docs
        elif isinstance(packet, AllCitations):
            response.cited_documents = {
                citation.citation_num: citation.document_id
                for citation in packet.citations
            }
        # agentic packets
        elif isinstance(packet, SubQuestionPiece):
            if packet.level is not None and packet.level_question_num is not None:
                id = (packet.level, packet.level_question_num)
                if agent_sub_questions.get(id) is None:
                    agent_sub_questions[id] = AgentSubQuestion(
                        level=packet.level,
                        level_question_num=packet.level_question_num,
                        sub_question=packet.sub_question,
                        document_ids=[],
                    )
                else:
                    agent_sub_questions[id].sub_question += packet.sub_question

        elif isinstance(packet, AgentAnswerPiece):
            if packet.level is not None and packet.level_question_num is not None:
                id = (packet.level, packet.level_question_num)
                if agent_answers.get(id) is None:
                    agent_answers[id] = AgentAnswer(
                        level=packet.level,
                        level_question_num=packet.level_question_num,
                        answer=packet.answer_piece,
                        answer_type=packet.answer_type,
                    )
                else:
                    agent_answers[id].answer += packet.answer_piece
        elif isinstance(packet, SubQueryPiece):
            if packet.level is not None and packet.level_question_num is not None:
                sub_query_id = (
                    packet.level,
                    packet.level_question_num,
                    packet.query_id,
                )
                if agent_sub_queries.get(sub_query_id) is None:
                    agent_sub_queries[sub_query_id] = AgentSubQuery(
                        level=packet.level,
                        level_question_num=packet.level_question_num,
                        sub_query=packet.sub_query,
                        query_id=packet.query_id,
                    )
                else:
                    agent_sub_queries[sub_query_id].sub_query += packet.sub_query
        elif isinstance(packet, ExtendedToolResponse):
            # we shouldn't get this ... it gets intercepted and translated to QADocsResponse
            logger.warning(
                "_convert_packet_stream_to_response: Unexpected chat packet type ExtendedToolResponse!"
            )
        elif isinstance(packet, RefinedAnswerImprovement):
            response.agent_refined_answer_improvement = (
                packet.refined_answer_improvement
            )
        else:
            logger.warning(
                f"_convert_packet_stream_to_response - Unrecognized chat packet: type={type(packet)}"
            )

    response.final_context_doc_indices = _get_final_context_doc_indices(
        final_context_docs, response.top_documents
    )

    # organize / sort agent metadata for output
    if len(agent_sub_questions) > 0:
        response.agent_sub_questions = cast(
            dict[int, list[AgentSubQuestion]],
            SubQuestionIdentifier.make_dict_by_level(agent_sub_questions),
        )

    if len(agent_answers) > 0:
        # return the agent_level_answer from the first level or the last one depending
        # on agent_refined_answer_improvement
        response.agent_answers = cast(
            dict[int, list[AgentAnswer]],
            SubQuestionIdentifier.make_dict_by_level(agent_answers),
        )
        if response.agent_answers:
            selected_answer_level = (
                0
                if not response.agent_refined_answer_improvement
                else len(response.agent_answers) - 1
            )
            level_answers = response.agent_answers[selected_answer_level]
            for level_answer in level_answers:
                if level_answer.answer_type != "agent_level_answer":
                    continue

                answer = level_answer.answer
                break

    if len(agent_sub_queries) > 0:
        # subqueries are often emitted with trailing whitespace ... clean it up here
        # perhaps fix at the source?
        for v in agent_sub_queries.values():
            v.sub_query = v.sub_query.strip()

        response.agent_sub_queries = (
            AgentSubQuery.make_dict_by_level_and_question_index(agent_sub_queries)
        )

    response.answer = answer
    if answer:
        response.answer_citationless = remove_answer_citations(answer)

    return response


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

    return _convert_packet_stream_to_response(packets)


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
        prompt_id=req.prompt_id,
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

    return _convert_packet_stream_to_response(packets)
