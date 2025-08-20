import re
from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.agents.agent_search.dr.constants import AVERAGE_TOOL_COSTS
from onyx.agents.agent_search.dr.constants import MAX_CHAT_HISTORY_MESSAGES
from onyx.agents.agent_search.dr.dr_prompt_builder import (
    get_dr_prompt_orchestration_templates,
)
from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.enums import ResearchAnswerPurpose
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import ClarificationGenerationResponse
from onyx.agents.agent_search.dr.models import DRPromptPurpose
from onyx.agents.agent_search.dr.models import OrchestrationClarificationInfo
from onyx.agents.agent_search.dr.models import OrchestratorTool
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationSetup
from onyx.agents.agent_search.dr.utils import get_chat_history_string
from onyx.agents.agent_search.dr.utils import update_db_session_with_messages
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.llm import stream_llm_answer
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import run_with_timeout
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.agents.agent_search.utils import create_question_prompt
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import DocumentSourceDescription
from onyx.configs.constants import TMP_DRALPHA_PERSONA_NAME
from onyx.db.connector import fetch_unique_document_sources
from onyx.kg.utils.extraction_utils import get_entity_types_str
from onyx.kg.utils.extraction_utils import get_relationship_types_str
from onyx.prompts.dr_prompts import DECISION_PROMPT_W_TOOL_CALLING
from onyx.prompts.dr_prompts import DECISION_PROMPT_WO_TOOL_CALLING
from onyx.prompts.dr_prompts import DEFAULT_DR_SYSTEM_PROMPT
from onyx.prompts.dr_prompts import EVAL_SYSTEM_PROMPT_W_TOOL_CALLING
from onyx.prompts.dr_prompts import EVAL_SYSTEM_PROMPT_WO_TOOL_CALLING
from onyx.prompts.dr_prompts import GENERAL_DR_ANSWER_PROMPT
from onyx.prompts.dr_prompts import TOOL_DESCRIPTION
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    InternetSearchTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _format_tool_name(tool_name: str) -> str:
    """Convert tool name to LLM-friendly format."""
    name = tool_name.replace(" ", "_")
    # take care of camel case like GetAPIKey -> GET_API_KEY for LLM readability
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    return name.upper()


def _get_available_tools(
    graph_config: GraphConfig,
    kg_enabled: bool,
    active_source_types: list[DocumentSource],
) -> dict[str, OrchestratorTool]:

    available_tools: dict[str, OrchestratorTool] = {}

    kg_enabled = graph_config.behavior.kg_config_settings.KG_ENABLED
    persona = graph_config.inputs.persona

    if persona:
        include_kg = persona.name == TMP_DRALPHA_PERSONA_NAME and kg_enabled
    else:
        include_kg = False

    for tool in graph_config.tooling.tools:
        tool_info = OrchestratorTool(
            tool_id=tool.id,
            name=tool.name,
            llm_path=_format_tool_name(tool.name),
            path=DRPath.GENERIC_TOOL,
            description=tool.description,
            metadata={},
            cost=1.0,
            tool_object=tool,
        )

        if isinstance(tool, CustomTool):
            # tool_info.metadata["summary_signature"] = CUSTOM_TOOL_RESPONSE_ID
            pass
        elif isinstance(tool, InternetSearchTool):
            # tool_info.metadata["summary_signature"] = (
            #     INTERNET_SEARCH_RESPONSE_SUMMARY_ID
            # )
            tool_info.llm_path = DRPath.INTERNET_SEARCH.value
            tool_info.path = DRPath.INTERNET_SEARCH
        elif isinstance(tool, SearchTool) and len(active_source_types) > 0:
            # tool_info.metadata["summary_signature"] = SEARCH_RESPONSE_SUMMARY_ID
            tool_info.llm_path = DRPath.INTERNAL_SEARCH.value
            tool_info.path = DRPath.INTERNAL_SEARCH
        elif (
            isinstance(tool, KnowledgeGraphTool)
            and include_kg
            and len(active_source_types) > 0
        ):
            tool_info.llm_path = DRPath.KNOWLEDGE_GRAPH.value
            tool_info.path = DRPath.KNOWLEDGE_GRAPH
        elif isinstance(tool, ImageGenerationTool):
            tool_info.llm_path = DRPath.IMAGE_GENERATION.value
            tool_info.path = DRPath.IMAGE_GENERATION
        else:
            logger.warning(
                f"Tool {tool.name} ({type(tool)}) is not supported/available"
            )
            continue

        tool_info.description = TOOL_DESCRIPTION.get(tool_info.path, tool.description)
        tool_info.cost = AVERAGE_TOOL_COSTS[tool_info.path]

        # TODO: handle custom tools with same name as other tools (e.g., CLOSER)
        available_tools[tool_info.llm_path] = tool_info

    # make sure KG isn't enabled without internal search
    if (
        DRPath.KNOWLEDGE_GRAPH.value in available_tools
        and DRPath.INTERNAL_SEARCH.value not in available_tools
    ):
        raise ValueError(
            "The Knowledge Graph is not supported without internal search tool"
        )

    # add CLOSER tool, which is always available
    available_tools[DRPath.CLOSER.value] = OrchestratorTool(
        tool_id=-1,
        name="closer",
        llm_path=DRPath.CLOSER.value,
        path=DRPath.CLOSER,
        description=TOOL_DESCRIPTION[DRPath.CLOSER],
        metadata={},
        cost=0.0,
        tool_object=None,
    )

    return available_tools


