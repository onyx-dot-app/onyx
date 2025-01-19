import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from typing import cast

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.messages import merge_message_runs

from onyx.agent_search.pro_search_b.answer_initial_sub_question.states import (
    AnswerQuestionOutput,
)
from onyx.agent_search.pro_search_b.base_raw_search.states import BaseRawSearchOutput
from onyx.agent_search.pro_search_b.main.models import FollowUpSubQuestion
from onyx.agent_search.pro_search_b.main.states import BaseDecompUpdate
from onyx.agent_search.pro_search_b.main.states import DecompAnswersUpdate
from onyx.agent_search.pro_search_b.main.states import EntityTermExtractionUpdate
from onyx.agent_search.pro_search_b.main.states import ExpandedRetrievalUpdate
from onyx.agent_search.pro_search_b.main.states import FollowUpSubQuestionsUpdate
from onyx.agent_search.pro_search_b.main.states import InitialAnswerBASEUpdate
from onyx.agent_search.pro_search_b.main.states import InitialAnswerQualityUpdate
from onyx.agent_search.pro_search_b.main.states import InitialAnswerUpdate
from onyx.agent_search.pro_search_b.main.states import MainOutput
from onyx.agent_search.pro_search_b.main.states import MainState
from onyx.agent_search.pro_search_b.main.states import RefinedAnswerUpdate
from onyx.agent_search.pro_search_b.main.states import RequireRefinedAnswerUpdate
from onyx.agent_search.shared_graph_utils.agent_prompt_ops import trim_prompt_piece
from onyx.agent_search.shared_graph_utils.models import AgentAdditionalMetrics
from onyx.agent_search.shared_graph_utils.models import AgentBaseMetrics
from onyx.agent_search.shared_graph_utils.models import AgentChunkStats
from onyx.agent_search.shared_graph_utils.models import AgentRefinedMetrics
from onyx.agent_search.shared_graph_utils.models import AgentTimings
from onyx.agent_search.shared_graph_utils.models import CombinedAgentMetrics
from onyx.agent_search.shared_graph_utils.models import Entity
from onyx.agent_search.shared_graph_utils.models import EntityRelationshipTermExtraction
from onyx.agent_search.shared_graph_utils.models import InitialAgentResultStats
from onyx.agent_search.shared_graph_utils.models import (
    QuestionAnswerResults,
)
from onyx.agent_search.shared_graph_utils.models import RefinedAgentStats
from onyx.agent_search.shared_graph_utils.models import Relationship
from onyx.agent_search.shared_graph_utils.models import Term
from onyx.agent_search.shared_graph_utils.operators import dedup_inference_sections
from onyx.agent_search.shared_graph_utils.prompts import ASSISTANT_SYSTEM_PROMPT_DEFAULT
from onyx.agent_search.shared_graph_utils.prompts import ASSISTANT_SYSTEM_PROMPT_PERSONA
from onyx.agent_search.shared_graph_utils.prompts import DEEP_DECOMPOSE_PROMPT
from onyx.agent_search.shared_graph_utils.prompts import ENTITY_TERM_PROMPT
from onyx.agent_search.shared_graph_utils.prompts import (
    INITIAL_DECOMPOSITION_PROMPT_QUESTIONS,
)
from onyx.agent_search.shared_graph_utils.prompts import INITIAL_RAG_BASE_PROMPT
from onyx.agent_search.shared_graph_utils.prompts import (
    INITIAL_RAG_PROMPT_NO_SUB_QUESTIONS,
)
from onyx.agent_search.shared_graph_utils.prompts import (
    INITIAL_RAG_PROMPT_SUB_QUESTION_SEARCH,
)
from onyx.agent_search.shared_graph_utils.prompts import REVISED_RAG_PROMPT
from onyx.agent_search.shared_graph_utils.prompts import (
    REVISED_RAG_PROMPT_NO_SUB_QUESTIONS,
)
from onyx.agent_search.shared_graph_utils.prompts import (
    SUB_QUESTION_ANSWER_TEMPLATE_REVISED,
)
from onyx.agent_search.shared_graph_utils.prompts import (
    SUB_QUESTION_SEARCH_RESULTS_TEMPLATE,
)
from onyx.agent_search.shared_graph_utils.prompts import UNKNOWN_ANSWER
from onyx.agent_search.shared_graph_utils.utils import dispatch_separated
from onyx.agent_search.shared_graph_utils.utils import format_docs
from onyx.agent_search.shared_graph_utils.utils import format_docs_content_flat
from onyx.agent_search.shared_graph_utils.utils import format_entity_term_extraction
from onyx.agent_search.shared_graph_utils.utils import get_persona_prompt
from onyx.agent_search.shared_graph_utils.utils import make_question_id
from onyx.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import ExtendedToolResponse
from onyx.chat.models import SubQuestionPiece
from onyx.db.chat import log_agent_metrics
from onyx.db.chat import log_agent_sub_question_results
from onyx.tools.tool_implementations.search.search_tool import yield_search_responses
from onyx.utils.logger import setup_logger

