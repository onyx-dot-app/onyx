import ast
import json
import re
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import cast
from uuid import UUID

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.models import (
    EntityRelationshipTermExtraction,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import DATE_PROMPT
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import CitationConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.chat.models import PromptConfig
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.chat_configs import CHAT_TARGET_CHUNK_PERCENTAGE
from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import RetrievalDetails
from onyx.context.search.models import SearchRequest
from onyx.db.engine import get_session_context_manager
from onyx.db.persona import get_persona_by_id
from onyx.db.persona import Persona
from onyx.llm.interfaces import LLM
from onyx.tools.force import ForceUseTool
from onyx.tools.tool_constructor import SearchToolConfig
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_tool import SearchTool


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text to single spaces and strip leading/trailing whitespace."""
    import re

    return re.sub(r"\s+", " ", text.strip())


# Post-processing
def format_docs(docs: Sequence[InferenceSection]) -> str:
    formatted_doc_list = []

    for doc_nr, doc in enumerate(docs):
        formatted_doc_list.append(f"Document D{doc_nr + 1}:\n{doc.combined_content}")

    return "\n\n".join(formatted_doc_list)


def format_docs_content_flat(docs: Sequence[InferenceSection]) -> str:
    formatted_doc_list = []

    for _, doc in enumerate(docs):
        formatted_doc_list.append(f"\n...{doc.combined_content}\n")

    return "\n\n".join(formatted_doc_list)


def clean_and_parse_list_string(json_string: str) -> list[dict]:
    # Remove any prefixes/labels before the actual JSON content
    json_string = re.sub(r"^.*?(?=\[)", "", json_string, flags=re.DOTALL)

    # Remove markdown code block markers and any newline prefixes
    cleaned_string = re.sub(r"```json\n|\n```", "", json_string)
    cleaned_string = cleaned_string.replace("\\n", " ").replace("\n", " ")
    cleaned_string = " ".join(cleaned_string.split())

    # Try parsing with json.loads first, fall back to ast.literal_eval
    try:
        return json.loads(cleaned_string)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(cleaned_string)
        except (ValueError, SyntaxError) as e:
            raise ValueError(f"Failed to parse JSON string: {cleaned_string}") from e


def clean_and_parse_json_string(json_string: str) -> dict[str, Any]:
    # Remove markdown code block markers and any newline prefixes
    cleaned_string = re.sub(r"```json\n|\n```", "", json_string)
    cleaned_string = cleaned_string.replace("\\n", " ").replace("\n", " ")
    cleaned_string = " ".join(cleaned_string.split())
    # Parse the cleaned string into a Python dictionary
    return json.loads(cleaned_string)


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


def _format_time_delta(time: timedelta) -> str:
    seconds_from_start = f"{((time).seconds):03d}"
    microseconds_from_start = f"{((time).microseconds):06d}"
    return f"{seconds_from_start}.{microseconds_from_start}"


def generate_log_message(
    message: str,
    node_start_time: datetime,
    graph_start_time: datetime | None = None,
) -> str:
    current_time = datetime.now()

    if graph_start_time is not None:
        graph_time_str = _format_time_delta(current_time - graph_start_time)
    else:
        graph_time_str = "N/A"

    node_time_str = _format_time_delta(current_time - node_start_time)

    return f"{graph_time_str} ({node_time_str} s): {message}"


def get_test_config(
    db_session: Session,
    primary_llm: LLM,
    fast_llm: LLM,
    search_request: SearchRequest,
    use_agentic_search: bool = True,
) -> tuple[AgentSearchConfig, SearchTool]:
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

    config = AgentSearchConfig(
        search_request=search_request,
        primary_llm=primary_llm,
        fast_llm=fast_llm,
        search_tool=search_tool,
        force_use_tool=ForceUseTool(force_use=False, tool_name=""),
        prompt_builder=AnswerPromptBuilder(
            user_message=HumanMessage(content=search_request.query),
            message_history=[],
            llm_config=primary_llm.config,
            raw_user_query=search_request.query,
            raw_user_uploaded_files=[],
        ),
        # chat_session_id=UUID("123e4567-e89b-12d3-a456-426614174000"),
        chat_session_id=UUID("edda10d5-6cef-45d8-acfb-39317552a1f4"),  # Joachim
        # chat_session_id=UUID("d1acd613-2692-4bc3-9d65-c6d3da62e58e"),  # Evan
        message_id=1,
        use_persistence=True,
        db_session=db_session,
        tools=[search_tool],
        use_agentic_search=use_agentic_search,
    )

    return config, search_tool


def get_persona_prompt(persona: Persona | None) -> str:
    if persona is None:
        return ""
    else:
        return "\n".join([x.system_prompt for x in persona.prompts])


def make_question_id(level: int, question_nr: int) -> str:
    return f"{level}_{question_nr}"


def parse_question_id(question_id: str) -> tuple[int, int]:
    level, question_nr = question_id.split("_")
    return int(level), int(question_nr)


def _dispatch_nonempty(
    content: str, dispatch_event: Callable[[str, int], None], num: int
) -> None:
    if content != "":
        dispatch_event(content, num)


def dispatch_separated(
    token_itr: Iterator[BaseMessage],
    dispatch_event: Callable[[str, int], None],
    sep: str = "\n",
) -> list[str | list[str | dict[str, Any]]]:
    num = 1
    streamed_tokens: list[str | list[str | dict[str, Any]]] = [""]
    for message in token_itr:
        content = cast(str, message.content)
        if sep in content:
            sub_question_parts = content.split(sep)
            _dispatch_nonempty(sub_question_parts[0], dispatch_event, num)
            num += 1
            _dispatch_nonempty(
                "".join(sub_question_parts[1:]).strip(), dispatch_event, num
            )
        else:
            _dispatch_nonempty(content, dispatch_event, num)
        streamed_tokens.append(content)

    return streamed_tokens


def dispatch_main_answer_stop_info(level: int) -> None:
    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type="main_answer",
        level=level,
    )
    dispatch_custom_event("stream_finished", stop_event)


def get_today_prompt() -> str:
    return DATE_PROMPT.format(date=datetime.now().strftime("%A, %B %d, %Y"))


def retrieve_search_docs(
    search_tool: SearchTool, question: str
) -> list[InferenceSection]:
    retrieved_docs: list[InferenceSection] = []

    # new db session to avoid concurrency issues
    with get_session_context_manager() as db_session:
        for tool_response in search_tool.run(
            query=question,
            force_no_rerank=True,
            alternate_db_session=db_session,
        ):
            # get retrieved docs to send to the rest of the graph
            if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                response = cast(SearchResponseSummary, tool_response.response)
                retrieved_docs = response.top_sections
                break

    return retrieved_docs
