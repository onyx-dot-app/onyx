from onyx.agents.agent_search.shared_graph_utils.models import (
    SubQuestionAnswerResults,
)
from onyx.chat.prune_and_merge import _merge_sections
from onyx.context.search.models import InferenceSection


def dedup_inference_sections(
    list1: list[InferenceSection], list2: list[InferenceSection]
) -> list[InferenceSection]:
    deduped = _merge_sections(list1 + list2)
    return deduped


def dedup_inference_section_list(
    list: list[InferenceSection],
) -> list[InferenceSection]:
    deduped = _merge_sections(list)
    return deduped


def dedup_question_answer_results(
    question_answer_results_1: list[SubQuestionAnswerResults],
    question_answer_results_2: list[SubQuestionAnswerResults],
) -> list[SubQuestionAnswerResults]:
    deduped_question_answer_results: list[SubQuestionAnswerResults] = (
        question_answer_results_1
    )
    utilized_question_ids: set[str] = set(
        [x.question_id for x in question_answer_results_1]
    )

    for question_answer_result in question_answer_results_2:
        if question_answer_result.question_id not in utilized_question_ids:
            deduped_question_answer_results.append(question_answer_result)
            utilized_question_ids.add(question_answer_result.question_id)

    return deduped_question_answer_results
