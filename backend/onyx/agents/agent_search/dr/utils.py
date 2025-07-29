import re

from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage

from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import OrchestrationClarificationInfo
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.context.search.models import InferenceSection

CITATION_PREFIX = "CITE:"


def extract_document_citations(
    answer: str, claims: list[str]
) -> tuple[list[int], str, list[str]]:
    """
    Finds all citations of the form [1], [2, 3], etc. and returns the list of cited indices,
    as well as the answer and claims with the citations replaced with [<CITATION_PREFIX>1],
    etc., to help with citation deduplication later on.
    """
    citations: set[int] = set()

    # Pattern to match both single citations [1] and multiple citations [1, 2, 3]
    # This regex matches:
    # - \[(\d+)\] for single citations like [1]
    # - \[(\d+(?:,\s*\d+)*)\] for multiple citations like [1, 2, 3]
    pattern = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")

    def _extract_and_replace(match: re.Match[str]) -> str:
        numbers = [int(num) for num in match.group(1).split(",")]
        citations.update(numbers)
        return "".join(f"[{CITATION_PREFIX}{num}]" for num in numbers)

    new_answer = pattern.sub(_extract_and_replace, answer)
    new_claims = [pattern.sub(_extract_and_replace, claim) for claim in claims]

    return list(citations), new_answer, new_claims


def aggregate_context(
    iteration_responses: list[IterationAnswer], include_documents: bool = False
) -> AggregatedDRContext:
    """
    Converts the iteration response into a single string with unified citations.
    For example,
        it 1: the answer is x [3][4]. {3: doc_abc, 4: doc_xyz}
        it 2: blah blah [1, 3]. {1: doc_xyz, 3: doc_pqr}
    Output:
        it 1: the answer is x [1][2].
        it 2: blah blah [2][3]
        [1]: doc_xyz
        [2]: doc_abc
        [3]: doc_pqr
    """
    # mapping of document id to citation number
    global_citations: dict[str, int] = {}
    global_documents: list[InferenceSection] = []
    output_strings: list[str] = []

    # build output string
    for iteration_response in sorted(
        iteration_responses,
        key=lambda x: (x.iteration_nr, x.parallelization_nr),
    ):
        output_strings.append(
            f"Iteration: {iteration_response.iteration_nr}, "
            f"Question {iteration_response.parallelization_nr}"
        )
        output_strings.append(f"Tool: {iteration_response.tool.value}")
        output_strings.append(f"Question: {iteration_response.question}")

        answer_str = iteration_response.answer
        claims_str = (
            "".join(f"\n  - {claim}" for claim in iteration_response.claims or [])
            or "No claims provided"
        )

        # compute global citation and replace citation in string
        local_citations = iteration_response.cited_documents
        for local_number, cited_doc in local_citations.items():
            cited_doc_id = cited_doc.center_chunk.document_id
            if cited_doc_id not in global_citations:
                global_documents.append(cited_doc)
                global_citations[cited_doc_id] = len(global_documents)
            global_number = global_citations[cited_doc_id]

            answer_str = answer_str.replace(
                f"[{CITATION_PREFIX}{local_number}]", f"[{global_number}]"
            )
            claims_str = claims_str.replace(
                f"[{CITATION_PREFIX}{local_number}]", f"[{global_number}]"
            )

        output_strings.append(f"Answer: {answer_str}")
        output_strings.append(f"Claims: {claims_str}")
        output_strings.append("\n---\n")

    # add document contents if requested
    if include_documents:
        # note: will probably need to merge sections properly with dedup_inference_section_list
        # at the very start, and use those to build the global citation numbers,
        # if we intend of frequently calling this with include_documents=True
        output_strings.append("Cited document contents:")
        for doc in global_documents:
            output_strings.append(
                build_document_context(
                    doc, global_citations[doc.center_chunk.document_id]
                )
            )
            output_strings.append("\n---\n")

    return AggregatedDRContext(
        context="\n".join(context_components),
        cited_documents=cited_documents,
        claim_context=claim_context,
        questions_answers_claims="\n".join(questions_answers_claims_components),
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
            f"Answer: {iteration_response.answer}\n"
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