# from onyx.agent_search.pro_search_b.main.mod els import CombinedAgentMetrics

logger = setup_logger()


def _dispatch_subquestion(level: int) -> Callable[[str, int], None]:
    def _helper(sub_question_part: str, num: int) -> None:
        dispatch_custom_event(
            "decomp_qs",
            SubQuestionPiece(
                sub_question=sub_question_part,
                level=level,
                level_question_nr=num + 1,
            ),
        )

    return _helper


def initial_sub_question_creation(state: MainState) -> BaseDecompUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------BASE DECOMP START---")

    question = state["config"].search_request.query
    state["db_session"]
    chat_session_id = state["config"].chat_session_id
    primary_message_id = state["config"].message_id

    if not chat_session_id or not primary_message_id:
        raise ValueError(
            "chat_session_id and message_id must be provided for agent search"
        )
    agent_start_time = datetime.now()
    msg = [
        HumanMessage(
            content=INITIAL_DECOMPOSITION_PROMPT_QUESTIONS.format(question=question),
        )
    ]

    # Get the rewritten queries in a defined format
    model = state["fast_llm"]

    # dispatches custom events for subquestion tokens, adding in subquestion ids.
    streamed_tokens = dispatch_separated(model.stream(msg), _dispatch_subquestion(0))

    response = merge_content(*streamed_tokens)

    # this call should only return strings. Commenting out for efficiency
    # assert [type(tok) == str for tok in streamed_tokens]

    # use no-op cast() instead of str() which runs code
    # list_of_subquestions = clean_and_parse_list_string(cast(str, response))
    list_of_subquestions = cast(str, response).split("\n")

    decomp_list: list[str] = [
        sub_question.strip() for sub_question in list_of_subquestions
    ]

    # Persist sub-questions to database
    # from onyx.agent_search.db_operations import create_sub_question

    if state["config"].use_persistence:
        # for sub_q in decomp_list:
        #     sub_questions.append(
        #         create_sub_question(
        #             db_session=db_session,
        #             chat_session_id=chat_session_id,
        #             primary_message_id=primary_message_id,
        #             sub_question=sub_q,
        #         )
        #     )
        pass

    now_end = datetime.now()

    logger.debug(f"--------{now_end}--{now_end - now_start}--------BASE DECOMP END---")

    return BaseDecompUpdate(
        initial_decomp_questions=decomp_list,
        agent_start_time=agent_start_time,
        agent_refined_start_time=None,
        agent_refined_end_time=None,
        agent_refined_metrics=AgentRefinedMetrics(
            refined_doc_boost_factor=None,
            refined_question_boost_factor=None,
            duration__s=None,
        ),
    )


