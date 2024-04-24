from collections.abc import Callable
from collections.abc import Iterator

from sqlalchemy.orm import Session

from danswer.chat.chat_utils import llm_doc_from_inference_section
from danswer.chat.chat_utils import reorganize_citations
from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import DanswerContexts
from danswer.chat.models import DanswerQuotes
from danswer.chat.models import LLMRelevanceFilterResponse
from danswer.chat.models import QADocsResponse
from danswer.chat.models import StreamingError
from danswer.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from danswer.configs.chat_configs import QA_TIMEOUT
from danswer.configs.constants import MessageType
from danswer.db.chat import create_chat_session
from danswer.db.chat import create_db_search_doc
from danswer.db.chat import create_new_chat_message
from danswer.db.chat import get_or_create_root_message
from danswer.db.chat import get_prompt_by_id
from danswer.db.chat import translate_db_message_to_chat_message_detail
from danswer.db.chat import translate_db_search_doc_to_server_search_doc
from danswer.db.engine import get_session_context_manager
from danswer.db.models import User
from danswer.llm.answering.answer import Answer
from danswer.llm.answering.models import AnswerStyleConfig
from danswer.llm.answering.models import CitationConfig
from danswer.llm.answering.models import DocumentPruningConfig
from danswer.llm.answering.models import LLMConfig
from danswer.llm.answering.models import PromptConfig
from danswer.llm.answering.models import QuotesConfig
from danswer.llm.utils import get_default_llm_token_encode
from danswer.one_shot_answer.models import DirectQARequest
from danswer.one_shot_answer.models import OneShotQAResponse
from danswer.one_shot_answer.models import QueryRephrase
from danswer.one_shot_answer.qa_utils import combine_message_thread
from danswer.search.models import RerankMetricsContainer
from danswer.search.models import RetrievalMetricsContainer
from danswer.search.models import SearchRequest
from danswer.search.pipeline import SearchPipeline
from danswer.search.utils import chunks_or_sections_to_search_docs
from danswer.secondary_llm_flows.answer_validation import get_answer_validity
from danswer.secondary_llm_flows.query_expansion import thread_based_query_rephrase
from danswer.server.query_and_chat.models import ChatMessageDetail
from danswer.server.utils import get_json_line
from danswer.utils.logger import setup_logger
from danswer.utils.timing import log_generator_function_time

logger = setup_logger()

AnswerObjectIterator = Iterator[
    QueryRephrase
    | QADocsResponse
    | LLMRelevanceFilterResponse
    | DanswerAnswerPiece
    | DanswerQuotes
    | DanswerContexts
    | StreamingError
    | ChatMessageDetail
    | CitationInfo
]


