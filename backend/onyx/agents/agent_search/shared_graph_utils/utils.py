import os
import re
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from typing import cast
from typing import Literal
from typing import TypedDict
from uuid import UUID

from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langgraph.types import StreamWriter
from sqlalchemy.orm import Session

from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.models import GraphInputs
from onyx.agents.agent_search.models import GraphPersistence
from onyx.agents.agent_search.models import GraphSearchConfig
from onyx.agents.agent_search.models import GraphTooling
from onyx.agents.agent_search.shared_graph_utils.models import BaseMessage_Content
from onyx.agents.agent_search.shared_graph_utils.models import (
    EntityRelationshipTermExtraction,
)
from onyx.agents.agent_search.shared_graph_utils.models import PersonaPromptExpressions
from onyx.agents.agent_search.shared_graph_utils.models import (
    StructuredSubquestionDocuments,
)
from onyx.agents.agent_search.shared_graph_utils.models import SubQuestionAnswerResults
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_section_list,
)
from onyx.chat.models import AnswerPacket
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import CitationConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.chat.models import PromptConfig
from onyx.chat.models import SectionRelevancePiece
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.models import StreamType
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.agent_configs import AGENT_MAX_TOKENS_HISTORY_SUMMARY
from onyx.configs.agent_configs import (
    AGENT_TIMEOUT_CONNECT_LLM_HISTORY_SUMMARY_GENERATION,
)
from onyx.configs.agent_configs import AGENT_TIMEOUT_LLM_HISTORY_SUMMARY_GENERATION
from onyx.configs.chat_configs import CHAT_TARGET_CHUNK_PERCENTAGE
from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.configs.constants import DISPATCH_SEP_CHAR
from onyx.configs.constants import FORMAT_DOCS_SEPARATOR
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import RetrievalDetails
from onyx.context.search.models import SearchRequest
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.persona import get_persona_by_id
from onyx.db.persona import Persona
from onyx.llm.chat_llm import LLMRateLimitError
from onyx.llm.chat_llm import LLMTimeoutError
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.prompts.agent_search import (
    ASSISTANT_SYSTEM_PROMPT_DEFAULT,
)
from onyx.prompts.agent_search import (
    ASSISTANT_SYSTEM_PROMPT_PERSONA,
)
from onyx.prompts.agent_search import (
    HISTORY_CONTEXT_SUMMARY_PROMPT,
)
from onyx.prompts.prompt_utils import handle_onyx_date_awareness
from onyx.tools.force import ForceUseTool
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_constructor import SearchToolConfig
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.utils import explicit_tool_calling_supported
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


# Post-processing
def format_docs(docs: Sequence[InferenceSection]) -> str:
    formatted_doc_list = []

    for doc_num, doc in enumerate(docs):
        title: str | None = doc.center_chunk.title
        metadata: dict[str, str | list[str]] | None = (
            doc.center_chunk.metadata if doc.center_chunk.metadata else None
        )

        doc_str = f"**Document: D{doc_num + 1}**"
        if title:
            doc_str += f"\nTitle: {title}"
        if metadata:
            metadata_str = ""
            for key, value in metadata.items():
                if isinstance(value, str):
                    metadata_str += f" - {key}: {value}"
                elif isinstance(value, list):
                    metadata_str += f" - {key}: {', '.join(value)}"
            doc_str += f"\nMetadata: {metadata_str}"
        doc_str += f"\nContent:\n{doc.combined_content}"

        formatted_doc_list.append(doc_str)

    return FORMAT_DOCS_SEPARATOR.join(formatted_doc_list)