def _calculate_initial_agent_stats(
    decomp_answer_results: list[QuestionAnswerResults],
    original_question_stats: AgentChunkStats,
) -> InitialAgentResultStats:
    initial_agent_result_stats: InitialAgentResultStats = InitialAgentResultStats(
        sub_questions={},
        original_question={},
        agent_effectiveness={},
    )

    orig_verified = original_question_stats.verified_count
    orig_support_score = original_question_stats.verified_avg_scores

    verified_document_chunk_ids = []
    support_scores = 0.0

    for decomp_answer_result in decomp_answer_results:
        verified_document_chunk_ids += (
            decomp_answer_result.sub_question_retrieval_stats.verified_doc_chunk_ids
        )
        if (
            decomp_answer_result.sub_question_retrieval_stats.verified_avg_scores
            is not None
        ):
            support_scores += (
                decomp_answer_result.sub_question_retrieval_stats.verified_avg_scores
            )

    verified_document_chunk_ids = list(set(verified_document_chunk_ids))

    # Calculate sub-question stats
    if (
        verified_document_chunk_ids
        and len(verified_document_chunk_ids) > 0
        and support_scores is not None
    ):
        sub_question_stats: dict[str, float | int | None] = {
            "num_verified_documents": len(verified_document_chunk_ids),
            "verified_avg_score": float(support_scores / len(decomp_answer_results)),
        }
    else:
        sub_question_stats = {"num_verified_documents": 0, "verified_avg_score": None}

    initial_agent_result_stats.sub_questions.update(sub_question_stats)

    # Get original question stats
    initial_agent_result_stats.original_question.update(
        {
            "num_verified_documents": original_question_stats.verified_count,
            "verified_avg_score": original_question_stats.verified_avg_scores,
        }
    )

    # Calculate chunk utilization ratio
    sub_verified = initial_agent_result_stats.sub_questions["num_verified_documents"]

    chunk_ratio: float | None = None
    if sub_verified is not None and orig_verified is not None and orig_verified > 0:
        chunk_ratio = (float(sub_verified) / orig_verified) if sub_verified > 0 else 0.0
    elif sub_verified is not None and sub_verified > 0:
        chunk_ratio = 10.0

    initial_agent_result_stats.agent_effectiveness["utilized_chunk_ratio"] = chunk_ratio

    if (
        orig_support_score is None
        or orig_support_score == 0.0
        and initial_agent_result_stats.sub_questions["verified_avg_score"] is None
    ):
        initial_agent_result_stats.agent_effectiveness["support_ratio"] = None
    elif orig_support_score is None or orig_support_score == 0.0:
        initial_agent_result_stats.agent_effectiveness["support_ratio"] = 10
    elif initial_agent_result_stats.sub_questions["verified_avg_score"] is None:
        initial_agent_result_stats.agent_effectiveness["support_ratio"] = 0
    else:
        initial_agent_result_stats.agent_effectiveness["support_ratio"] = (
            initial_agent_result_stats.sub_questions["verified_avg_score"]
            / orig_support_score
        )

    return initial_agent_result_stats


