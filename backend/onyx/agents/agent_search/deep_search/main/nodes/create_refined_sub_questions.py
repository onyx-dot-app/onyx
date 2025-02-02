from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.main.models import (
    RefinementSubQuestion,
)
from onyx.agents.agent_search.deep_search.main.operations import (
    dispatch_subquestion,
)
from onyx.agents.agent_search.deep_search.main.states import MainState
from onyx.agents.agent_search.deep_search.main.states import (
    RefinedQuestionDecompositionUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_history_prompt,
)
from onyx.agents.agent_search.shared_graph_utils.utils import dispatch_separated
from onyx.agents.agent_search.shared_graph_utils.utils import (
    format_entity_term_extraction,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import make_question_id
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.prompts.agent_search import (
    REFINEMENT_QUESTION_DECOMPOSITION_PROMPT,
)
from onyx.tools.models import ToolCallKickoff


def create_refined_sub_questions(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> RefinedQuestionDecompositionUpdate:
    """ """
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    write_custom_event(
        "start_refined_answer_creation",
        ToolCallKickoff(
            tool_name="agent_search_1",
            tool_args={
                "query": graph_config.inputs.search_request.query,
                "answer": state.initial_answer,
            },
        ),
        writer,
    )

    node_start_time = datetime.now()

    agent_refined_start_time = datetime.now()

    question = graph_config.inputs.search_request.query
    base_answer = state.initial_answer
    history = build_history_prompt(graph_config, question)
    # get the entity term extraction dict and properly format it
    entity_retlation_term_extractions = state.entity_relation_term_extractions

    entity_term_extraction_str = format_entity_term_extraction(
        entity_retlation_term_extractions
    )

    initial_question_answers = state.sub_question_results

    addressed_question_list = [
        x.question for x in initial_question_answers if x.verified_high_quality
    ]

    failed_question_list = [
        x.question for x in initial_question_answers if not x.verified_high_quality
    ]

    msg = [
        HumanMessage(
            content=REFINEMENT_QUESTION_DECOMPOSITION_PROMPT.format(
                question=question,
                history=history,
                entity_term_extraction_str=entity_term_extraction_str,
                base_answer=base_answer,
                answered_sub_questions="\n - ".join(addressed_question_list),
                failed_sub_questions="\n - ".join(failed_question_list),
            ),
        )
    ]

    # Grader
    model = graph_config.tooling.fast_llm

    streamed_tokens = dispatch_separated(
        model.stream(msg), dispatch_subquestion(1, writer)
    )
    response = merge_content(*streamed_tokens)

    if isinstance(response, str):
        parsed_response = [q for q in response.split("\n") if q.strip() != ""]
    else:
        raise ValueError("LLM response is not a string")

    refined_sub_question_dict = {}
    for sub_question_num, sub_question in enumerate(parsed_response):
        refined_sub_question = RefinementSubQuestion(
            sub_question=sub_question,
            sub_question_id=make_question_id(1, sub_question_num + 1),
            verified=False,
            answered=False,
            answer="",
        )

        refined_sub_question_dict[sub_question_num + 1] = refined_sub_question

    return RefinedQuestionDecompositionUpdate(
        refined_sub_questions=refined_sub_question_dict,
        agent_refined_start_time=agent_refined_start_time,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="create refined sub questions",
                node_start_time=node_start_time,
                result=f"Created {len(refined_sub_question_dict)} refined sub questions",
            )
        ],
    )
