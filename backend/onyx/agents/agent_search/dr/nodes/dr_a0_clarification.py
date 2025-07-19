from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.constants import MAX_CHAT_HISTORY_MESSAGES
from onyx.agents.agent_search.dr.models import OrchestrationFeedbackRequest
from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.dr.utils import get_chat_history_string
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.models import TimeBudget
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.configs.constants import MessageType
from onyx.prompts.dr_prompts import GET_FEEDBACK_PROMPT
from onyx.utils.logger import setup_logger

logger = setup_logger()

CLARIFICATION_REQUEST_PREFIX = "PLEASE CLARIFY:"
HIGH_LEVEL_PLAN_PREFIX = "HIGH_LEVEL PLAN:"

AVERAGE_TOOL_COSTS = {
    "SEARCH": 1.0,
    "KNOWLEDGE_GRAPH": 2.0,
    "CLOSER": 0.0,
    "USER_FEEDBACK": 0.0,
}

AVERAGE_TOOL_COST_STRING = "\n".join(
    [f"{tool}: {cost}" for tool, cost in AVERAGE_TOOL_COSTS.items()]
)


def clarifier(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> OrchestrationUpdate:
    """
    Perform a quick search on the question as is and see whether a set of clarification
    questions is needed. For now this is based on the models
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    original_question: str | None = None
    user_feedback: str | None = None

    time_budget = graph_config.behavior.time_budget

    graph_config.behavior.use_agentic_search = False

    feedback_request = OrchestrationFeedbackRequest(
        feedback_needed=False
    )  # remainder is None

    chat_history_string = (
        get_chat_history_string(
            graph_config.inputs.prompt_builder.message_history[:-2],
            MAX_CHAT_HISTORY_MESSAGES,
        )
        or "(No chat history yet available)"
    )
    if time_budget != TimeBudget.FAST:

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

            original_question = graph_config.inputs.prompt_builder.raw_user_query

            get_feedback_prompt = GET_FEEDBACK_PROMPT.replace(
                "---question---", original_question
            ).replace("---chat_history_string---", chat_history_string)

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
                        answer_piece=f"PLEASE CLARIFY: {feedback_request_response.feedback_request}\n\n",
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

        if feedback_request.feedback_needed and not feedback_request.feedback_addressed:
            query_path = DRPath.USER_FEEDBACK

        else:
            query_path = DRPath.ORCHESTRATOR

        original_question_update: str | None = original_question

    else:
        # if time budget is FAST, we do not need to ask for feedback
        # original question is the raw_user_query
        query_path = DRPath.ORCHESTRATOR
        original_question_update = graph_config.inputs.prompt_builder.raw_user_query

    return OrchestrationUpdate(
        original_question=[original_question_update],
        chat_history_string=[chat_history_string],
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
    )
