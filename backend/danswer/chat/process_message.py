from collections.abc import Callable
from collections.abc import Iterator
from functools import partial
from typing import cast

from sqlalchemy.orm import Session

from danswer.chat.chat_utils import create_chat_chain
from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import ImageGenerationDisplay
from danswer.chat.models import LlmDoc
from danswer.chat.models import LLMRelevanceFilterResponse
from danswer.chat.models import QADocsResponse
from danswer.chat.models import StreamingError
from danswer.configs.chat_configs import CHAT_TARGET_CHUNK_PERCENTAGE
from danswer.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from danswer.configs.constants import MessageType
from danswer.db.chat import create_db_search_doc
from danswer.db.chat import create_new_chat_message
from danswer.db.chat import get_chat_message
from danswer.db.chat import get_chat_session_by_id
from danswer.db.chat import get_db_search_doc_by_id
from danswer.db.chat import get_doc_query_identifiers_from_model
from danswer.db.chat import get_or_create_root_message
from danswer.db.chat import translate_db_message_to_chat_message_detail
from danswer.db.chat import translate_db_search_doc_to_server_search_doc
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.engine import get_session_context_manager
from danswer.db.llm import fetch_existing_llm_providers
from danswer.db.models import SearchDoc as DbSearchDoc
from danswer.db.models import User
from danswer.document_index.factory import get_default_document_index
from danswer.file_store.models import ChatFileType
from danswer.file_store.models import FileDescriptor
from danswer.file_store.utils import load_all_chat_files
from danswer.file_store.utils import save_files_from_urls
from danswer.llm.answering.answer import Answer
from danswer.llm.answering.models import AnswerStyleConfig
from danswer.llm.answering.models import CitationConfig
from danswer.llm.answering.models import DocumentPruningConfig
from danswer.llm.answering.models import PreviousMessage
from danswer.llm.answering.models import PromptConfig
from danswer.llm.exceptions import GenAIDisabledException
from danswer.llm.factory import get_llm_for_persona
from danswer.llm.utils import get_default_llm_tokenizer
from danswer.search.enums import OptionalSearchSetting
from danswer.search.retrieval.search_runner import inference_documents_from_ids
from danswer.search.utils import chunks_or_sections_to_search_docs
from danswer.server.query_and_chat.models import ChatMessageDetail
from danswer.server.query_and_chat.models import CreateChatMessageRequest
from danswer.server.utils import get_json_line
from danswer.tools.factory import get_tool_cls
from danswer.tools.force import ForceUseTool
from danswer.tools.images.image_generation_tool import IMAGE_GENERATION_RESPONSE_ID
from danswer.tools.images.image_generation_tool import ImageGenerationResponse
from danswer.tools.images.image_generation_tool import ImageGenerationTool
from danswer.tools.search.search_tool import SEARCH_RESPONSE_SUMMARY_ID
from danswer.tools.search.search_tool import SearchResponseSummary
from danswer.tools.search.search_tool import SearchTool
from danswer.tools.search.search_tool import SECTION_RELEVANCE_LIST_ID
from danswer.tools.tool import Tool
from danswer.tools.tool import ToolResponse
from danswer.tools.utils import compute_all_tool_tokens
from danswer.tools.utils import explicit_tool_calling_supported
from danswer.utils.logger import setup_logger
from danswer.utils.timing import log_generator_function_time

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


def _handle_search_tool_response_summary(
    packet: ToolResponse,
    db_session: Session,
    selected_search_docs: list[DbSearchDoc] | None,
) -> tuple[QADocsResponse, list[DbSearchDoc]]:
    response_sumary = cast(SearchResponseSummary, packet.response)

    if not selected_search_docs:
        top_docs = chunks_or_sections_to_search_docs(response_sumary.top_sections)
        reference_db_search_docs = [
            create_db_search_doc(server_search_doc=top_doc, db_session=db_session)
            for top_doc in top_docs
        ]
    else:
        reference_db_search_docs = selected_search_docs

    response_docs = [
        translate_db_search_doc_to_server_search_doc(db_search_doc)
        for db_search_doc in reference_db_search_docs
    ]
    return (
        QADocsResponse(
            rephrased_query=response_sumary.rephrased_query,
            top_documents=response_docs,
            predicted_flow=response_sumary.predicted_flow,
            predicted_search=response_sumary.predicted_search,
            applied_source_filters=response_sumary.final_filters.source_type,
            applied_time_cutoff=response_sumary.final_filters.time_cutoff,
            recency_bias_multiplier=response_sumary.recency_bias_multiplier,
        ),
        reference_db_search_docs,
    )


