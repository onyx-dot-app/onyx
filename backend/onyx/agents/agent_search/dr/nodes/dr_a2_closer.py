from datetime import datetime

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.states import FinalUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.utils import aggregate_context
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.prompts.dr_prompts import FINAL_ANSWER_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def closer(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> FinalUpdate:
    """
    LangGraph node to close the agentic search process and finalize the answer.
    """

    node_start_time = datetime.now()
    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)
    # Also, add missing fields once usage in UI is clear.

    base_question = config["metadata"]["config"].inputs.prompt_builder.raw_user_query

    iteration_responses_string = aggregate_context(state.iteration_responses)

    final_answer_prompt = FINAL_ANSWER_PROMPT.replace(
        "---base_question---", base_question
    ).replace("---iteration_responses_string---", iteration_responses_string)

    msg = [
        HumanMessage(
            content=final_answer_prompt,
        )
    ]

    primary_llm = config["metadata"]["config"].tooling.primary_llm

    try:
        llm_response = run_with_timeout(
            25,
            primary_llm.invoke,
            prompt=msg,
            timeout_override=45,
            max_tokens=1500,
        )

        final_answer = str(llm_response.content).replace("```json\n", "")

    except Exception as e:
        raise ValueError(f"Error in closer: {e}")

    logger.debug(final_answer)

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece="FINAL ANSWER:\n\n" + final_answer,
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    return FinalUpdate(
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="closer",
                node_start_time=node_start_time,
            )
        ],
    )