def format_entity_term_extraction(
    entity_term_extraction_dict: EntityRelationshipTermExtraction,
) -> str:
    entities = entity_term_extraction_dict.entities
    terms = entity_term_extraction_dict.terms
    relationships = entity_term_extraction_dict.relationships

    entity_strs = ["\nEntities:\n"]
    for entity in entities:
        entity_str = f"{entity.entity_name} ({entity.entity_type})"
        entity_strs.append(entity_str)

    entity_str = "\n - ".join(entity_strs)

    relationship_strs = ["\n\nRelationships:\n"]
    for relationship in relationships:
        relationship_name = relationship.relationship_name
        relationship_type = relationship.relationship_type
        relationship_entities = relationship.relationship_entities
        relationship_str = (
            f"""{relationship_name} ({relationship_type}): {relationship_entities}"""
        )
        relationship_strs.append(relationship_str)

    relationship_str = "\n - ".join(relationship_strs)

    term_strs = ["\n\nTerms:\n"]
    for term in terms:
        term_str = f"{term.term_name} ({term.term_type}): similar to {', '.join(term.term_similar_to)}"
        term_strs.append(term_str)

    term_str = "\n - ".join(term_strs)

    return "\n".join(entity_strs + relationship_strs + term_strs)


def get_test_config(
    db_session: Session,
    primary_llm: LLM,
    fast_llm: LLM,
    search_request: SearchRequest,
    use_agentic_search: bool = True,
) -> GraphConfig:
    persona = get_persona_by_id(DEFAULT_PERSONA_ID, None, db_session)
    document_pruning_config = DocumentPruningConfig(
        max_chunks=int(
            persona.num_chunks
            if persona.num_chunks is not None
            else MAX_CHUNKS_FED_TO_CHAT
        ),
        max_window_percentage=CHAT_TARGET_CHUNK_PERCENTAGE,
    )

    answer_style_config = AnswerStyleConfig(
        citation_config=CitationConfig(
            # The docs retrieved by this flow are already relevance-filtered
            all_docs_useful=True
        ),
        document_pruning_config=document_pruning_config,
        structured_response_format=None,
    )

    search_tool_config = SearchToolConfig(
        answer_style_config=answer_style_config,
        document_pruning_config=document_pruning_config,
        retrieval_options=RetrievalDetails(),  # may want to set dedupe_docs=True
        rerank_settings=None,  # Can use this to change reranking model
        selected_sections=None,
        latest_query_files=None,
        bypass_acl=False,
    )

    prompt_config = PromptConfig.from_model(persona.prompts[0])

    search_tool = SearchTool(
        db_session=db_session,
        user=None,
        persona=persona,
        retrieval_options=search_tool_config.retrieval_options,
        prompt_config=prompt_config,
        llm=primary_llm,
        fast_llm=fast_llm,
        pruning_config=search_tool_config.document_pruning_config,
        answer_style_config=search_tool_config.answer_style_config,
        selected_sections=search_tool_config.selected_sections,
        chunks_above=search_tool_config.chunks_above,
        chunks_below=search_tool_config.chunks_below,
        full_doc=search_tool_config.full_doc,
        evaluation_type=(
            LLMEvaluationType.BASIC
            if persona.llm_relevance_filter
            else LLMEvaluationType.SKIP
        ),
        rerank_settings=search_tool_config.rerank_settings,
        bypass_acl=search_tool_config.bypass_acl,
    )

    graph_inputs = GraphInputs(
        persona=search_request.persona,
        rerank_settings=search_tool_config.rerank_settings,
        prompt_builder=AnswerPromptBuilder(
            user_message=HumanMessage(content=search_request.query),
            message_history=[],
            llm_config=primary_llm.config,
            raw_user_query=search_request.query,
            raw_user_uploaded_files=[],
        ),
        structured_response_format=answer_style_config.structured_response_format,
    )

    using_tool_calling_llm = explicit_tool_calling_supported(
        primary_llm.config.model_provider, primary_llm.config.model_name
    )
    graph_tooling = GraphTooling(
        primary_llm=primary_llm,
        fast_llm=fast_llm,
        search_tool=search_tool,
        tools=[search_tool],
        force_use_tool=ForceUseTool(force_use=False, tool_name=""),
        using_tool_calling_llm=using_tool_calling_llm,
    )

    chat_session_id = (
        os.environ.get("ONYX_AS_CHAT_SESSION_ID")
        or "00000000-0000-0000-0000-000000000000"
    )
    assert (
        chat_session_id is not None
    ), "ONYX_AS_CHAT_SESSION_ID must be set for backend tests"
    graph_persistence = GraphPersistence(
        db_session=db_session,
        chat_session_id=UUID(chat_session_id),
        message_id=1,
    )

    search_behavior_config = GraphSearchConfig(
        use_agentic_search=use_agentic_search,
        skip_gen_ai_answer_generation=False,
        allow_refinement=True,
    )
    graph_config = GraphConfig(
        inputs=graph_inputs,
        tooling=graph_tooling,
        persistence=graph_persistence,
        behavior=search_behavior_config,
    )

    return graph_config


