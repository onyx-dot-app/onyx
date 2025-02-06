from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.initial.generate_initial_answer.states import (
    SubQuestionRetrievalState,
)
from onyx.agents.agent_search.deep_search.main.models import (
    AgentRefinedMetrics,
)
from onyx.agents.agent_search.deep_search.main.operations import dispatch_subquestion
from onyx.agents.agent_search.deep_search.main.operations import (
    dispatch_subquestion_sep,
)
from onyx.agents.agent_search.deep_search.main.states import (
    InitialQuestionDecompositionUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_history_prompt,
)
from onyx.agents.agent_search.shared_graph_utils.utils import dispatch_separated
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.models import StreamType
from onyx.chat.models import SubQuestionPiece
from onyx.configs.agent_configs import AGENT_NUM_DOCS_FOR_DECOMPOSITION
from onyx.prompts.agent_search import (
    INITIAL_DECOMPOSITION_PROMPT_QUESTIONS_AFTER_SEARCH,
)
from onyx.prompts.agent_search import (
    INITIAL_QUESTION_DECOMPOSITION_PROMPT,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def decompose_orig_question(
    state: SubQuestionRetrievalState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> InitialQuestionDecompositionUpdate:
    """
    LangGraph node to decompose the original question into sub-questions.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.search_request.query
    perform_initial_search_decomposition = (
        graph_config.behavior.perform_initial_search_decomposition
    )
    # Get the rewritten queries in a defined format
    model = graph_config.tooling.fast_llm

    history = build_history_prompt(graph_config, question)

    # Use the initial search results to inform the decomposition
    agent_start_time = datetime.now()

    # Initial search to inform decomposition. Just get top 3 fits

    if perform_initial_search_decomposition:
        # Due to unfortunate state representation in LangGraph, we need here to double check that the retrieval has
        # happened prior to this point, allowing silent failure here since it is not critical for decomposition in
        # all queries.
        if not state.exploratory_search_results:
            logger.error("Initial search for decomposition failed")

        sample_doc_str = "\n\n".join(
            [
                doc.combined_content
                for doc in state.exploratory_search_results[
                    :AGENT_NUM_DOCS_FOR_DECOMPOSITION
                ]
            ]
        )

        decomposition_prompt = (
            INITIAL_DECOMPOSITION_PROMPT_QUESTIONS_AFTER_SEARCH.format(
                question=question, sample_doc_str=sample_doc_str, history=history
            )
        )

    else:
        decomposition_prompt = INITIAL_QUESTION_DECOMPOSITION_PROMPT.format(
            question=question, history=history
        )

    # Start decomposition

    msg = [HumanMessage(content=decomposition_prompt)]

    # Send the initial question as a subquestion with number 0
    write_custom_event(
        "decomp_qs",
        SubQuestionPiece(
            sub_question=question,
            level=0,
            level_question_num=0,
        ),
        writer,
    )

    # dispatches custom events for subquestion tokens, adding in subquestion ids.
    streamed_tokens = dispatch_separated(
        model.stream(msg),
        dispatch_subquestion(0, writer),
        sep_callback=dispatch_subquestion_sep(0, writer),
    )

    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type=StreamType.SUB_QUESTIONS,
        level=0,
    )
    write_custom_event("stream_finished", stop_event, writer)

    deomposition_response = merge_content(*streamed_tokens)

    # this call should only return strings. Commenting out for efficiency
    # assert [type(tok) == str for tok in streamed_tokens]

    # use no-op cast() instead of str() which runs code
    # list_of_subquestions = clean_and_parse_list_string(cast(str, response))
    list_of_subqs = cast(str, deomposition_response).split("\n")

    decomp_list: list[str] = [sq.strip() for sq in list_of_subqs if sq.strip() != ""]

    return InitialQuestionDecompositionUpdate(
        initial_sub_questions=decomp_list,
        agent_start_time=agent_start_time,
        agent_refined_start_time=None,
        agent_refined_end_time=None,
        agent_refined_metrics=AgentRefinedMetrics(
            refined_doc_boost_factor=None,
            refined_question_boost_factor=None,
            duration_s=None,
        ),
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="initial - generate sub answers",
                node_name="decompose original question",
                node_start_time=node_start_time,
                result=f"decomposed original question into {len(decomp_list)} subquestions",
            )
        ],
    )