def generate_initial_answer(state: MainState) -> InitialAnswerUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------GENERATE INITIAL---")

    question = state["config"].search_request.query
    persona_prompt = get_persona_prompt(state["config"].search_request.persona)
    sub_question_docs = state["documents"]
    all_original_question_documents = state["all_original_question_documents"]

    relevant_docs = dedup_inference_sections(
        sub_question_docs, all_original_question_documents
    )

    initial_agent_stats = InitialAgentResultStats(
        sub_questions={},
        original_question={},
        agent_effectiveness={},
    )
    decomp_questions = []
    if len(relevant_docs) == 0:
        dispatch_custom_event(
            "initial_agent_answer",
            AgentAnswerPiece(
                answer_piece=UNKNOWN_ANSWER,
                level=0,
                level_question_nr=0,
                answer_type="agent_level_answer",
            ),
        )

        answer = UNKNOWN_ANSWER

    else:
        # Use the query info from the base document retrieval
        query_infos = [
            result.query_info
            for result in state["original_question_retrieval_results"]
            if result.query_info is not None
        ]
        if len(query_infos) == 0:
            raise ValueError("No query info found")
        for tool_response in yield_search_responses(
            query=question,
            reranked_sections=relevant_docs,
            final_context_sections=relevant_docs,
            search_query_info=query_infos[0],
            get_section_relevance=lambda: None,  # TODO: add relevance
            search_tool=state["search_tool"],
        ):
            dispatch_custom_event(
                "tool_response",
                ExtendedToolResponse(
                    id=tool_response.id,
                    response=tool_response.response,
                    level=0,
                    level_question_nr=0,  # 0, 0 is the base question
                ),
            )

        net_new_original_question_docs = []
        for all_original_question_doc in all_original_question_documents:
            if all_original_question_doc not in sub_question_docs:
                net_new_original_question_docs.append(all_original_question_doc)

        decomp_answer_results = state["decomp_answer_results"]

        good_qa_list: list[str] = []

        sub_question_nr = 1

        for decomp_answer_result in decomp_answer_results:
            decomp_questions.append(decomp_answer_result.question)

            formatted_sub_question_docs = format_docs_content_flat(
                decomp_answer_result.documents
            )

            good_qa_list.append(
                SUB_QUESTION_SEARCH_RESULTS_TEMPLATE.format(
                    sub_question=decomp_answer_result.question,
                    formatted_sub_question_docs=formatted_sub_question_docs,
                    sub_question_nr=sub_question_nr,
                )
            )
            sub_question_nr += 1

        if len(good_qa_list) > 0:
            sub_question_doc_str = "\n\n------\n\n".join(good_qa_list)
        else:
            sub_question_doc_str = ""

        # Determine which persona-specification prompt to use

        if len(persona_prompt) > 0:
            persona_specification = ASSISTANT_SYSTEM_PROMPT_DEFAULT
        else:
            persona_specification = ASSISTANT_SYSTEM_PROMPT_PERSONA.format(
                persona_prompt=persona_prompt
            )

        # Determine which base prompt to use given the sub-question information
        if len(good_qa_list) > 0:
            base_prompt = INITIAL_RAG_PROMPT_SUB_QUESTION_SEARCH
        else:
            base_prompt = INITIAL_RAG_PROMPT_NO_SUB_QUESTIONS

        msg = [
            HumanMessage(
                content=base_prompt.format(
                    question=question,
                    answered_sub_questions=sub_question_doc_str,
                    relevant_docs=format_docs(relevant_docs),
                    persona_specification=persona_specification,
                )
            )
        ]

        model = state["fast_llm"]
        streamed_tokens: list[str | list[str | dict[str, Any]]] = [""]
        for message in model.stream(msg):
            # TODO: in principle, the answer here COULD contain images, but we don't support that yet
            content = message.content
            if not isinstance(content, str):
                raise ValueError(
                    f"Expected content to be a string, but got {type(content)}"
                )
            dispatch_custom_event(
                "initial_agent_answer",
                AgentAnswerPiece(
                    answer_piece=content,
                    level=0,
                    level_question_nr=0,
                    answer_type="agent_level_answer",
                ),
            )
            streamed_tokens.append(content)

        response = merge_content(*streamed_tokens)
        answer = cast(str, response)

        initial_agent_stats = _calculate_initial_agent_stats(
            state["decomp_answer_results"], state["original_question_retrieval_stats"]
        )

        logger.debug(
            f"\n\nYYYYY--Sub-Questions:\n\n{sub_question_doc_str}\n\nStats:\n\n"
        )

        if initial_agent_stats:
            logger.debug(initial_agent_stats.original_question)
            logger.debug(initial_agent_stats.sub_questions)
            logger.debug(initial_agent_stats.agent_effectiveness)

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INITIAL AGENT ANSWER  END---\n\n"
    )

    agent_base_end_time = datetime.now()

    agent_base_metrics = AgentBaseMetrics(
        num_verified_documents_total=len(relevant_docs),
        num_verified_documents_core=state[
            "original_question_retrieval_stats"
        ].verified_count,
        verified_avg_score_core=state[
            "original_question_retrieval_stats"
        ].verified_avg_scores,
        num_verified_documents_base=initial_agent_stats.sub_questions.get(
            "num_verified_documents", None
        ),
        verified_avg_score_base=initial_agent_stats.sub_questions.get(
            "verified_avg_score", None
        ),
        base_doc_boost_factor=initial_agent_stats.agent_effectiveness.get(
            "utilized_chunk_ratio", None
        ),
        support_boost_factor=initial_agent_stats.agent_effectiveness.get(
            "support_ratio", None
        ),
        duration__s=(agent_base_end_time - state["agent_start_time"]).total_seconds(),
    )

    return InitialAnswerUpdate(
        initial_answer=answer,
        initial_agent_stats=initial_agent_stats,
        generated_sub_questions=decomp_questions,
        agent_base_end_time=agent_base_end_time,
        agent_base_metrics=agent_base_metrics,
    )