def stream_answer_objects(
    query_req: DirectQARequest,
    user: User | None,
    # These need to be passed in because in Web UI one shot flow,
    # we can have much more document as there is no history.
    # For Slack flow, we need to save more tokens for the thread context
    max_document_tokens: int | None,
    max_history_tokens: int | None,
    db_session: Session,
    # Needed to translate persona num_chunks to tokens to the LLM
    default_num_chunks: float = MAX_CHUNKS_FED_TO_CHAT,
    timeout: int = QA_TIMEOUT,
    bypass_acl: bool = False,
    use_citations: bool = False,
    retrieval_metrics_callback: Callable[[RetrievalMetricsContainer], None]
    | None = None,
    rerank_metrics_callback: Callable[[RerankMetricsContainer], None] | None = None,
) -> AnswerObjectIterator:
    """Streams in order:
    1. [always] Retrieved documents, stops flow if nothing is found
    2. [conditional] LLM selected chunk indices if LLM chunk filtering is turned on
    3. [always] A set of streamed DanswerAnswerPiece and DanswerQuotes at the end
                or an error anywhere along the line if something fails
    4. [always] Details on the final AI response message that is created
    """
    user_id = user.id if user is not None else None
    query_msg = query_req.messages[-1]
    history = query_req.messages[:-1]

    chat_session = create_chat_session(
        db_session=db_session,
        description="",  # One shot queries don't need naming as it's never displayed
        user_id=user_id,
        persona_id=query_req.persona_id,
        one_shot=True,
    )

    llm_tokenizer = get_default_llm_token_encode()

    # Create a chat session which will just store the root message, the query, and the AI response
    root_message = get_or_create_root_message(
        chat_session_id=chat_session.id, db_session=db_session
    )

    history_str = combine_message_thread(
        messages=history, max_tokens=max_history_tokens
    )

    rephrased_query = thread_based_query_rephrase(
        user_query=query_msg.message,
        history_str=history_str,
    )
    # Given back ahead of the documents for latency reasons
    # In chat flow it's given back along with the documents
    yield QueryRephrase(rephrased_query=rephrased_query)

    search_pipeline = SearchPipeline(
        search_request=SearchRequest(
            query=rephrased_query,
            human_selected_filters=query_req.retrieval_options.filters,
            persona=chat_session.persona,
            offset=query_req.retrieval_options.offset,
            limit=query_req.retrieval_options.limit,
            skip_rerank=query_req.skip_rerank,
            skip_llm_chunk_filter=query_req.skip_llm_chunk_filter,
            chunks_above=query_req.chunks_above,
            chunks_below=query_req.chunks_below,
            full_doc=query_req.full_doc,
        ),
        user=user,
        db_session=db_session,
        bypass_acl=bypass_acl,
        retrieval_metrics_callback=retrieval_metrics_callback,
        rerank_metrics_callback=rerank_metrics_callback,
    )

    # First fetch and return the top chunks so the user can immediately see some results
    top_sections = search_pipeline.reranked_sections
    top_docs = chunks_or_sections_to_search_docs(top_sections)

    reference_db_search_docs = [
        create_db_search_doc(server_search_doc=top_doc, db_session=db_session)
        for top_doc in top_docs
    ]

    response_docs = [
        translate_db_search_doc_to_server_search_doc(db_search_doc)
        for db_search_doc in reference_db_search_docs
    ]

    initial_response = QADocsResponse(
        rephrased_query=rephrased_query,
        top_documents=response_docs,
        predicted_flow=search_pipeline.predicted_flow,
        predicted_search=search_pipeline.predicted_search_type,
        applied_source_filters=search_pipeline.search_query.filters.source_type,
        applied_time_cutoff=search_pipeline.search_query.filters.time_cutoff,
        recency_bias_multiplier=search_pipeline.search_query.recency_bias_multiplier,
    )
    yield initial_response

    # Yield the list of LLM selected chunks for showing the LLM selected icons in the UI
    llm_relevance_filtering_response = LLMRelevanceFilterResponse(
        relevant_chunk_indices=search_pipeline.relevant_chunk_indices
    )
    yield llm_relevance_filtering_response

    prompt = None
    if query_req.prompt_id is not None:
        prompt = get_prompt_by_id(
            prompt_id=query_req.prompt_id, user=user, db_session=db_session
        )
    if prompt is None:
        if not chat_session.persona.prompts:
            raise RuntimeError(
                "Persona does not have any prompts - this should never happen"
            )
        prompt = chat_session.persona.prompts[0]

    # Create the first User query message
    new_user_message = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=root_message,
        prompt_id=query_req.prompt_id,
        message=query_msg.message,
        token_count=len(llm_tokenizer(query_msg.message)),
        message_type=MessageType.USER,
        db_session=db_session,
        commit=True,
    )

    answer_config = AnswerStyleConfig(
        citation_config=CitationConfig() if use_citations else None,
        quotes_config=QuotesConfig() if not use_citations else None,
        document_pruning_config=DocumentPruningConfig(
            max_chunks=int(
                chat_session.persona.num_chunks
                if chat_session.persona.num_chunks is not None
                else default_num_chunks
            ),
            max_tokens=max_document_tokens,
            use_sections=search_pipeline.ran_merge_chunk,
        ),
    )
    answer = Answer(
        question=query_msg.message,
        docs=[llm_doc_from_inference_section(section) for section in top_sections],
        answer_style_config=answer_config,
        prompt_config=PromptConfig.from_model(prompt),
        llm_config=LLMConfig.from_persona(chat_session.persona),
        doc_relevance_list=search_pipeline.section_relevance_list,
        single_message_history=history_str,
        timeout=timeout,
    )
    yield from answer.processed_streamed_output

    reference_db_search_docs = [
        create_db_search_doc(server_search_doc=top_doc, db_session=db_session)
        for top_doc in top_docs
    ]

    # Saving Gen AI answer and responding with message info
    gen_ai_response_message = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=new_user_message,
        prompt_id=query_req.prompt_id,
        message=answer.llm_answer,
        token_count=len(llm_tokenizer(answer.llm_answer)),
        message_type=MessageType.ASSISTANT,
        error=None,
        reference_docs=reference_db_search_docs,
        db_session=db_session,
        commit=True,
    )

    msg_detail_response = translate_db_message_to_chat_message_detail(
        gen_ai_response_message
    )

    yield msg_detail_response