def _get_existing_clarification_request(
    graph_config: GraphConfig,
) -> tuple[OrchestrationClarificationInfo, str, str] | None:
    """
    Returns the clarification info, original question, and updated chat history if
    a clarification request and response exists, otherwise returns None.
    """
    # check for clarification request and response in message history
    previous_raw_messages = graph_config.inputs.prompt_builder.raw_message_history

    if len(previous_raw_messages) == 0 or (
        previous_raw_messages[-1].research_answer_purpose
        != ResearchAnswerPurpose.CLARIFICATION_REQUEST
    ):
        return None

    # get the clarification request and response
    previous_messages = graph_config.inputs.prompt_builder.message_history
    last_message = previous_raw_messages[-1].message

    clarification = OrchestrationClarificationInfo(
        clarification_question=last_message.strip(),
        clarification_response=graph_config.inputs.prompt_builder.raw_user_query,
    )
    original_question = graph_config.inputs.prompt_builder.raw_user_query
    chat_history_string = "(No chat history yet available)"

    # get the original user query and chat history string before the original query
    # e.g., if history = [user query, assistant clarification request, user clarification response],
    # previous_messages = [user query, assistant clarification request], we want the user query
    for i, message in enumerate(reversed(previous_messages), 1):
        if (
            isinstance(message, HumanMessage)
            and message.content
            and isinstance(message.content, str)
        ):
            original_question = message.content
            chat_history_string = (
                get_chat_history_string(
                    graph_config.inputs.prompt_builder.message_history[:-i],
                    MAX_CHAT_HISTORY_MESSAGES,
                )
                or "(No chat history yet available)"
            )
            break

    return clarification, original_question, chat_history_string


_ARTIFICIAL_ALL_ENCOMPASSING_TOOL = {
    "type": "function",
    "function": {
        "name": "run_any_knowledge_retrieval_and_any_action_tool",
        "description": "Use this tool to get any external information \
that is relevant to the question, or for any action to be taken.",
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The request to be made to the tool",
                },
            },
            "required": ["request"],
        },
    },
}