def initial_answer_quality_check(state: MainState) -> InitialAnswerQualityUpdate:
    """
    Check whether the final output satisfies the original user question

    Args:
        state (messages): The current state

    Returns:
        InitialAnswerQualityUpdate
    """

    now_start = datetime.now()

    logger.debug(
        f"--------{now_start}--------Checking for base answer validity - for not set True/False manually"
    )

    verdict = True

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INITIAL ANSWER QUALITY CHECK END---"
    )

    return InitialAnswerQualityUpdate(initial_answer_quality=verdict)


def entity_term_extraction_llm(state: MainState) -> EntityTermExtractionUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------GENERATE ENTITIES & TERMS---")

    if not state["config"].allow_refinement:
        return EntityTermExtractionUpdate(
            entity_retlation_term_extractions=EntityRelationshipTermExtraction(
                entities=[],
                relationships=[],
                terms=[],
            )
        )

    # first four lines duplicates from generate_initial_answer
    question = state["config"].search_request.query
    sub_question_docs = state["documents"]
    all_original_question_documents = state["all_original_question_documents"]
    relevant_docs = dedup_inference_sections(
        sub_question_docs, all_original_question_documents
    )

    # start with the entity/term/extraction

    doc_context = format_docs(relevant_docs)
    fast_llm = state["fast_llm"]
    doc_context = trim_prompt_piece(
        fast_llm.config, doc_context, ENTITY_TERM_PROMPT + question
    )

    msg = [
        HumanMessage(
            content=ENTITY_TERM_PROMPT.format(question=question, context=doc_context),
        )
    ]

    # Grader
    llm_response_list = list(
        fast_llm.stream(
            prompt=msg,
        )
    )
    llm_response = merge_message_runs(llm_response_list, chunk_separator="")[0].content

    cleaned_response = re.sub(r"```json\n|\n```", "", llm_response)
    parsed_response = json.loads(cleaned_response)

    entities = []
    relationships = []
    terms = []
    for entity in parsed_response.get("retrieved_entities_relationships", {}).get(
        "entities", {}
    ):
        entity_name = entity.get("entity_name", "")
        entity_type = entity.get("entity_type", "")
        entities.append(Entity(entity_name=entity_name, entity_type=entity_type))

    for relationship in parsed_response.get("retrieved_entities_relationships", {}).get(
        "relationships", {}
    ):
        relationship_name = relationship.get("relationship_name", "")
        relationship_type = relationship.get("relationship_type", "")
        relationship_entities = relationship.get("relationship_entities", [])
        relationships.append(
            Relationship(
                relationship_name=relationship_name,
                relationship_type=relationship_type,
                relationship_entities=relationship_entities,
            )
        )

    for term in parsed_response.get("retrieved_entities_relationships", {}).get(
        "terms", {}
    ):
        term_name = term.get("term_name", "")
        term_type = term.get("term_type", "")
        term_similar_to = term.get("term_similar_to", [])
        terms.append(
            Term(
                term_name=term_name,
                term_type=term_type,
                term_similar_to=term_similar_to,
            )
        )

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------ENTITY TERM EXTRACTION END---"
    )

    return EntityTermExtractionUpdate(
        entity_retlation_term_extractions=EntityRelationshipTermExtraction(
            entities=entities,
            relationships=relationships,
            terms=terms,
        )
    )


def generate_initial_base_search_only_answer(
    state: MainState,
) -> InitialAnswerBASEUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------GENERATE INITIAL BASE ANSWER---")

    question = state["config"].search_request.query
    original_question_docs = state["all_original_question_documents"]

    msg = [
        HumanMessage(
            content=INITIAL_RAG_BASE_PROMPT.format(
                question=question,
                context=format_docs(original_question_docs),
            )
        )
    ]

    # Grader
    model = state["fast_llm"]
    response = model.invoke(msg)
    answer = response.pretty_repr()

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INITIAL BASE ANSWER END---\n\n"
    )

    return InitialAnswerBASEUpdate(initial_base_answer=answer)