@log_generator_function_time()
def stream_search_answer(
    query_req: DirectQARequest,
    user: User | None,
    max_document_tokens: int | None,
    max_history_tokens: int | None,
) -> Iterator[str]:
    with get_session_context_manager() as session:
        objects = stream_answer_objects(
            query_req=query_req,
            user=user,
            max_document_tokens=max_document_tokens,
            max_history_tokens=max_history_tokens,
            db_session=session,
        )
        for obj in objects:
            yield get_json_line(obj.dict())


def get_search_answer(
    query_req: DirectQARequest,
    user: User | None,
    max_document_tokens: int | None,
    max_history_tokens: int | None,
    db_session: Session,
    answer_generation_timeout: int = QA_TIMEOUT,
    enable_reflexion: bool = False,
    bypass_acl: bool = False,
    use_citations: bool = False,
    retrieval_metrics_callback: Callable[[RetrievalMetricsContainer], None]
    | None = None,
    rerank_metrics_callback: Callable[[RerankMetricsContainer], None] | None = None,
) -> OneShotQAResponse:
    """Collects the streamed one shot answer responses into a single object"""
    qa_response = OneShotQAResponse()

    results = stream_answer_objects(
        query_req=query_req,
        user=user,
        max_document_tokens=max_document_tokens,
        max_history_tokens=max_history_tokens,
        db_session=db_session,
        bypass_acl=bypass_acl,
        use_citations=use_citations,
        timeout=answer_generation_timeout,
        retrieval_metrics_callback=retrieval_metrics_callback,
        rerank_metrics_callback=rerank_metrics_callback,
    )

    answer = ""
    for packet in results:
        if isinstance(packet, QueryRephrase):
            qa_response.rephrase = packet.rephrased_query
        if isinstance(packet, DanswerAnswerPiece) and packet.answer_piece:
            answer += packet.answer_piece
        elif isinstance(packet, QADocsResponse):
            qa_response.docs = packet
        elif isinstance(packet, LLMRelevanceFilterResponse):
            qa_response.llm_chunks_indices = packet.relevant_chunk_indices
        elif isinstance(packet, DanswerQuotes):
            qa_response.quotes = packet
        elif isinstance(packet, CitationInfo):
            if qa_response.citations:
                qa_response.citations.append(packet)
            else:
                qa_response.citations = [packet]
        elif isinstance(packet, DanswerContexts):
            qa_response.contexts = packet
        elif isinstance(packet, StreamingError):
            qa_response.error_msg = packet.error
        elif isinstance(packet, ChatMessageDetail):
            qa_response.chat_message_id = packet.message_id

    if answer:
        qa_response.answer = answer

    if enable_reflexion:
        # Because follow up messages are explicitly tagged, we don't need to verify the answer
        if len(query_req.messages) == 1:
            first_query = query_req.messages[0].message
            qa_response.answer_valid = get_answer_validity(first_query, answer)
        else:
            qa_response.answer_valid = True

    if use_citations and qa_response.answer and qa_response.citations:
        # Reorganize citation nums to be in the same order as the answer
        qa_response.answer, qa_response.citations = reorganize_citations(
            qa_response.answer, qa_response.citations
        )

    return qa_response
