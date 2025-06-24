from collections.abc import Callable
from collections.abc import Iterator
from functools import partial
from typing import cast

from sqlalchemy.orm import Session

from danswer.chat.chat_utils import create_chat_chain
from danswer.chat.models import CitationInfo
from danswer.chat.models import CustomToolResponse
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import ImageGenerationDisplay
from danswer.chat.models import LLMRelevanceFilterResponse
from danswer.chat.models import QADocsResponse
from danswer.chat.models import StreamingError
from danswer.configs.chat_configs import CHAT_TARGET_CHUNK_PERCENTAGE
from danswer.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from danswer.configs.constants import MessageType
from danswer.db.chat import attach_files_to_chat_message
from danswer.db.chat import create_new_chat_message
from danswer.db.chat import get_chat_message
from danswer.db.chat import get_chat_session_by_id
from danswer.db.chat import get_db_search_doc_by_id
from danswer.db.chat import get_or_create_root_message
from danswer.db.chat import translate_db_message_to_chat_message_detail
from danswer.db.models import SearchDoc as DbSearchDoc
from danswer.db.models import User
from danswer.file_store.utils import load_all_chat_files
from danswer.llm.answering.answer import Answer
from danswer.llm.answering.models import AnswerStyleConfig
from danswer.llm.answering.models import CitationConfig
from danswer.llm.answering.models import DocumentPruningConfig
from danswer.llm.answering.models import PreviousMessage
from danswer.llm.answering.models import PromptConfig
from danswer.llm.exceptions import GenAIDisabledException
from danswer.llm.factory import get_llm_for_persona
from danswer.llm.utils import get_default_llm_tokenizer
from danswer.server.query_and_chat.models import ChatMessageDetail
from danswer.server.query_and_chat.models import CreateChatMessageRequest
from danswer.utils.logger import setup_logger

logger = setup_logger()


def translate_citations(
    citations_list: list[CitationInfo], db_docs: list[DbSearchDoc]
) -> dict[int, int]:
    """Always cites the first instance of the document_id, assumes the db_docs
    are sorted in the order displayed in the UI"""
    doc_id_to_saved_doc_id_map: dict[str, int] = {}
    for db_doc in db_docs:
        if db_doc.document_id not in doc_id_to_saved_doc_id_map:
            doc_id_to_saved_doc_id_map[db_doc.document_id] = db_doc.id

    citation_to_saved_doc_id_map: dict[int, int] = {}
    for citation in citations_list:
        if citation.citation_num not in citation_to_saved_doc_id_map:
            citation_to_saved_doc_id_map[
                citation.citation_num
            ] = doc_id_to_saved_doc_id_map[citation.document_id]

    return citation_to_saved_doc_id_map


ChatPacket = (
    StreamingError
    | QADocsResponse
    | LLMRelevanceFilterResponse
    | ChatMessageDetail
    | DanswerAnswerPiece
    | CitationInfo
    | ImageGenerationDisplay
    | CustomToolResponse
)
ChatPacketStream = Iterator[ChatPacket]


