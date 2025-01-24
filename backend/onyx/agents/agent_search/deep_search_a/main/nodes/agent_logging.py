from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search_a.main.models import AgentAdditionalMetrics
from onyx.agents.agent_search.deep_search_a.main.models import AgentTimings
from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.states import MainOutput
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.models import CombinedAgentMetrics
from onyx.db.chat import log_agent_metrics
from onyx.db.chat import log_agent_sub_question_results


def agent_logging(state: MainState, config: RunnableConfig) -> MainOutput:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------LOGGING NODE---")

    agent_start_time = state.agent_start_time
    agent_base_end_time = state.agent_base_end_time
    agent_refined_start_time = state.agent_refined_start_time or None
    agent_refined_end_time = state.agent_refined_end_time or None
    agent_end_time = agent_refined_end_time or agent_base_end_time

    agent_base_duration = None
    if agent_base_end_time:
        agent_base_duration = (agent_base_end_time - agent_start_time).total_seconds()

    agent_refined_duration = None
    if agent_refined_start_time and agent_refined_end_time:
        agent_refined_duration = (
            agent_refined_end_time - agent_refined_start_time
        ).total_seconds()

    agent_full_duration = None
    if agent_end_time:
        agent_full_duration = (agent_end_time - agent_start_time).total_seconds()

    agent_type = "refined" if agent_refined_duration else "base"

    agent_base_metrics = state.agent_base_metrics
    agent_refined_metrics = state.agent_refined_metrics

    combined_agent_metrics = CombinedAgentMetrics(
        timings=AgentTimings(
            base_duration__s=agent_base_duration,
            refined_duration__s=agent_refined_duration,
            full_duration__s=agent_full_duration,
        ),
        base_metrics=agent_base_metrics,
        refined_metrics=agent_refined_metrics,
        additional_metrics=AgentAdditionalMetrics(),
    )

    persona_id = None
    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    if agent_a_config.search_request.persona:
        persona_id = agent_a_config.search_request.persona.id

    user_id = None
    user = agent_a_config.search_tool.user
    if user:
        user_id = user.id

    # log the agent metrics
    if agent_a_config.db_session is not None:
        log_agent_metrics(
            db_session=agent_a_config.db_session,
            user_id=user_id,
            persona_id=persona_id,
            agent_type=agent_type,
            start_time=agent_start_time,
            agent_metrics=combined_agent_metrics,
        )

        if agent_a_config.use_persistence:
            # Persist the sub-answer in the database
            db_session = agent_a_config.db_session
            chat_session_id = agent_a_config.chat_session_id
            primary_message_id = agent_a_config.message_id
            sub_question_answer_results = state.decomp_answer_results

            log_agent_sub_question_results(
                db_session=db_session,
                chat_session_id=chat_session_id,
                primary_message_id=primary_message_id,
                sub_question_answer_results=sub_question_answer_results,
            )

        # if chat_session_id is not None and primary_message_id is not None and sub_question_id is not None:
        #     create_sub_answer(
        #         db_session=db_session,
        #         chat_session_id=chat_session_id,
        #         primary_message_id=primary_message_id,
        #         sub_question_id=sub_question_id,
        #         answer=answer_str,
        # #     )
        # pass

    now_end = datetime.now()
    main_output = MainOutput(
        log_messages=[
            f"{now_end} -- Main - Logging,  Time taken: {now_end - now_start}"
        ],
    )

    logger.debug(f"--------{now_end}--{now_end - now_start}--------LOGGING NODE END---")
    logger.debug(f"--------{now_end}--{now_end - now_start}--------LOGGING NODE END---")

    return main_output