def ingest_initial_sub_question_answers(
    state: AnswerQuestionOutput,
) -> DecompAnswersUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------INGEST ANSWERS---")
    documents = []
    answer_results = state.get("answer_results", [])
    for answer_result in answer_results:
        documents.extend(answer_result.documents)

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INGEST ANSWERS END---"
    )

    return DecompAnswersUpdate(
        # Deduping is done by the documents operator for the main graph
        # so we might not need to dedup here
        documents=dedup_inference_sections(documents, []),
        decomp_answer_results=answer_results,
    )


def ingest_initial_base_retrieval(
    state: BaseRawSearchOutput,
) -> ExpandedRetrievalUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------INGEST INITIAL RETRIEVAL---")

    sub_question_retrieval_stats = state[
        "base_expanded_retrieval_result"
    ].sub_question_retrieval_stats
    if sub_question_retrieval_stats is None:
        sub_question_retrieval_stats = AgentChunkStats()
    else:
        sub_question_retrieval_stats = sub_question_retrieval_stats

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INGEST INITIAL RETRIEVAL END---"
    )

    return ExpandedRetrievalUpdate(
        original_question_retrieval_results=state[
            "base_expanded_retrieval_result"
        ].expanded_queries_results,
        all_original_question_documents=state[
            "base_expanded_retrieval_result"
        ].all_documents,
        original_question_retrieval_stats=sub_question_retrieval_stats,
    )


def refined_answer_decision(state: MainState) -> RequireRefinedAnswerUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------REFINED ANSWER DECISION---")

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------REFINED ANSWER DECISION END---"
    )

    if not state["config"].allow_refinement or True:
        return RequireRefinedAnswerUpdate(require_refined_answer=True)

    else:
        return RequireRefinedAnswerUpdate(require_refined_answer=True)