def _check_should_force_search(
    new_msg_req: CreateChatMessageRequest,
) -> ForceUseTool | None:
    if (
        new_msg_req.query_override
        or (
            new_msg_req.retrieval_options
            and new_msg_req.retrieval_options.run_search == OptionalSearchSetting.ALWAYS
        )
        or new_msg_req.search_doc_ids
    ):
        args = (
            {"query": new_msg_req.query_override}
            if new_msg_req.query_override
            else None
        )
        # if we are using selected docs, just put something here so the Tool doesn't need
        # to build its own args via an LLM call
        if new_msg_req.search_doc_ids:
            args = {"query": new_msg_req.message}

        return ForceUseTool(
            tool_name=SearchTool.name(),
            args=args,
        )
    return None


ChatPacket = (
    StreamingError
    | QADocsResponse
    | LLMRelevanceFilterResponse
    | ChatMessageDetail
    | DanswerAnswerPiece
    | CitationInfo
    | ImageGenerationDisplay
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
                persona, new_msg_req.llm_override or chat_session.llm_override
            )
        except GenAIDisabledException:
            raise RuntimeError("LLM is disabled. Can't use chat flow without LLM.")

        llm_tokenizer = get_default_llm_tokenizer()
        llm_tokenizer_encode_func = cast(
            Callable[[str], list[int]], llm_tokenizer.encode
        )

        embedding_model = get_current_db_embedding_model(db_session)
        document_index = get_default_document_index(
            primary_index_name=embedding_model.index_name, secondary_index_name=None
        )

        # Every chat Session begins with an empty root message
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
                files=[
                    {"id": str(file_id), "type": ChatFileType.IMAGE}
                    for file_id in new_msg_req.file_ids
                ],
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

            # Save now to save the latest chat message
            db_session.commit()
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
        files = load_all_chat_files(history_msgs, new_msg_req.file_ids, db_session)
        latest_query_files = [
            file for file in files if file.file_id in new_msg_req.file_ids
        ]

        selected_db_search_docs = None
        selected_llm_docs: list[LlmDoc] | None = None
        if reference_doc_ids:
            identifier_tuples = get_doc_query_identifiers_from_model(
                search_doc_ids=reference_doc_ids,
                chat_session=chat_session,
                user_id=user_id,
                db_session=db_session,
            )

            # Generates full documents currently
            # May extend to include chunk ranges
            selected_llm_docs = inference_documents_from_ids(
                doc_identifiers=identifier_tuples,
                document_index=document_index,
            )
            document_pruning_config = DocumentPruningConfig(
                is_manually_selected_docs=True
            )

            # In case the search doc is deleted, just don't include it
            # though this should never happen
            db_search_docs_or_none = [
                get_db_search_doc_by_id(doc_id=doc_id, db_session=db_session)
                for doc_id in reference_doc_ids
            ]

            selected_db_search_docs = [
                db_sd for db_sd in db_search_docs_or_none if db_sd
            ]

        else:
            document_pruning_config = DocumentPruningConfig(
                max_chunks=int(
                    persona.num_chunks
                    if persona.num_chunks is not None
                    else default_num_chunks
                ),
                max_window_percentage=max_document_percentage,
                use_sections=new_msg_req.chunks_above > 0
                or new_msg_req.chunks_below > 0,
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
            commit=True,
        )

        if not final_msg.prompt:
            raise RuntimeError("No Prompt found")

        prompt_config = PromptConfig.from_model(
            final_msg.prompt,
            prompt_override=(
                new_msg_req.prompt_override or chat_session.prompt_override
            ),
        )

        persona_tool_classes = [
            get_tool_cls(tool, db_session) for tool in persona.tools
        ]

        # factor in tool definition size when pruning
        document_pruning_config.tool_num_tokens = compute_all_tool_tokens(
            persona_tool_classes
        )
        document_pruning_config.using_tool_message = explicit_tool_calling_supported(
            llm.config.model_provider, llm.config.model_name
        )

        # NOTE: for now, only support SearchTool and ImageGenerationTool
        # in the future, will support arbitrary user-defined tools
        search_tool: SearchTool | None = None
        tools: list[Tool] = []
        for tool_cls in persona_tool_classes:
            if tool_cls.__name__ == SearchTool.__name__:
                search_tool = SearchTool(
                    db_session=db_session,
                    user=user,
                    persona=persona,
                    retrieval_options=retrieval_options,
                    prompt_config=prompt_config,
                    llm_config=llm.config,
                    pruning_config=document_pruning_config,
                    selected_docs=selected_llm_docs,
                    chunks_above=new_msg_req.chunks_above,
                    chunks_below=new_msg_req.chunks_below,
                    full_doc=new_msg_req.full_doc,
                )
                tools.append(search_tool)
            elif tool_cls.__name__ == ImageGenerationTool.__name__:
                dalle_key = None
                if llm and llm.config.api_key and llm.config.model_provider == "openai":
                    dalle_key = llm.config.api_key
                else:
                    llm_providers = fetch_existing_llm_providers(db_session)
                    openai_provider = next(
                        iter(
                            [
                                llm_provider
                                for llm_provider in llm_providers
                                if llm_provider.provider == "openai"
                            ]
                        ),
                        None,
                    )
                    if not openai_provider or not openai_provider.api_key:
                        raise ValueError(
                            "Image generation tool requires an OpenAI API key"
                        )
                    dalle_key = openai_provider.api_key
                tools.append(ImageGenerationTool(api_key=dalle_key))

        # LLM prompt building, response capturing, etc.
        answer = Answer(
            question=final_msg.message,
            latest_query_files=latest_query_files,
            answer_style_config=AnswerStyleConfig(
                citation_config=CitationConfig(
                    all_docs_useful=selected_db_search_docs is not None
                ),
                document_pruning_config=document_pruning_config,
            ),
            prompt_config=prompt_config,
            llm=(
                llm
                or get_llm_for_persona(
                    persona, new_msg_req.llm_override or chat_session.llm_override
                )
            ),
            message_history=[
                PreviousMessage.from_chat_message(msg, files) for msg in history_msgs
            ],
            tools=tools,
            force_use_tool=_check_should_force_search(new_msg_req),
        )

        reference_db_search_docs = None
        qa_docs_response = None
        ai_message_files = None  # any files to associate with the AI message e.g. dall-e generated images
        for packet in answer.processed_streamed_output:
            if isinstance(packet, ToolResponse):
                if packet.id == SEARCH_RESPONSE_SUMMARY_ID:
                    (
                        qa_docs_response,
                        reference_db_search_docs,
                    ) = _handle_search_tool_response_summary(
                        packet, db_session, selected_db_search_docs
                    )
                    yield qa_docs_response
                elif packet.id == SECTION_RELEVANCE_LIST_ID:
                    yield LLMRelevanceFilterResponse(
                        relevant_chunk_indices=packet.response
                    )
                elif packet.id == IMAGE_GENERATION_RESPONSE_ID:
                    img_generation_response = cast(
                        list[ImageGenerationResponse], packet.response
                    )

                    file_ids = save_files_from_urls(
                        [img.url for img in img_generation_response]
                    )
                    ai_message_files = [
                        FileDescriptor(id=str(file_id), type=ChatFileType.IMAGE)
                        for file_id in file_ids
                    ]
                    yield ImageGenerationDisplay(
                        file_ids=[str(file_id) for file_id in file_ids]
                    )

            else:
                yield cast(ChatPacket, packet)

    except Exception as e:
        logger.exception(e)

        # Frontend will erase whatever answer and show this instead
        # This will be the issue 99% of the time
        yield StreamingError(error="LLM failed to respond, have you set your API key?")
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
        )

        msg_detail_response = translate_db_message_to_chat_message_detail(
            gen_ai_response_message
        )

        yield msg_detail_response
    except Exception as e:
        logger.exception(e)

        # Frontend will erase whatever answer and show this instead
        yield StreamingError(error="Failed to parse LLM output")


@log_generator_function_time()
def stream_chat_message(
    new_msg_req: CreateChatMessageRequest,
    user: User | None,
    use_existing_user_message: bool = False,
) -> Iterator[str]:
    with get_session_context_manager() as db_session:
        objects = stream_chat_message_objects(
            new_msg_req=new_msg_req,
            user=user,
            db_session=db_session,
            use_existing_user_message=use_existing_user_message,
        )
        for obj in objects:
            yield get_json_line(obj.dict())
