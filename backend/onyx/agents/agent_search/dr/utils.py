import re

from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage

from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import OrchestrationClarificationInfo
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_section_list,
)
from onyx.context.search.models import InferenceSection


def extract_document_citations(
    citation_string: str, answer: str, claims: list[str] | None = None
) -> tuple[list[int], str, list[str]]:
    """
    Get the cited documents and remove the citations from the answer.
    """

    def _extract_citation_numbers(text: str) -> set[int]:
        """
        Extract all citation numbers from text that contains citations in the format [1] or [1, 2, 3].
        Returns a set of all observed citation numbers.
        """
        citations: set[int] = set()

        # Pattern to match both single citations [1] and multiple citations [1, 2, 3]
        # This regex matches:
        # - \[(\d+)\] for single citations like [1]
        # - \[(\d+(?:,\s*\d+)*)\] for multiple citations like [1, 2, 3]
        pattern = r"\[(\d+(?:,\s*\d+)*)\]"

        for match in re.finditer(pattern, text):
            # Extract the content inside the brackets
            citation_content = match.group(1)

            # Split by comma and extract individual numbers
            numbers = [int(num.strip()) for num in citation_content.split(",")]
            citations.update(numbers)

        return citations

    overall_citation_set = set(
        list(_extract_citation_numbers(citation_string + answer))
        + list(_extract_citation_numbers(" ".join(claims or [])))
    )

    relevant_citation_map = {
        citation: citation_index
        for citation, citation_index in enumerate(list(overall_citation_set), 1)
    }

    # Replace citations in answer with new indices
    def replace_citation(match: re.Match[str]) -> str:
        citation_content = match.group(1)
        numbers = [int(num.strip()) for num in citation_content.split(",")]
        new_numbers = [
            str(relevant_citation_map[num])
            for num in numbers
            if num in relevant_citation_map
        ]
        return f"[{', '.join(new_numbers)}]"

    cleaned_answer = re.sub(r"\[(\d+(?:,\s*\d+)*)\]", replace_citation, answer)

    # Process claims if provided
    cleaned_claims = []
    if claims:
        for claim in claims:
            cleaned_claim = re.sub(r"\[(\d+(?:,\s*\d+)*)\]", replace_citation, claim)
            cleaned_claims.append(cleaned_claim)

    return list(overall_citation_set), cleaned_answer, cleaned_claims


def aggregate_context(
    iteration_responses: list[IterationAnswer],
) -> AggregatedDRContext:
    """
    Aggregate the context from the sub-answers and cited documents.
    """
    # get inference sections from all iterations
    cited_documents: list[InferenceSection] = []
    for iteration_response in iteration_responses:
        for cited_document in iteration_response.cited_documents:
            cited_doc_copy = cited_document.model_copy(deep=True)
            # make sure docs maintains ordering by iteration and question number
            cited_doc_copy.center_chunk.score = 1 - 0.01 * len(cited_documents)
            cited_documents.append(cited_doc_copy)

    # get final inference sections and mapping of document id to index
    cited_documents = dedup_inference_section_list(cited_documents)
    cited_doc_indices = {
        section.center_chunk.document_id: index
        for index, section in enumerate(cited_documents, 1)
    }

    # generate context string
    context_components: list[str] = []
    for question_nr, iteration_response in enumerate(iteration_responses, 1):
        question_text = iteration_response.question
        answer_text = iteration_response.answer
        citation_numbers = [
            cited_doc_indices[cited_document.center_chunk.document_id]
            for cited_document in iteration_response.cited_documents
        ]
        citation_text = (
            "Cited documents: " + "".join(f"[{index}]" for index in citation_numbers)
            if citation_numbers
            else "No citations provided for this answer. Take provided answer at face value."
        )

        context_components.append(f"Question Number: {question_nr}")
        context_components.append(f"Question: {question_text}")
        context_components.append(f"Answer: {answer_text}")
        context_components.append(citation_text)
        context_components.append("\n\n---\n\n")

    # add cited document contents
    context_components.append("Cited document contents:")
    for doc in cited_documents:
        context_components.append(
            build_document_context(doc, cited_doc_indices[doc.center_chunk.document_id])
        )
        context_components.append("\n---\n")

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
            f"Tool: {iteration_response.tool}\n"
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


def get_prompt_question(
    question: str, clarification: OrchestrationClarificationInfo | None
) -> str:
    if clarification:
        clarification_question = clarification.clarification_question
        clarification_response = clarification.clarification_response
        return (
            f"Initial User Question: {question}\n"
            f"(Clarification Question: {clarification_question}\n"
            f"User Response: {clarification_response})"
        )

    return question
