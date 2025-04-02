from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.main.models import (
    RefinementSubQuestion,
)
from onyx.agents.agent_search.deep_search.main.operations import dispatch_subquestion
from onyx.agents.agent_search.deep_search.main.operations import (
    dispatch_subquestion_sep,
)
from onyx.agents.agent_search.deep_search.main.states import MainState
from onyx.agents.agent_search.deep_search.main.states import (
    RefinedQuestionDecompositionUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_history_prompt,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AGENT_LLM_RATELIMIT_MESSAGE,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AGENT_LLM_TIMEOUT_MESSAGE,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AgentLLMErrorType,
)
from onyx.agents.agent_search.shared_graph_utils.models import AgentErrorLog
from onyx.agents.agent_search.shared_graph_utils.models import BaseMessage_Content
from onyx.agents.agent_search.shared_graph_utils.models import LLMNodeErrorStrings
from onyx.agents.agent_search.shared_graph_utils.utils import dispatch_separated
from onyx.agents.agent_search.shared_graph_utils.utils import (
    format_entity_term_extraction,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import make_question_id
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import StreamingError
from onyx.configs.agent_configs import AGENT_MAX_TOKENS_SUBQUESTION_GENERATION
from onyx.configs.agent_configs import (
    AGENT_TIMEOUT_CONNECT_LLM_REFINED_SUBQUESTION_GENERATION,
)
from onyx.configs.agent_configs import (
    AGENT_TIMEOUT_LLM_REFINED_SUBQUESTION_GENERATION,
)
from onyx.llm.chat_llm import LLMRateLimitError
from onyx.llm.chat_llm import LLMTimeoutError
from onyx.prompts.agent_search import (
    REFINEMENT_QUESTION_DECOMPOSITION_PROMPT_W_INITIAL_SUBQUESTION_ANSWERS,
)
from onyx.tools.models import ToolCallKickoff
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout
from onyx.utils.timing import log_function_time

logger = setup_logger()

_ANSWERED_SUBQUESTIONS_DIVIDER = "\n\n---\n\n"

_llm_node_error_strings = LLMNodeErrorStrings(
    timeout="The LLM timed out. The sub-questions could not be generated.",
    rate_limit="The LLM encountered a rate limit. The sub-questions could not be generated.",
    general_error="The LLM encountered an error. The sub-questions could not be generated.",
)


@log_function_time(print_only=True)
def create_refined_sub_questions(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> RefinedQuestionDecompositionUpdate:
    """
    LangGraph node to create refined sub-questions based on the initial answer, the history,
    the entity term extraction results found earlier, and the sub-questions that were answered and failed.
    """
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

    addressed_subquestions_with_answers = [
        f"Subquestion: {x.question}\nSubanswer:\n{x.answer}"
        for x in initial_question_answers
        if x.verified_high_quality and x.answer
    ]

    failed_question_list = [
        x.question for x in initial_question_answers if not x.verified_high_quality
    ]

    msg = [
        HumanMessage(
            content=REFINEMENT_QUESTION_DECOMPOSITION_PROMPT_W_INITIAL_SUBQUESTION_ANSWERS.format(
                question=question,
                history=history,
                entity_term_extraction_str=entity_term_extraction_str,
                base_answer=base_answer,
                answered_subquestions_with_answers=_ANSWERED_SUBQUESTIONS_DIVIDER.join(
                    addressed_subquestions_with_answers
                ),
                failed_sub_questions="\n - ".join(failed_question_list),
            ),
        )
    ]

    # Grader
    model = graph_config.tooling.fast_llm

    agent_error: AgentErrorLog | None = None
    streamed_tokens: list[BaseMessage_Content] = []
    try:
        streamed_tokens = run_with_timeout(
            AGENT_TIMEOUT_LLM_REFINED_SUBQUESTION_GENERATION,
            dispatch_separated,
            model.stream(
                msg,
                timeout_override=AGENT_TIMEOUT_CONNECT_LLM_REFINED_SUBQUESTION_GENERATION,
                max_tokens=AGENT_MAX_TOKENS_SUBQUESTION_GENERATION,
            ),
            dispatch_subquestion(1, writer),
            sep_callback=dispatch_subquestion_sep(1, writer),
        )
    except (LLMTimeoutError, TimeoutError):
        agent_error = AgentErrorLog(
            error_type=AgentLLMErrorType.TIMEOUT,
            error_message=AGENT_LLM_TIMEOUT_MESSAGE,
            error_result=_llm_node_error_strings.timeout,
        )
        logger.error("LLM Timeout Error - create refined sub questions")

    except LLMRateLimitError:
        agent_error = AgentErrorLog(
            error_type=AgentLLMErrorType.RATE_LIMIT,
            error_message=AGENT_LLM_RATELIMIT_MESSAGE,
            error_result=_llm_node_error_strings.rate_limit,
        )
        logger.error("LLM Rate Limit Error - create refined sub questions")

    if agent_error:
        refined_sub_question_dict: dict[int, RefinementSubQuestion] = {}
        log_result = agent_error.error_result
        write_custom_event(
            "refined_sub_question_creation_error",
            StreamingError(
                error="Your LLM was not able to create refined sub questions in time and timed out. Please try again.",
            ),
            writer,
        )

    else:
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

        log_result = f"Created {len(refined_sub_question_dict)} refined sub questions"

    return RefinedQuestionDecompositionUpdate(
        refined_sub_questions=refined_sub_question_dict,
        agent_refined_start_time=agent_refined_start_time,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="create refined sub questions",
                node_start_time=node_start_time,
                result=log_result,
            )
        ],
    )