def clarifier(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> OrchestrationSetup:
    """
    Perform a quick search on the question as is and see whether a set of clarification
    questions is needed. For now this is based on the models
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])

    use_tool_calling_llm = graph_config.tooling.using_tool_calling_llm
    db_session = graph_config.persistence.db_session

    original_question = graph_config.inputs.prompt_builder.raw_user_query
    research_type = graph_config.behavior.research_type

    message_id = graph_config.persistence.message_id

    # get the connected tools and format for the Deep Research flow
    kg_enabled = graph_config.behavior.kg_config_settings.KG_ENABLED
    db_session = graph_config.persistence.db_session
    active_source_types = fetch_unique_document_sources(db_session)

    available_tools = _get_available_tools(
        graph_config, kg_enabled, active_source_types
    )

    all_entity_types = get_entity_types_str(active=True)
    all_relationship_types = get_relationship_types_str(active=True)

    # if not active_source_types:
    #    raise ValueError("No active source types found")

    active_source_types_descriptions = [
        DocumentSourceDescription[source_type] for source_type in active_source_types
    ]

    if graph_config.inputs.persona and len(graph_config.inputs.persona.prompts) > 0:
        assistant_system_prompt = (
            graph_config.inputs.persona.prompts[0].system_prompt
            or DEFAULT_DR_SYSTEM_PROMPT
        ) + "\n\n"
        if graph_config.inputs.persona.prompts[0].task_prompt:
            assistant_task_prompt = (
                "\n\nHere are more specifications from the user:\n\n"
                + graph_config.inputs.persona.prompts[0].task_prompt
            )
        else:
            assistant_task_prompt = ""

    else:
        assistant_system_prompt = DEFAULT_DR_SYSTEM_PROMPT + "\n\n"
        assistant_task_prompt = ""

    chat_history_string = (
        get_chat_history_string(
            graph_config.inputs.prompt_builder.message_history,
            MAX_CHAT_HISTORY_MESSAGES,
        )
        or "(No chat history yet available)"
    )

    if len(available_tools) == 1:
        # Closer is always there, therefore 'len(available_tools) == 1' above
        answer_prompt = GENERAL_DR_ANSWER_PROMPT.build(
            question=original_question, chat_history_string=chat_history_string
        )

        stream = graph_config.tooling.primary_llm.stream(
            prompt=create_question_prompt(
                assistant_system_prompt, answer_prompt + assistant_task_prompt
            ),
            tools=None,
            tool_choice=(None),
            structured_response_format=None,
        )

        full_response = process_llm_stream(
            messages=stream,
            should_stream_answer=True,
            writer=writer,
            ind=0,
            generate_final_answer=True,
            chat_message_id=str(graph_config.persistence.chat_session_id),
        )

        if isinstance(full_response.full_answer, str):
            full_answer = full_response.full_answer
        else:
            full_answer = None

        update_db_session_with_messages(
            db_session=db_session,
            chat_message_id=message_id,
            chat_session_id=str(graph_config.persistence.chat_session_id),
            is_agentic=graph_config.behavior.use_agentic_search,
            message=full_answer,
            update_parent_message=True,
            research_answer_purpose=ResearchAnswerPurpose.ANSWER,
        )

        db_session.commit()

        return OrchestrationSetup(
            original_question=original_question,
            chat_history_string="",
            tools_used=[DRPath.END.value],
            query_list=[],
            assistant_system_prompt=assistant_system_prompt,
            assistant_task_prompt=assistant_task_prompt,
        )

    elif not use_tool_calling_llm:
        decision_prompt = DECISION_PROMPT_WO_TOOL_CALLING.build(
            question=original_question, chat_history_string=chat_history_string
        )

        initial_decision_tokens, _, _ = run_with_timeout(
            80,
            lambda: stream_llm_answer(
                llm=graph_config.tooling.primary_llm,
                prompt=create_question_prompt(
                    assistant_system_prompt + EVAL_SYSTEM_PROMPT_WO_TOOL_CALLING,
                    decision_prompt + assistant_task_prompt,
                ),
                event_name="basic_response",
                writer=writer,
                agent_answer_level=0,
                agent_answer_question_num=0,
                agent_answer_type="agent_level_answer",
                timeout_override=60,
                max_tokens=None,
            ),
        )

        initial_decision_str = cast(str, merge_content(*initial_decision_tokens))

        if len(initial_decision_str.replace(" ", "")) > 0:
            return OrchestrationSetup(
                original_question=original_question,
                chat_history_string="",
                tools_used=[DRPath.END.value],
                query_list=[],
                assistant_system_prompt=assistant_system_prompt,
                assistant_task_prompt=assistant_task_prompt,
            )

    else:

        decision_prompt = DECISION_PROMPT_W_TOOL_CALLING.build(
            question=original_question, chat_history_string=chat_history_string
        )

        stream = graph_config.tooling.primary_llm.stream(
            prompt=create_question_prompt(
                assistant_system_prompt + EVAL_SYSTEM_PROMPT_W_TOOL_CALLING,
                decision_prompt + assistant_task_prompt,
            ),
            tools=([_ARTIFICIAL_ALL_ENCOMPASSING_TOOL]),
            tool_choice=(None),
            structured_response_format=graph_config.inputs.structured_response_format,
        )

        full_response = process_llm_stream(
            messages=stream,
            should_stream_answer=True,
            writer=writer,
            ind=0,
            generate_final_answer=True,
            chat_message_id=str(graph_config.persistence.chat_session_id),
        )

        if len(full_response.ai_message_chunk.tool_calls) == 0:

            if isinstance(full_response.full_answer, str):
                full_answer = full_response.full_answer
            else:
                full_answer = None

            update_db_session_with_messages(
                db_session=db_session,
                chat_message_id=message_id,
                chat_session_id=str(graph_config.persistence.chat_session_id),
                is_agentic=graph_config.behavior.use_agentic_search,
                message=full_answer,
                update_parent_message=True,
                research_answer_purpose=ResearchAnswerPurpose.ANSWER,
            )

            db_session.commit()

            return OrchestrationSetup(
                original_question=original_question,
                chat_history_string="",
                tools_used=[DRPath.END.value],
                query_list=[],
                assistant_system_prompt=assistant_system_prompt,
                assistant_task_prompt=assistant_task_prompt,
            )

    # Continue, as external knowledge is required.

    clarification = None

    if research_type != ResearchType.THOUGHTFUL:
        result = _get_existing_clarification_request(graph_config)
        if result is not None:
            clarification, original_question, chat_history_string = result
        else:
            # generate clarification questions if needed
            chat_history_string = (
                get_chat_history_string(
                    graph_config.inputs.prompt_builder.message_history,
                    MAX_CHAT_HISTORY_MESSAGES,
                )
                or "(No chat history yet available)"
            )

            base_clarification_prompt = get_dr_prompt_orchestration_templates(
                DRPromptPurpose.CLARIFICATION,
                research_type,
                entity_types_string=all_entity_types,
                relationship_types_string=all_relationship_types,
                available_tools=available_tools,
            )
            clarification_prompt = base_clarification_prompt.build(
                question=original_question,
                chat_history_string=chat_history_string,
            )

            try:
                clarification_response = invoke_llm_json(
                    llm=graph_config.tooling.primary_llm,
                    prompt=create_question_prompt(
                        assistant_system_prompt, clarification_prompt
                    ),
                    schema=ClarificationGenerationResponse,
                    timeout_override=25,
                    # max_tokens=1500,
                )
            except Exception as e:
                logger.error(f"Error in clarification generation: {e}")
                raise e

            if (
                clarification_response.clarification_needed
                and clarification_response.clarification_question
            ):
                clarification = OrchestrationClarificationInfo(
                    clarification_question=clarification_response.clarification_question,
                    clarification_response=None,
                )
                write_custom_event(
                    0,
                    MessageStart(
                        content="",
                        final_documents=None,
                    ),
                    writer,
                )

                write_custom_event(
                    0,
                    MessageDelta(
                        content=clarification_response.clarification_question,
                        type="message_delta",
                    ),
                    writer,
                )

                write_custom_event(
                    0,
                    SectionEnd(
                        type="section_end",
                    ),
                    writer,
                )

                write_custom_event(
                    1,
                    OverallStop(),
                    writer,
                )

                update_db_session_with_messages(
                    db_session=db_session,
                    chat_message_id=message_id,
                    chat_session_id=str(graph_config.persistence.chat_session_id),
                    is_agentic=graph_config.behavior.use_agentic_search,
                    message=clarification_response.clarification_question,
                    update_parent_message=True,
                    research_type=research_type,
                    research_answer_purpose=ResearchAnswerPurpose.CLARIFICATION_REQUEST,
                )

                db_session.commit()

    else:
        chat_history_string = (
            get_chat_history_string(
                graph_config.inputs.prompt_builder.message_history,
                MAX_CHAT_HISTORY_MESSAGES,
            )
            or "(No chat history yet available)"
        )

    if (
        clarification
        and clarification.clarification_question
        and clarification.clarification_response is None
    ):

        update_db_session_with_messages(
            db_session=db_session,
            chat_message_id=message_id,
            chat_session_id=str(graph_config.persistence.chat_session_id),
            is_agentic=graph_config.behavior.use_agentic_search,
            message=clarification.clarification_question,
            update_parent_message=True,
            research_type=research_type,
            research_answer_purpose=ResearchAnswerPurpose.CLARIFICATION_REQUEST,
        )

        db_session.commit()

        next_tool = DRPath.END.value
    else:
        next_tool = DRPath.ORCHESTRATOR.value

    return OrchestrationSetup(
        original_question=original_question,
        chat_history_string=chat_history_string,
        tools_used=[next_tool],
        query_list=[],
        iteration_nr=0,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="clarifier",
                node_start_time=node_start_time,
            )
        ],
        clarification=clarification,
        available_tools=available_tools,
        active_source_types=active_source_types,
        active_source_types_descriptions="\n".join(active_source_types_descriptions),
        assistant_system_prompt=assistant_system_prompt,
        assistant_task_prompt=assistant_task_prompt,
    )
