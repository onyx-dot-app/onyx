from datetime import datetime
from typing import cast

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search_a.main.models import FollowUpSubQuestion
from onyx.agents.agent_search.deep_search_a.main.operations import dispatch_subquestion
from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.states import (
    FollowUpSubQuestionsUpdate,
)
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_history_prompt,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import DEEP_DECOMPOSE_PROMPT
from onyx.agents.agent_search.shared_graph_utils.utils import dispatch_separated
from onyx.agents.agent_search.shared_graph_utils.utils import format_docs
from onyx.agents.agent_search.shared_graph_utils.utils import make_question_id
from onyx.configs.agent_configs import AGENT_NUM_DOCS_FOR_REFINED_DECOMPOSITION
from onyx.tools.models import ToolCallKickoff


def refined_sub_question_creation(
    state: MainState, config: RunnableConfig
) -> FollowUpSubQuestionsUpdate:
    """ """
    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    dispatch_custom_event(
        "start_refined_answer_creation",
        ToolCallKickoff(
            tool_name="agent_search_1",
            tool_args={
                "query": agent_a_config.search_request.query,
                "answer": state.initial_answer,
            },
        ),
    )

    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------FOLLOW UP DECOMPOSE---")

    agent_refined_start_time = datetime.now()

    question = agent_a_config.search_request.query
    base_answer = state.initial_answer
    history = build_history_prompt(agent_a_config.prompt_builder)
    # get the entity term extraction dict and properly format it
    # entity_retlation_term_extractions = state.entity_relation_term_extractions

    # entity_term_extraction_str = format_entity_term_extraction(
    #     entity_retlation_term_extractions
    # )

    docs_str = format_docs(
        state.all_original_question_documents[:AGENT_NUM_DOCS_FOR_REFINED_DECOMPOSITION]
    )

    initial_question_answers = state.decomp_answer_results

    addressed_question_list = [
        x.question for x in initial_question_answers if "yes" in x.quality.lower()
    ]

    failed_question_list = [
        x.question for x in initial_question_answers if "no" in x.quality.lower()
    ]

    msg = [
        HumanMessage(
            content=DEEP_DECOMPOSE_PROMPT.format(
                question=question,
                history=history,
                docs_str=docs_str,
                base_answer=base_answer,
                answered_sub_questions="\n - ".join(addressed_question_list),
                failed_sub_questions="\n - ".join(failed_question_list),
            ),
        )
    ]

    # Grader
    model = agent_a_config.fast_llm

    streamed_tokens = dispatch_separated(model.stream(msg), dispatch_subquestion(1))
    response = merge_content(*streamed_tokens)

    if isinstance(response, str):
        parsed_response = [q for q in response.split("\n") if q.strip() != ""]
    else:
        raise ValueError("LLM response is not a string")

    refined_sub_question_dict = {}
    for sub_question_nr, sub_question in enumerate(parsed_response):
        refined_sub_question = FollowUpSubQuestion(
            sub_question=sub_question,
            sub_question_id=make_question_id(1, sub_question_nr + 1),
            verified=False,
            answered=False,
            answer="",
        )

        refined_sub_question_dict[sub_question_nr + 1] = refined_sub_question

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------FOLLOW UP DECOMPOSE END---"
    )

    return FollowUpSubQuestionsUpdate(
        refined_sub_questions=refined_sub_question_dict,
        agent_refined_start_time=agent_refined_start_time,
    )
