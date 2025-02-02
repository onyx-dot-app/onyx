from datetime import datetime
from typing import Any
from typing import cast

from langchain_core.messages import merge_message_runs
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    AnswerQuestionState,
)
from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    SubQuestionAnswerGenerationUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_sub_question_answer_prompt,
)
from onyx.agents.agent_search.shared_graph_utils.utils import get_answer_citation_ids
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_persona_agent_prompt_expressions,
)
from onyx.agents.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.models import StreamType
from onyx.configs.agent_configs import AGENT_MAX_ANSWER_CONTEXT_DOCS
from onyx.prompts.agent_search import NO_RECOVERED_DOCS
from onyx.utils.logger import setup_logger

logger = setup_logger()


def generate_sub_answer(
    state: AnswerQuestionState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> SubQuestionAnswerGenerationUpdate:
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = state.question
    state.verified_reranked_documents
    level, question_num = parse_question_id(state.question_id)
    context_docs = state.context_documents[:AGENT_MAX_ANSWER_CONTEXT_DOCS]
    persona_contextualized_prompt = get_persona_agent_prompt_expressions(
        graph_config.inputs.search_request.persona
    ).contextualized_prompt

    if len(context_docs) == 0:
        answer_str = NO_RECOVERED_DOCS
        write_custom_event(
            "sub_answers",
            AgentAnswerPiece(
                answer_piece=answer_str,
                level=level,
                level_question_num=question_num,
                answer_type="agent_sub_answer",
            ),
            writer,
        )
    else:
        fast_llm = graph_config.tooling.fast_llm
        msg = build_sub_question_answer_prompt(
            question=question,
            original_question=graph_config.inputs.search_request.query,
            docs=context_docs,
            persona_specification=persona_contextualized_prompt,
            config=fast_llm.config,
        )

        response: list[str | list[str | dict[str, Any]]] = []
        dispatch_timings: list[float] = []
        for message in fast_llm.stream(
            prompt=msg,
        ):
            # TODO: in principle, the answer here COULD contain images, but we don't support that yet
            content = message.content
            if not isinstance(content, str):
                raise ValueError(
                    f"Expected content to be a string, but got {type(content)}"
                )
            start_stream_token = datetime.now()
            write_custom_event(
                "sub_answers",
                AgentAnswerPiece(
                    answer_piece=content,
                    level=level,
                    level_question_num=question_num,
                    answer_type="agent_sub_answer",
                ),
                writer,
            )
            end_stream_token = datetime.now()
            dispatch_timings.append(
                (end_stream_token - start_stream_token).microseconds
            )
            response.append(content)

        answer_str = merge_message_runs(response, chunk_separator="")[0].content
        logger.info(
            f"Average dispatch time: {sum(dispatch_timings) / len(dispatch_timings)}"
        )

    answer_citation_ids = get_answer_citation_ids(answer_str)
    cited_documents = [
        context_docs[id] for id in answer_citation_ids if id < len(context_docs)
    ]

    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type=StreamType.SUB_ANSWER,
        level=level,
        level_question_num=question_num,
    )
    write_custom_event("stream_finished", stop_event, writer)

    return SubQuestionAnswerGenerationUpdate(
        answer=answer_str,
        cited_documents=cited_documents,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="initial - generate individual sub answer",
                node_name="generate sub answer",
                node_start_time=node_start_time,
                result="",
            )
        ],
    )
