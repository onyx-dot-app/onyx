import copy
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
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc
from onyx.tools.tool_implementations.web_search.web_search_tool import (
    WebSearchTool,
)


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
    iteration_responses: list[IterationAnswer], include_documents: bool = True
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
    # dedupe and merge inference section contents
    unrolled_inference_sections: list[InferenceSection] = []
    is_internet_marker_dict: dict[str, bool] = {}
    for iteration_response in sorted(
        iteration_responses,
        key=lambda x: (x.iteration_nr, x.parallelization_nr),
    ):

        iteration_tool = iteration_response.tool
        is_internet = iteration_tool == WebSearchTool._NAME

        for cited_doc in iteration_response.cited_documents.values():
            unrolled_inference_sections.append(cited_doc)
            if cited_doc.center_chunk.document_id not in is_internet_marker_dict:
                is_internet_marker_dict[cited_doc.center_chunk.document_id] = (
                    is_internet
                )
            cited_doc.center_chunk.score = None  # None means maintain order

    global_documents = dedup_inference_section_list(unrolled_inference_sections)

    global_citations = {
        doc.center_chunk.document_id: i for i, doc in enumerate(global_documents, 1)
    }

    # build output string
    output_strings: list[str] = []
    global_iteration_responses: list[IterationAnswer] = []

    for iteration_response in sorted(
        iteration_responses,
        key=lambda x: (x.iteration_nr, x.parallelization_nr),
    ):
        # add basic iteration info
        output_strings.append(
            f"Iteration: {iteration_response.iteration_nr}, "
            f"Question {iteration_response.parallelization_nr}"
        )
        output_strings.append(f"Tool: {iteration_response.tool}")
        output_strings.append(f"Question: {iteration_response.question}")

        # get answer and claims with global citations
        answer_str = iteration_response.answer
        claims = iteration_response.claims or []

        iteration_citations: list[int] = []
        for local_number, cited_doc in iteration_response.cited_documents.items():
            global_number = global_citations[cited_doc.center_chunk.document_id]
            # translate local citations to global citations
            answer_str = answer_str.replace(
                f"[{CITATION_PREFIX}{local_number}]", f"[{global_number}]"
            )
            claims = [
                claim.replace(
                    f"[{CITATION_PREFIX}{local_number}]", f"[{global_number}]"
                )
                for claim in claims
            ]
            iteration_citations.append(global_number)

        # add answer, claims, and citation info
        if answer_str:
            output_strings.append(f"Answer: {answer_str}")
        if claims:
            output_strings.append(
                "Claims: " + "".join(f"\n  - {claim}" for claim in claims or [])
                or "No claims provided"
            )
        if not answer_str and not claims:
            output_strings.append(
                "Retrieved documents: "
                + (
                    "".join(
                        f"[{global_number}]"
                        for global_number in sorted(iteration_citations)
                    )
                    or "No documents retrieved"
                )
            )
        output_strings.append("\n---\n")

        # save global iteration response
        iteration_response_copy = iteration_response.model_copy()
        iteration_response_copy.answer = answer_str
        iteration_response_copy.claims = claims
        iteration_response_copy.cited_documents = {
            global_citations[doc.center_chunk.document_id]: doc
            for doc in iteration_response.cited_documents.values()
        }
        global_iteration_responses.append(iteration_response_copy)

    # add document contents if requested
    if include_documents:
        if global_documents:
            output_strings.append("Cited document contents:")
        for doc in global_documents:
            output_strings.append(
                build_document_context(
                    doc, global_citations[doc.center_chunk.document_id]
                )
            )
            output_strings.append("\n---\n")

    return AggregatedDRContext(
        context="\n".join(output_strings),
        cited_documents=global_documents,
        is_internet_marker_dict=is_internet_marker_dict,
        global_iteration_responses=global_iteration_responses,
    )


def get_chat_history_string(chat_history: list[BaseMessage], max_messages: int) -> str:
    """
    Get the chat history (up to max_messages) as a string.
    """
    # get past max_messages USER, ASSISTANT message pairs

    past_messages = chat_history[-max_messages * 2 :]
    filtered_past_messages = copy.deepcopy(past_messages)

    for past_message_number, past_message in enumerate(past_messages):

        if isinstance(past_message.content, list):
            removal_indices = []
            for content_piece_number, content_piece in enumerate(past_message.content):
                if (
                    isinstance(content_piece, dict)
                    and content_piece.get("type") != "text"
                ):
                    removal_indices.append(content_piece_number)

            # Only rebuild the content list if there are items to remove
            if removal_indices:
                filtered_past_messages[past_message_number].content = [
                    content_piece
                    for content_piece_number, content_piece in enumerate(
                        past_message.content
                    )
                    if content_piece_number not in removal_indices
                ]

        else:
            continue

    return (
        "...\n" if len(chat_history) > len(filtered_past_messages) else ""
    ) + "\n".join(
        ("user" if isinstance(msg, HumanMessage) else "you")
        + f": {str(msg.content).strip()}"
        for msg in filtered_past_messages
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


def create_tool_call_string(tool_name: str, query_list: list[str]) -> str:
    """
    Create a string representation of the tool call.
    """
    questions_str = "\n  - ".join(query_list)
    return f"Tool: {tool_name}\n\nQuestions:\n{questions_str}"


def parse_plan_to_dict(plan_text: str) -> dict[str, str]:
    # Convert plan string to numbered dict format
    if not plan_text:
        return {}

    # Split by numbered items (1., 2., 3., etc. or 1), 2), 3), etc.)
    parts = re.split(r"(\d+[.)])", plan_text)
    plan_dict = {}

    for i in range(
        1, len(parts), 2
    ):  # Skip empty first part, then take number and text pairs
        if i + 1 < len(parts):
            number = parts[i].rstrip(".)")  # Remove the dot or parenthesis
            text = parts[i + 1].strip()
            if text:  # Only add if there's actual content
                plan_dict[number] = text

    return plan_dict


def convert_inference_sections_to_search_docs(
    inference_sections: list[InferenceSection],
    is_internet: bool = False,
) -> list[SavedSearchDoc]:
    # Convert InferenceSections to SavedSearchDocs
    search_docs = SearchDoc.from_chunks_or_sections(inference_sections)
    for search_doc in search_docs:
        search_doc.is_internet = is_internet

    retrieved_saved_search_docs = [
        SavedSearchDoc.from_search_doc(search_doc, db_doc_id=0)
        for search_doc in search_docs
    ]
    return retrieved_saved_search_docs