def generate_refined_answer(state: MainState) -> RefinedAnswerUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------GENERATE REFINED ANSWER---")

    question = state["config"].search_request.query
    persona_prompt = get_persona_prompt(state["config"].search_request.persona)

    initial_documents = state["documents"]
    revised_documents = state["refined_documents"]

    combined_documents = dedup_inference_sections(initial_documents, revised_documents)

    if len(initial_documents) > 0:
        revision_doc_effectiveness = len(combined_documents) / len(initial_documents)
    elif len(revised_documents) == 0:
        revision_doc_effectiveness = 0.0
    else:
        revision_doc_effectiveness = 10.0

    decomp_answer_results = state["decomp_answer_results"]
    # revised_answer_results = state["refined_decomp_answer_results"]

    good_qa_list: list[str] = []
    decomp_questions = []

    initial_good_sub_questions: list[str] = []
    new_revised_good_sub_questions: list[str] = []

    for decomp_answer_result in decomp_answer_results:
        question_level, _ = parse_question_id(decomp_answer_result.question_id)

        decomp_questions.append(decomp_answer_result.question)
        if (
            decomp_answer_result.quality.lower().startswith("yes")
            and len(decomp_answer_result.answer) > 0
            and decomp_answer_result.answer != UNKNOWN_ANSWER
        ):
            good_qa_list.append(
                SUB_QUESTION_ANSWER_TEMPLATE_REVISED.format(
                    sub_question=decomp_answer_result.question,
                    level_type="revised" if question_level == 1 else "initial",
                    sub_answer=decomp_answer_result.answer,
                )
            )
            if question_level == 0:
                initial_good_sub_questions.append(decomp_answer_result.question)
            else:
                new_revised_good_sub_questions.append(decomp_answer_result.question)

    initial_good_sub_questions = list(set(initial_good_sub_questions))
    new_revised_good_sub_questions = list(set(new_revised_good_sub_questions))
    total_good_sub_questions = list(
        set(initial_good_sub_questions + new_revised_good_sub_questions)
    )
    if len(initial_good_sub_questions) > 0:
        revision_question_efficiency: float = len(total_good_sub_questions) / len(
            initial_good_sub_questions
        )
    elif len(new_revised_good_sub_questions) > 0:
        revision_question_efficiency = 10.0
    else:
        revision_question_efficiency = 1.0

    sub_question_answer_str = "\n\n------\n\n".join(list(set(good_qa_list)))

    # original answer

    initial_answer = state["initial_answer"]

    # Determine which persona-specification prompt to use

    if len(persona_prompt) > 0:
        persona_specification = ASSISTANT_SYSTEM_PROMPT_DEFAULT
    else:
        persona_specification = ASSISTANT_SYSTEM_PROMPT_PERSONA.format(
            persona_prompt=persona_prompt
        )

    # Determine which base prompt to use given the sub-question information
    if len(good_qa_list) > 0:
        base_prompt = REVISED_RAG_PROMPT
    else:
        base_prompt = REVISED_RAG_PROMPT_NO_SUB_QUESTIONS

    msg = [
        HumanMessage(
            content=base_prompt.format(
                question=question,
                answered_sub_questions=sub_question_answer_str,
                relevant_docs=format_docs(combined_documents),
                initial_answer=initial_answer,
                persona_specification=persona_specification,
            )
        )
    ]

    # TODO: stream refined answer
    # Grader
    model = state["fast_llm"]
    response = model.invoke(msg)
    answer = response.pretty_repr()

    # refined_agent_stats = _calculate_refined_agent_stats(
    #     state["decomp_answer_results"], state["original_question_retrieval_stats"]
    # )

    initial_good_sub_questions_str = "\n".join(list(set(initial_good_sub_questions)))
    new_revised_good_sub_questions_str = "\n".join(
        list(set(new_revised_good_sub_questions))
    )

    refined_agent_stats = RefinedAgentStats(
        revision_doc_efficiency=revision_doc_effectiveness,
        revision_question_efficiency=revision_question_efficiency,
    )

    logger.debug(
        f"\n\n---INITIAL ANSWER START---\n\n Answer:\n Agent: {initial_answer}"
    )
    logger.debug("-" * 10)
    logger.debug(f"\n\n---REVISED AGENT ANSWER START---\n\n Answer:\n Agent: {answer}")

    logger.debug("-" * 100)
    logger.debug(f"\n\nINITAL Sub-Questions\n\n{initial_good_sub_questions_str}\n\n")
    logger.debug("-" * 10)
    logger.debug(
        f"\n\nNEW REVISED Sub-Questions\n\n{new_revised_good_sub_questions_str}\n\n"
    )

    logger.debug("-" * 100)

    if state["initial_agent_stats"]:
        initial_doc_boost_factor = state["initial_agent_stats"].agent_effectiveness.get(
            "utilized_chunk_ratio", "--"
        )
        initial_support_boost_factor = state[
            "initial_agent_stats"
        ].agent_effectiveness.get("support_ratio", "--")
        num_initial_verified_docs = state["initial_agent_stats"].original_question.get(
            "num_verified_documents", "--"
        )
        initial_verified_docs_avg_score = state[
            "initial_agent_stats"
        ].original_question.get("verified_avg_score", "--")
        initial_sub_questions_verified_docs = state[
            "initial_agent_stats"
        ].sub_questions.get("num_verified_documents", "--")

        logger.debug("INITIAL AGENT STATS")
        logger.debug(f"Document Boost Factor: {initial_doc_boost_factor}")
        logger.debug(f"Support Boost Factor: {initial_support_boost_factor}")
        logger.debug(f"Originally Verified Docs: {num_initial_verified_docs}")
        logger.debug(
            f"Originally Verified Docs Avg Score: {initial_verified_docs_avg_score}"
        )
        logger.debug(
            f"Sub-Questions Verified Docs: {initial_sub_questions_verified_docs}"
        )
    if refined_agent_stats:
        logger.debug("-" * 10)
        logger.debug("REFINED AGENT STATS")
        logger.debug(
            f"Revision Doc Factor: {refined_agent_stats.revision_doc_efficiency}"
        )
        logger.debug(
            f"Revision Question Factor: {refined_agent_stats.revision_question_efficiency}"
        )

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INITIAL AGENT ANSWER  END---\n\n"
    )

    agent_refined_end_time = datetime.now()
    if state["agent_refined_start_time"]:
        agent_refined_duration = (
            agent_refined_end_time - state["agent_refined_start_time"]
        ).total_seconds()
    else:
        agent_refined_duration = None

    agent_refined_metrics = AgentRefinedMetrics(
        refined_doc_boost_factor=refined_agent_stats.revision_doc_efficiency,
        refined_question_boost_factor=refined_agent_stats.revision_question_efficiency,
        duration__s=agent_refined_duration,
    )

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------REFINED ANSWER UPDATE END---"
    )

    return RefinedAnswerUpdate(
        refined_answer=answer,
        refined_answer_quality=True,  # TODO: replace this with the actual check value
        refined_agent_stats=refined_agent_stats,
        agent_refined_end_time=agent_refined_end_time,
        agent_refined_metrics=agent_refined_metrics,
    )


