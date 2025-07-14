from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.states import FinalUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.utils import aggregate_context
from onyx.agents.agent_search.shared_graph_utils.llm import stream_llm_answer
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
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

    try:
        _ = run_with_timeout(
            80,
            lambda: stream_llm_answer(
                llm=config["metadata"]["config"].tooling.primary_llm,
                prompt=final_answer_prompt,
                event_name="basic_response",
                writer=writer,
                agent_answer_level=0,
                agent_answer_question_num=0,
                agent_answer_type="agent_level_answer",
                timeout_override=60,
                max_tokens=None,
            ),
        )
    except Exception as e:
        raise ValueError(f"Error in consolidate_research: {e}")

    return FinalUpdate(
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="closer",
                node_start_time=node_start_time,
            )
        ],
    )