def get_persona_agent_prompt_expressions(
    persona: Persona | None,
) -> PersonaPromptExpressions:
    if persona is None or len(persona.prompts) == 0:
        # TODO base_prompt should be None, but no time to properly fix
        return PersonaPromptExpressions(
            contextualized_prompt=ASSISTANT_SYSTEM_PROMPT_DEFAULT, base_prompt=""
        )

    # Only a 1:1 mapping between personas and prompts currently
    prompt = persona.prompts[0]
    prompt_config = PromptConfig.from_model(prompt)
    datetime_aware_system_prompt = handle_onyx_date_awareness(
        prompt_str=prompt_config.system_prompt,
        prompt_config=prompt_config,
        add_additional_info_if_no_tag=prompt.datetime_aware,
    )

    return PersonaPromptExpressions(
        contextualized_prompt=ASSISTANT_SYSTEM_PROMPT_PERSONA.format(
            persona_prompt=datetime_aware_system_prompt
        ),
        base_prompt=datetime_aware_system_prompt,
    )


def make_question_id(level: int, question_num: int) -> str:
    return f"{level}_{question_num}"


def parse_question_id(question_id: str) -> tuple[int, int]:
    level, question_num = question_id.split("_")
    return int(level), int(question_num)


def _dispatch_nonempty(
    content: str, dispatch_event: Callable[[str, int], None], sep_num: int
) -> None:
    """
    Dispatch a content string if it is not empty using the given callback.
    This function is used in the context of dispatching some arbitrary number
    of similar objects which are separated by a separator during the LLM stream.
    The callback expects a sep_num denoting which object is being dispatched; these
    numbers go from 1 to however many strings the LLM decides to stream.
    """
    if content != "":
        dispatch_event(content, sep_num)


def dispatch_separated(
    tokens: Iterator[BaseMessage],
    dispatch_event: Callable[[str, int], None],
    sep_callback: Callable[[int], None] | None = None,
    sep: str = DISPATCH_SEP_CHAR,
) -> list[BaseMessage_Content]:
    num = 1
    accumulated_tokens = ""
    streamed_tokens: list[BaseMessage_Content] = []
    for token in tokens:
        accumulated_tokens += cast(str, token.content)
        content = cast(str, token.content)
        if sep in content:
            sub_question_parts = content.split(sep)
            _dispatch_nonempty(sub_question_parts[0], dispatch_event, num)

            if sep_callback:
                sep_callback(num)

            num += 1
            _dispatch_nonempty(
                "".join(sub_question_parts[1:]).strip(), dispatch_event, num
            )
        else:
            _dispatch_nonempty(content, dispatch_event, num)
        streamed_tokens.append(content)

    if sep_callback:
        sep_callback(num)

    return streamed_tokens


def dispatch_main_answer_stop_info(level: int, writer: StreamWriter) -> None:
    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type=StreamType.MAIN_ANSWER,
        level=level,
    )
    write_custom_event("stream_finished", stop_event, writer)


def retrieve_search_docs(
    search_tool: SearchTool, question: str
) -> list[InferenceSection]:
    retrieved_docs: list[InferenceSection] = []

    # new db session to avoid concurrency issues
    with get_session_with_current_tenant() as db_session:
        for tool_response in search_tool.run(
            query=question,
            override_kwargs=SearchToolOverrideKwargs(
                force_no_rerank=True,
                alternate_db_session=db_session,
                retrieved_sections_callback=None,
                skip_query_analysis=False,
            ),
        ):
            # get retrieved docs to send to the rest of the graph
            if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                response = cast(SearchResponseSummary, tool_response.response)
                retrieved_docs = response.top_sections
                break

    return retrieved_docs


