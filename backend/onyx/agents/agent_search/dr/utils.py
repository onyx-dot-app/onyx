import re

from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage

from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import DRTimeBudget
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import OrchestrationClarificationInfo
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_section_list,
)
from onyx.context.search.models import InferenceSection


def _extract_citation_numbers_from_text(text: str) -> list[int]:
    """
    Extract all citation numbers from text that contains citations in the format [1] or [1, 2, 3].
    Returns a list of all observed citation numbers in order of appearance.
    """
    citations: list[int] = []

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
        citations.extend(numbers)

    return citations


def _replace_citations_with_map(
    text: str, relevant_citation_map: dict[int, int]
) -> str:
    """
    Replace citations in text using a mapping from old citation numbers to new ones.

    Args:
        text: Text containing citations in format [number] or [number, number, ...]
        relevant_citation_map: Mapping from old citation number to new citation number

    Returns:
        Text with citations replaced according to the mapping
    """

    def replace_citation(match: re.Match[str]) -> str:
        citation_content = match.group(1)
        numbers = [int(num.strip()) for num in citation_content.split(",")]

        # Replace each number with its new value from the map
        new_numbers = []
        for num in numbers:
            if num in relevant_citation_map:
                new_numbers.append(str(relevant_citation_map[num]))
            else:
                # Keep original number if not in map
                new_numbers.append(str(num))

        return f"[{', '.join(new_numbers)}]"

    # Pattern to match citations: [number] or [number, number, ...]
    pattern = r"\[(\d+(?:,\s*\d+)*)\]"
    return re.sub(pattern, replace_citation, text)


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
    cleaned_answer = _replace_citations_with_map(answer, relevant_citation_map)

    # Process claims if provided
    cleaned_claims = []
    if claims:
        for claim in claims:
            cleaned_claim = _replace_citations_with_map(claim, relevant_citation_map)
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

    citation_map: dict[int, dict[int, dict[int, str]]] = (
        {}
    )  # map of document id to citation number string in iteration-nr_doc_nr format

    for iteration_response in iteration_responses:
        if iteration_response.iteration_nr not in citation_map:
            citation_map[iteration_response.iteration_nr] = {}
        if (
            iteration_response.parallelization_nr
            not in citation_map[iteration_response.iteration_nr]
        ):
            citation_map[iteration_response.iteration_nr][
                iteration_response.parallelization_nr
            ] = {}

        for response_doc_number, cited_document in enumerate(
            iteration_response.cited_documents, start=1
        ):
            cited_doc_copy = cited_document.model_copy(deep=True)
            # make sure docs maintains ordering by iteration and question number
            cited_doc_copy.center_chunk.score = (
                1 - 0.01 * len(cited_documents) - 0.01 * response_doc_number
            )
            cited_documents.append(cited_doc_copy)

            citation_map[iteration_response.iteration_nr][
                iteration_response.parallelization_nr
            ][response_doc_number] = cited_document.center_chunk.document_id

    # get final inference sections and mapping of document id to index
    cited_documents = dedup_inference_section_list(cited_documents)
    cited_doc_indices = {
        section.center_chunk.document_id: index
        for index, section in enumerate(cited_documents, 1)
    }

    # generate context string
    context_components: list[str] = []
    claim_context_components: list[str] = []

    current_claim_number = 1

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

        if iteration_response.claims is not None:
            for claim in iteration_response.claims:
                # Create mapping from original citation numbers to new citation numbers for this iteration
                citation_mapping = {}
                for response_doc_number, cited_document in enumerate(
                    iteration_response.cited_documents, start=1
                ):
                    doc_id = cited_document.center_chunk.document_id
                    new_citation_number = cited_doc_indices[doc_id]
                    citation_mapping[response_doc_number] = new_citation_number

                claim_with_new_citations = _replace_citations_with_map(
                    text=claim, relevant_citation_map=citation_mapping
                )

                claim_context_components.append(
                    f"Claim {current_claim_number}: {claim_with_new_citations}"
                )
                claim_context_components.append("\n")
                current_claim_number += 1

    # add cited document contents
    context_components.append("Cited document contents:")
    for doc in cited_documents:
        context_components.append(
            build_document_context(doc, cited_doc_indices[doc.center_chunk.document_id])
        )
        context_components.append("\n---\n")

    claim_context = "\n\n".join(claim_context_components)

    return AggregatedDRContext(
        context="\n".join(context_components),
        cited_documents=cited_documents,
        claim_context=claim_context,
    )


def get_answers_history_from_iteration_responses(
    iteration_responses: list[IterationAnswer],
    time_budget: DRTimeBudget,
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
            f"Claims: {iteration_response.claims if iteration_response.claims else 'No claims provided'}"
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


def test_citation_replacement():
    """
    Test function to verify citation replacement works correctly.
    """
    # Test case 1: Single citation
    text1 = "This is a claim with citation [1]"
    mapping1 = {1: 5}
    result1 = _replace_citations_with_map(text1, mapping1)
    print(
        f"Test 1: '{text1}' -> '{result1}' (expected: 'This is a claim with citation [5]')"
    )

    # Test case 2: Multiple citations
    text2 = "This has citations [1, 2, 3] and [4]"
    mapping2 = {1: 10, 2: 20, 3: 30, 4: 40}
    result2 = _replace_citations_with_map(text2, mapping2)
    print(
        f"Test 2: '{text2}' -> '{result2}' (expected: 'This has citations [10, 20, 30] and [40]')"
    )

    # Test case 3: Mixed citations (some in map, some not)
    text3 = "Mixed citations [1, 5, 2] where 5 is not in map"
    mapping3 = {1: 100, 2: 200}
    result3 = _replace_citations_with_map(text3, mapping3)
    print(
        f"Test 3: '{text3}' -> '{result3}' (expected: 'Mixed citations [100, 5, 200] where 5 is not in map')"
    )


if __name__ == "__main__":
    test_citation_replacement()
