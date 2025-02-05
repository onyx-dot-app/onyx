from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search.main.models import (
    AgentAdditionalMetrics,
)
from onyx.agents.agent_search.deep_search.main.models import AgentTimings
from onyx.agents.agent_search.deep_search.main.operations import logger
from onyx.agents.agent_search.deep_search.main.states import MainOutput
from onyx.agents.agent_search.deep_search.main.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.models import CombinedAgentMetrics
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.db.chat import log_agent_metrics
from onyx.db.chat import log_agent_sub_question_results


def persist_agent_results(state: MainState, config: RunnableConfig) -> MainOutput:
    """
    LangGraph node to persist the agent results, including agent logging data.
    """
    node_start_time = datetime.now()

    agent_start_time = state.agent_start_time
    agent_base_end_time = state.agent_base_end_time
    agent_refined_start_time = state.agent_refined_start_time
    agent_refined_end_time = state.agent_refined_end_time
    agent_end_time = agent_refined_end_time or agent_base_end_time

    agent_base_duration = None
    if agent_base_end_time and agent_start_time:
        agent_base_duration = (agent_base_end_time - agent_start_time).total_seconds()

    agent_refined_duration = None
    if agent_refined_start_time and agent_refined_end_time:
        agent_refined_duration = (
            agent_refined_end_time - agent_refined_start_time
        ).total_seconds()

    agent_full_duration = None
    if agent_end_time and agent_start_time:
        agent_full_duration = (agent_end_time - agent_start_time).total_seconds()

    agent_type = "refined" if agent_refined_duration else "base"

    agent_base_metrics = state.agent_base_metrics
    agent_refined_metrics = state.agent_refined_metrics

    combined_agent_metrics = CombinedAgentMetrics(
        timings=AgentTimings(
            base_duration_s=agent_base_duration,
            refined_duration_s=agent_refined_duration,
            full_duration_s=agent_full_duration,
        ),
        base_metrics=agent_base_metrics,
        refined_metrics=agent_refined_metrics,
        additional_metrics=AgentAdditionalMetrics(),
    )

    persona_id = None
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    if graph_config.inputs.search_request.persona:
        persona_id = graph_config.inputs.search_request.persona.id

    user_id = None
    assert (
        graph_config.tooling.search_tool
    ), "search_tool must be provided for agentic search"
    user = graph_config.tooling.search_tool.user
    if user:
        user_id = user.id

    # log the agent metrics
    if graph_config.persistence:
        if agent_base_duration is not None:
            log_agent_metrics(
                db_session=graph_config.persistence.db_session,
                user_id=user_id,
                persona_id=persona_id,
                agent_type=agent_type,
                start_time=agent_start_time,
                agent_metrics=combined_agent_metrics,
            )

        # Persist the sub-answer in the database
        db_session = graph_config.persistence.db_session
        chat_session_id = graph_config.persistence.chat_session_id
        primary_message_id = graph_config.persistence.message_id
        sub_question_answer_results = state.sub_question_results

        log_agent_sub_question_results(
            db_session=db_session,
            chat_session_id=chat_session_id,
            primary_message_id=primary_message_id,
            sub_question_answer_results=sub_question_answer_results,
        )

    main_output = MainOutput(
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="persist agent results",
                node_start_time=node_start_time,
            )
        ],
    )

    for log_message in state.log_messages:
        logger.debug(log_message)

    if state.agent_base_metrics:
        logger.debug(f"Initial loop: {state.agent_base_metrics.duration_s}")
    if state.agent_refined_metrics:
        logger.debug(f"Refined loop: {state.agent_refined_metrics.duration_s}")
    if (
        state.agent_base_metrics
        and state.agent_refined_metrics
        and state.agent_base_metrics.duration_s
        and state.agent_refined_metrics.duration_s
    ):
        logger.debug(
            f"Total time: {float(state.agent_base_metrics.duration_s) + float(state.agent_refined_metrics.duration_s)}"
        )

    return main_output
