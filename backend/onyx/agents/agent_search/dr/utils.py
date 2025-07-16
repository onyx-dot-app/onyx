import re

from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage

from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.context.search.models import InferenceSection


def extract_document_citations(answer: str) -> tuple[list[int], str]:
    """
    Get the cited documents and remove the citations from the answer.
    """
    citations: set[int] = set()

    def replace_and_capture(match: re.Match[str]) -> str:
        num = int(match.group(1))
        citations.add(num)
        return ""

    cleaned_answer = re.sub(r"\[(\d+)\]", replace_and_capture, answer)

    return list(citations), cleaned_answer


def aggregate_context(
    iteration_responses: list[IterationAnswer],
) -> AggregatedDRContext:
    """
    Aggregate the context from the sub-answers and cited documents.
    """
    context_components: list[str] = []
    cited_documents: list[InferenceSection] = []

    cited_doc_indices: dict[str, int] = {}

    for question_counter, iteration_response in enumerate(iteration_responses, 1):
        question_text = iteration_response.question
        answer_text = iteration_response.answer
        cited_document_list = iteration_response.cited_documents

        if cited_document_list:
            citation_text_components = ["CITED DOCUMENTS for this question:"]
            for cited_document in cited_document_list:
                if cited_document.center_chunk.score is not None:
                    cited_document.center_chunk.score -= (
                        iteration_response.iteration_nr - 1
                    )
                for chunk in cited_document.chunks:
                    if chunk.score is not None:
                        chunk.score -= iteration_response.iteration_nr - 1

                section_id = cited_document.center_chunk.unique_id
                if section_id not in cited_doc_indices:
                    cited_doc_indices[section_id] = len(cited_doc_indices) + 1
                    cited_documents.append(cited_document)
                citation_text_components.append(
                    build_document_context(
                        cited_document, cited_doc_indices[section_id]
                    )
                )
            citation_text = "\n\n---\n".join(citation_text_components)

        else:
            citation_text = "No citations provided for this answer. Take provided answer at face value."

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