def get_answer_citation_ids(answer_str: str) -> list[int]:
    """
    Extract citation numbers of format [D<number>] from the answer string.
    """
    citation_ids = re.findall(r"\[D(\d+)\]", answer_str)
    return list(set([(int(id) - 1) for id in citation_ids]))


def summarize_history(
    history: str, question: str, persona_specification: str | None, llm: LLM
) -> str:
    history_context_prompt = remove_document_citations(
        HISTORY_CONTEXT_SUMMARY_PROMPT.format(
            persona_specification=persona_specification,
            question=question,
            history=history,
        )
    )

    try:
        history_response = run_with_timeout(
            AGENT_TIMEOUT_LLM_HISTORY_SUMMARY_GENERATION,
            llm.invoke,
            history_context_prompt,
            timeout_override=AGENT_TIMEOUT_CONNECT_LLM_HISTORY_SUMMARY_GENERATION,
            max_tokens=AGENT_MAX_TOKENS_HISTORY_SUMMARY,
        )
    except (LLMTimeoutError, TimeoutError):
        logger.error("LLM Timeout Error - summarize history")
        return (
            history  # this is what is done at this point anyway, so we default to this
        )
    except LLMRateLimitError:
        logger.error("LLM Rate Limit Error - summarize history")
        return (
            history  # this is what is done at this point anyway, so we default to this
        )

    assert isinstance(history_response.content, str)

    return history_response.content


# taken from langchain_core.runnables.schema
# we don't use the one from their library because
# it includes ids they generate
class CustomStreamEvent(TypedDict):
    # Overwrite the event field to be more specific.
    event: Literal["on_custom_event"]  # type: ignore[misc]
    """The event type."""
    name: str
    """User defined name for the event."""
    data: Any
    """The data associated with the event. Free form and can be anything."""


def write_custom_event(
    name: str, event: AnswerPacket, stream_writer: StreamWriter
) -> None:
    stream_writer(CustomStreamEvent(event="on_custom_event", name=name, data=event))


def relevance_from_docs(
    relevant_docs: list[InferenceSection],
) -> list[SectionRelevancePiece]:
    return [
        SectionRelevancePiece(
            relevant=True,
            content=doc.center_chunk.content,
            document_id=doc.center_chunk.document_id,
            chunk_id=doc.center_chunk.chunk_id,
        )
        for doc in relevant_docs
    ]


def get_langgraph_node_log_string(
    graph_component: str,
    node_name: str,
    node_start_time: datetime,
    result: str | None = None,
) -> str:
    duration = datetime.now() - node_start_time
    results_str = "" if result is None else f" -- Result: {result}"
    return f"{node_start_time} -- {graph_component} - {node_name} -- Time taken: {duration}{results_str}"


def remove_document_citations(text: str) -> str:
    """
    Removes citation expressions of format '[[D1]]()' from text.
    The number after D can vary.

    Args:
        text: Input text containing citations

    Returns:
        Text with citations removed
    """
    # Pattern explanation:
    # \[(?:D|Q)?\d+\]  matches:
    #   \[   - literal [ character
    #   (?:D|Q)?  - optional D or Q character
    #   \d+  - one or more digits
    #   \]   - literal ] character
    return re.sub(r"\[(?:D|Q)?\d+\]", "", text)


def get_deduplicated_structured_subquestion_documents(
    sub_question_results: list[SubQuestionAnswerResults],
) -> StructuredSubquestionDocuments:
    """
    Extract and deduplicate all cited documents from sub-question results.

    Args:
        sub_question_results: List of sub-question results containing cited documents

    Returns:
        Deduplicated list of cited documents
    """
    cited_docs = [
        doc for result in sub_question_results for doc in result.cited_documents
    ]
    context_docs = [
        doc for result in sub_question_results for doc in result.context_documents
    ]
    return StructuredSubquestionDocuments(
        cited_documents=dedup_inference_section_list(cited_docs),
        context_documents=dedup_inference_section_list(context_docs),
    )


def _should_restrict_tokens(llm_config: LLMConfig) -> bool:
    return not (
        llm_config.model_provider == "openai" and llm_config.model_name.startswith("o")
    )
