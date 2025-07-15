import re

from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage

from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.context.search.models import InferenceSection


def get_cited_document_numbers(answer: str) -> list[int]:
    """
    Get the document numbers cited in the answer.
    """
    return [int(num) for num in re.findall(r"\[(\d+)\]", answer)]


def aggregate_context(
    iteration_responses: list[IterationAnswer],
) -> AggregatedDRContext:
    """
    Aggregate the context from the sub-answers and cited documents.
    """
    document_counter = 0
    question_counter = 0

    context_components: list[str] = []
    cited_documents: list[InferenceSection] = []

    for iteration_response in iteration_responses:
        question_text = iteration_response.question
        answer_text = iteration_response.answer
        cited_document_list = iteration_response.cited_documents

        if cited_document_list:
            citation_text_components = ["CITED DOCUMENTS for this question:"]
            for cited_document in cited_document_list:
                document_counter += 1
                citation_text_components.append(
                    build_document_context(cited_document, document_counter)
                )
                if cited_document.center_chunk.score is not None:
                    cited_document.center_chunk.score -= (
                        iteration_response.iteration_nr - 1
                    )
                for chunk in cited_document.chunks:
                    if chunk.score is not None:
                        chunk.score -= iteration_response.iteration_nr - 1
                cited_documents.append(cited_document)
            citation_text = "\n\n---\n".join(citation_text_components)

        else:
            citation_text = "No citations provided for this answer. Take provided answer at face value."

        question_counter += 1
        context_components.append(f"Question Number: {question_counter}")
        context_components.append(f"Question: {question_text}")
        context_components.append(f"Answer: {answer_text}")
        context_components.append(citation_text)
        context_components.append("\n\n---\n\n")

    return AggregatedDRContext(
        context="\n".join(context_components),
        cited_documents=cited_documents,
    )


def get_answers_history_from_iteration_responses(
    iteration_responses: list[IterationAnswer],
) -> str:
    """
    Get the answers history from the iteration responses.
    """
    return "\n".join(
        (
            f"Iteration: {iteration_response.iteration_nr}\n"
            f"Iteration Question Number: {iteration_response.parallelization_nr}\n"
            f"Question: {iteration_response.question}\n"
            f"Answer: {iteration_response.answer}"
        )
        for iteration_response in sorted(
            iteration_responses,
            key=lambda x: (x.iteration_nr, x.parallelization_nr),
        )
    )


def get_chat_history_string(chat_history: list[BaseMessage], max_messages: int) -> str:
    """
    Get the chat history (up to max_messages) as a string.
    """
    # get past max_messages USER, ASSISTANT message pairs
    past_messages = chat_history[-max_messages * 2 :]
    return (
        "...\n"
        if len(chat_history) > len(past_messages)
        else ""
        "\n".join(
            ("user" if isinstance(msg, HumanMessage) else "you")
            + f": {str(msg.content).strip()}"
            for msg in past_messages
        )
    )
