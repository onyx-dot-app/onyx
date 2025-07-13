import re
from typing import cast

from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.context.search.models import InferenceSection


def get_cited_document_numbers(answer: str) -> list[int]:
    """
    Get the document numbers cited in the answer.
    """
    return [int(num) for num in re.findall(r"\[(\d+)\]", answer)]


def aggregate_context(
    iteration_responses: list[
        dict[int, dict[int, dict[str, str | list[InferenceSection]]]]
    ],
) -> str:
    """
    Aggregate the context from the sub-answers and cited documents.
    """
    document_counter = 1
    question_counter = 1

    context_components: list[str] = []

    for iteration_response in iteration_responses:
        for iteration_num, iteration_response_dict in iteration_response.items():
            for question_num, response_dict in iteration_response_dict.items():
                question_text = response_dict["Q"]
                answer_text = response_dict["A"]
                cited_document_list = response_dict["C"]

                if cited_document_list:
                    citation_text_components = ["CITED DOCUMENTS for this question:"]
                    for cited_document in cited_document_list:

                        cited_document = cast(InferenceSection, cited_document)

                        chunk_text = build_document_context(
                            cited_document, document_counter
                        )

                        citation_text_components.append(chunk_text)

                        document_counter += 1

                    citation_text = "\n\n---\n".join(citation_text_components)

                else:
                    citation_text = """No citations provided for this answer. Take \
provided answer at face value."""

                context_components.append(f"Question Number: {question_counter}")
                context_components.append(f"Question: {question_text}")
                context_components.append(f"Answer: {answer_text}")
                context_components.append(citation_text)
                context_components.append("\n\n---\n\n")

                question_counter += 1

    return "\n".join(context_components)


def get_answers_history_from_iteration_responses(
    iteration_responses: list[
        dict[int, dict[int, dict[str, str | list[InferenceSection]]]]
    ],
) -> str:
    """
    Get the answers history from the iteration responses.
    """

    answer_history_list: list[str] = []

    for iteration_response in iteration_responses:
        for iteration_num, iteration_response_dict in iteration_response.items():
            for question_num, response_dict in iteration_response_dict.items():
                question_text = response_dict["Q"]
                answer_text = response_dict["A"]

                answer_history_list.append(
                    f"""Iteration: {iteration_num}\nIteration Question Number: \
{question_num}\nQuestion: {question_text}\nAnswer: {answer_text}"""
                )

    return "\n".join(answer_history_list)