def stream_chat_message_objects(
    new_msg_req: CreateChatMessageRequest,
    user: User | None,
    db_session: Session,
    # Needed to translate persona num_chunks to tokens to the LLM
    default_num_chunks: float = MAX_CHUNKS_FED_TO_CHAT,
    # For flow with search, don't include as many chunks as possible since we need to leave space
    # for the chat history, for smaller models, we likely won't get MAX_CHUNKS_FED_TO_CHAT chunks
    max_document_percentage: float = CHAT_TARGET_CHUNK_PERCENTAGE,
    # if specified, uses the last user message and does not create a new user message based
    # on the `new_msg_req.message`. Currently, requires a state where the last message is a
    # user message (e.g. this can only be used for the chat-seeding flow).
    use_existing_user_message: bool = False,
    litellm_additional_headers: dict[str, str] | None = None,
) -> ChatPacketStream:
    """Streams in order:
    1. [conditional] Retrieved documents if a search needs to be run
    2. [conditional] LLM selected chunk indices if LLM chunk filtering is turned on
    3. [always] A set of streamed LLM tokens or an error anywhere along the line if something fails
    4. [always] Details on the final AI response message that is created

    """
    try:
        user_id = user.id if user is not None else None

        chat_session = get_chat_session_by_id(
            chat_session_id=new_msg_req.chat_session_id,
            user_id=user_id,
            db_session=db_session,
        )

        message_text = new_msg_req.message
        chat_session_id = new_msg_req.chat_session_id
        parent_id = new_msg_req.parent_message_id
        reference_doc_ids = new_msg_req.search_doc_ids
        retrieval_options = new_msg_req.retrieval_options
        persona = chat_session.persona

        prompt_id = new_msg_req.prompt_id
        if prompt_id is None and persona.prompts:
            prompt_id = sorted(persona.prompts, key=lambda x: x.id)[-1].id

        if reference_doc_ids is None and retrieval_options is None:
            raise RuntimeError(
                "Must specify a set of documents for chat or specify search options"
            )

        try:
            llm = get_llm_for_persona(
                persona=persona,
                llm_override=new_msg_req.llm_override or chat_session.llm_override,
                additional_headers=litellm_additional_headers,
            )
        except GenAIDisabledException:
            raise RuntimeError("LLM is disabled. Can't use chat flow without LLM.")

        llm_tokenizer = get_default_llm_tokenizer()
        llm_tokenizer_encode_func = cast(
            Callable[[str], list[int]], llm_tokenizer.encode
        )

        root_message = get_or_create_root_message(
            chat_session_id=chat_session_id, db_session=db_session
        )

        if parent_id is not None:
            parent_message = get_chat_message(
                chat_message_id=parent_id,
                user_id=user_id,
                db_session=db_session,
            )
        else:
            parent_message = root_message

        user_message = None
        if not use_existing_user_message:
            # Create new message at the right place in the tree and update the parent's child pointer
            # Don't commit yet until we verify the chat message chain
            user_message = create_new_chat_message(
                chat_session_id=chat_session_id,
                parent_message=parent_message,
                prompt_id=prompt_id,
                message=message_text,
                token_count=len(llm_tokenizer_encode_func(message_text)),
                message_type=MessageType.USER,
                files=None,  # Need to attach later for optimization to only load files once in parallel
                db_session=db_session,
                commit=False,
            )
            # re-create linear history of messages
            final_msg, history_msgs = create_chat_chain(
                chat_session_id=chat_session_id, db_session=db_session
            )
            if final_msg.id != user_message.id:
                db_session.rollback()
                raise RuntimeError(
                    "The new message was not on the mainline. "
                    "Be sure to update the chat pointers before calling this."
                )

            # NOTE: do not commit user message - it will be committed when the
            # assistant message is successfully generated
        else:
            # re-create linear history of messages
            final_msg, history_msgs = create_chat_chain(
                chat_session_id=chat_session_id, db_session=db_session
            )
            if final_msg.message_type != MessageType.USER:
                raise RuntimeError(
                    "The last message was not a user message. Cannot call "
                    "`stream_chat_message_objects` with `is_regenerate=True` "
                    "when the last message is not a user message."
                )

        # load all files needed for this chat chain in memory
        files = load_all_chat_files(
            history_msgs, new_msg_req.file_descriptors, db_session
        )
        latest_query_files = [
            file
            for file in files
            if file.file_id in [f["id"] for f in new_msg_req.file_descriptors]
        ]

        if user_message:
            attach_files_to_chat_message(
                chat_message=user_message,
                files=[
                    new_file.to_file_descriptor() for new_file in latest_query_files
                ],
                db_session=db_session,
                commit=False,
            )

        # Cannot determine these without the LLM step or breaking out early
        partial_response = partial(
            create_new_chat_message,
            chat_session_id=chat_session_id,
            parent_message=final_msg,
            prompt_id=prompt_id,
            # message=,
            # rephrased_query=,
            # token_count=,
            message_type=MessageType.ASSISTANT,
            # error=,
            # reference_docs=,
            db_session=db_session,
            commit=False,
        )

        if not final_msg.prompt:
            raise RuntimeError("No Prompt found")

        prompt_config = PromptConfig.from_model(
            final_msg.prompt,
            prompt_override=(
                new_msg_req.prompt_override or chat_session.prompt_override
            ),
        )

        # LLM prompt building, response capturing, etc.
        answer = Answer(
            question=final_msg.message,
            latest_query_files=latest_query_files,
            prompt_config=prompt_config,
            llm=(
                llm
                or get_llm_for_persona(
                    persona=persona,
                    llm_override=new_msg_req.llm_override or chat_session.llm_override,
                    additional_headers=litellm_additional_headers,
                )
            ),
            message_history=[
                PreviousMessage.from_chat_message(msg, files) for msg in history_msgs
            ]
        )

        reference_db_search_docs = None
        qa_docs_response = None
        ai_message_files = None  # any files to associate with the AI message e.g. dall-e generated images

    except Exception as e:
        logger.exception("Failed to process chat message")

        # Don't leak the API key
        error_msg = str(e)
        if llm.config.api_key and llm.config.api_key.lower() in error_msg.lower():
            error_msg = (
                f"LLM failed to respond. Invalid API "
                f"key error from '{llm.config.model_provider}'."
            )

        yield StreamingError(error=error_msg)
        # Cancel the transaction so that no messages are saved
        db_session.rollback()
        return

    # Post-LLM answer processing
    try:
        db_citations = None
        if reference_db_search_docs:
            db_citations = translate_citations(
                citations_list=answer.citations,
                db_docs=reference_db_search_docs,
            )

        # Saving Gen AI answer and responding with message info
        

        gen_ai_response_message = partial_response(
            message=answer.llm_answer,
            rephrased_query=(
                qa_docs_response.rephrased_query if qa_docs_response else None
            ),
            reference_docs=reference_db_search_docs,
            files=ai_message_files,
            token_count=len(llm_tokenizer_encode_func(answer.llm_answer)),
            citations=db_citations,
            error=None,
            tool_calls=[]
        )
        db_session.commit()  # actually save user / assistant message

        msg_detail_response = translate_db_message_to_chat_message_detail(
            gen_ai_response_message
        )

        yield msg_detail_response
    except Exception as e:
        logger.exception(e)

        # Frontend will erase whatever answer and show this instead
        yield StreamingError(error="Failed to parse LLM output")