def refined_sub_question_creation(state: MainState) -> FollowUpSubQuestionsUpdate:
    """ """

    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------FOLLOW UP DECOMPOSE---")

    agent_refined_start_time = datetime.now()

    question = state["config"].search_request.query
    base_answer = state["initial_answer"]

    # get the entity term extraction dict and properly format it
    entity_retlation_term_extractions = state["entity_retlation_term_extractions"]

    entity_term_extraction_str = format_entity_term_extraction(
        entity_retlation_term_extractions
    )

    initial_question_answers = state["decomp_answer_results"]

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
                entity_term_extraction_str=entity_term_extraction_str,
                base_answer=base_answer,
                answered_sub_questions="\n - ".join(addressed_question_list),
                failed_sub_questions="\n - ".join(failed_question_list),
            ),
        )
    ]

    # Grader
    model = state["fast_llm"]

    streamed_tokens = dispatch_separated(model.stream(msg), _dispatch_subquestion(1))
    response = merge_content(*streamed_tokens)

    if isinstance(response, str):
        parsed_response = response.split("\n")
    else:
        raise ValueError("LLM response is not a string")

    refined_sub_question_dict = {}
    for sub_question_nr, sub_question in enumerate(parsed_response):
        refined_sub_question = FollowUpSubQuestion(
            sub_question=sub_question,
            sub_question_id=make_question_id(1, sub_question_nr),
            verified=False,
            answered=False,
            answer="",
        )

        refined_sub_question_dict[sub_question_nr] = refined_sub_question

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------FOLLOW UP DECOMPOSE END---"
    )

    return FollowUpSubQuestionsUpdate(
        refined_sub_questions=refined_sub_question_dict,
        agent_refined_start_time=agent_refined_start_time,
    )


def ingest_refined_answers(
    state: AnswerQuestionOutput,
) -> DecompAnswersUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------INGEST FOLLOW UP ANSWERS---")

    documents = []
    answer_results = state.get("answer_results", [])
    for answer_result in answer_results:
        documents.extend(answer_result.documents)

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INGEST FOLLOW UP ANSWERS END---"
    )

    return DecompAnswersUpdate(
        # Deduping is done by the documents operator for the main graph
        # so we might not need to dedup here
        documents=dedup_inference_sections(documents, []),
        decomp_answer_results=answer_results,
    )


def agent_logging(state: MainState) -> MainOutput:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------LOGGING NODE---")

    agent_start_time = state["agent_start_time"]
    agent_base_end_time = state["agent_base_end_time"]
    agent_refined_start_time = state["agent_refined_start_time"] or None
    agent_refined_end_time = state["agent_refined_end_time"] or None
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

    agent_base_metrics = state["agent_base_metrics"]
    agent_refined_metrics = state["agent_refined_metrics"]

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
    if state["config"].search_request.persona:
        persona_id = state["config"].search_request.persona.id

    user_id = None
    if "user" in state and state["user"]:
        user_id = state["user"].id

    # log the agent metrics
    log_agent_metrics(
        db_session=state["db_session"],
        user_id=user_id,
        persona_id=persona_id,
        agent_type=agent_type,
        start_time=agent_start_time,
        agent_metrics=combined_agent_metrics,
    )

    if state["config"].use_persistence:
        # Persist the sub-answer in the database
        db_session = state["db_session"]
        chat_session_id = state["config"].chat_session_id
        primary_message_id = state["config"].message_id
        sub_question_answer_results = state["decomp_answer_results"]

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

    main_output = MainOutput()

    now_end = datetime.now()

    logger.debug(f"--------{now_end}--{now_end - now_start}--------LOGGING NODE END---")

    return main_output
