from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.constants import CLARIFICATION_REQUEST_PREFIX
from onyx.agents.agent_search.dr.constants import MAX_CHAT_HISTORY_MESSAGES
from onyx.agents.agent_search.dr.models import DRTimeBudget
from onyx.agents.agent_search.dr.models import OrchestrationFeedbackRequest
from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.dr.utils import get_chat_history_string
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.configs.constants import MessageType
from onyx.kg.utils.extraction_utils import get_entity_types_str
from onyx.kg.utils.extraction_utils import get_relationship_types_str
from onyx.prompts.dr_prompts import GET_CLARIFICATION_PROMPT
from onyx.tools.tool_implementations.custom.custom_tool import CUSTOM_TOOL_RESPONSE_ID
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    INTERNET_SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    InternetSearchTool,
)
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_available_tools(graph_config: GraphConfig, kg_enabled: bool) -> list[dict]:

    available_tools = []
    for tool in graph_config.tooling.tools:

        if tool.name == "run_kg_search" and not kg_enabled:
            continue

        # TODO: use a pydantic model instead of dict?
        tool_dict = {}
        tool_dict["name"] = tool.name
        tool_dict["description"] = tool.description
        tool_dict["display_name"] = tool.display_name

        if isinstance(tool, CustomTool):
            tool_dict["summary_signature"] = CUSTOM_TOOL_RESPONSE_ID
            tool_dict["path"] = tool.name.upper()
        elif isinstance(tool, InternetSearchTool):
            tool_dict["summary_signature"] = INTERNET_SEARCH_RESPONSE_SUMMARY_ID
            tool_dict["path"] = DRPath.INTERNET_SEARCH.value
        elif isinstance(tool, SearchTool):
            tool_dict["summary_signature"] = SEARCH_RESPONSE_SUMMARY_ID
            tool_dict["path"] = DRPath.SEARCH.value
        # TODO: add proper KG search tool
        elif tool.name == "run_kg_search":
            KG_SEARCH_RESPONSE_SUMMARY_ID = CUSTOM_TOOL_RESPONSE_ID  # unused for now
            tool_dict["summary_signature"] = KG_SEARCH_RESPONSE_SUMMARY_ID
            tool_dict["path"] = DRPath.KNOWLEDGE_GRAPH.value

        available_tools.append(tool_dict)

    return available_tools


def clarifier(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> OrchestrationUpdate:
    """
    Perform a quick search on the question as is and see whether a set of clarification
    questions is needed. For now this is based on the models
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    original_question = graph_config.inputs.prompt_builder.raw_user_query
    user_feedback: str | None = None

    time_budget = graph_config.behavior.time_budget

    # TODO: I don't think this is used in dr, if so remove
    graph_config.behavior.use_agentic_search = False

    kg_enabled = not config["metadata"]["config"].behavior.kg_config_settings.KG_ENABLED

    # get the connected tools and format for the Deep Research flow
    available_tools = _get_available_tools(graph_config, kg_enabled)

    all_entity_types = get_entity_types_str(active=True)
    all_relationship_types = get_relationship_types_str(active=True)

    # by default, go straight to orchestrator
    feedback_request = OrchestrationFeedbackRequest(
        feedback_needed=False
    )  # remainder is None
    query_path = DRPath.ORCHESTRATOR

    chat_history_string = (
        get_chat_history_string(
            graph_config.inputs.prompt_builder.message_history,
            MAX_CHAT_HISTORY_MESSAGES,
        )
        or "(No chat history yet available)"
    )

    # feedback can only be requested if time budget is not FAST
    if time_budget != DRTimeBudget.FAST:
        previous_messages = graph_config.inputs.prompt_builder.message_history
        previous_raw_messages = graph_config.inputs.prompt_builder.raw_message_history

        # check if there is a feedback request in the most recent message history...
        if (
            len(previous_raw_messages) >= 2
            and previous_raw_messages[-1].message_type == MessageType.ASSISTANT
            and CLARIFICATION_REQUEST_PREFIX in previous_raw_messages[-1].message
        ):

            last_message = previous_raw_messages[-1]
            potential_user_feedback_message = (
                graph_config.inputs.prompt_builder.raw_user_query
            )

            feedback_questions = last_message.message.split(
                CLARIFICATION_REQUEST_PREFIX
            )[1].strip()

            user_feedback = potential_user_feedback_message

            # overwrite the overall question, as it has not changed if the last message is
            # a user feedback message
            # ignore here the last two messages and look for the last human message before that
            for previous_message in reversed(previous_messages):
                if (
                    isinstance(previous_message, HumanMessage)
                    and previous_message.content
                    and isinstance(previous_message.content, str)
                ):
                    original_question = previous_message.content
                    break

            feedback_request = OrchestrationFeedbackRequest(
                feedback_needed=True,
                feedback_request=feedback_questions,
                feedback_addressed=True,
                feedback_answer=user_feedback,
            )

            chat_history_string = (
                get_chat_history_string(
                    graph_config.inputs.prompt_builder.message_history[:-2],
                    MAX_CHAT_HISTORY_MESSAGES,
                )
                or "(No chat history yet available)"
            )

        else:
            # ... if not, use the raw_user_query as the original question and ask for feedback
            get_feedback_prompt = (
                GET_CLARIFICATION_PROMPT.replace("---question---", original_question)
                .replace("---possible_entities---", all_entity_types)
                .replace("---possible_relationships---", all_relationship_types)
                .replace("---chat_history_string---", chat_history_string)
            )

            try:
                feedback_request_response = invoke_llm_json(
                    llm=graph_config.tooling.primary_llm,
                    prompt=get_feedback_prompt,
                    schema=OrchestrationFeedbackRequest,
                    timeout_override=25,
                    max_tokens=1500,
                )

                write_custom_event(
                    "basic_response",
                    AgentAnswerPiece(
                        answer_piece=(
                            f"{CLARIFICATION_REQUEST_PREFIX} "
                            f"{feedback_request_response.feedback_request}\n\n"
                        ),
                        level=0,
                        level_question_num=0,
                        answer_type="agent_level_answer",
                    ),
                    writer,
                )

            except Exception as e:
                logger.error(f"Error in feedback request: {e}")
                raise e

            if feedback_request_response.feedback_needed:
                feedback_request = OrchestrationFeedbackRequest(
                    feedback_needed=True,
                    feedback_request=feedback_request_response.feedback_request,
                    feedback_addressed=False,
                    feedback_answer=None,
                )

        query_path = (
            DRPath.END
            if feedback_request.feedback_needed
            and not feedback_request.feedback_addressed
            else DRPath.ORCHESTRATOR
        )

    return OrchestrationUpdate(
        original_question=original_question,
        chat_history_string=chat_history_string,
        query_path=[query_path],
        query_list=[],
        iteration_nr=0,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="clarifier",
                node_start_time=node_start_time,
            )
        ],
        feedback_structure=feedback_request,
        available_tools=available_tools,
    )
