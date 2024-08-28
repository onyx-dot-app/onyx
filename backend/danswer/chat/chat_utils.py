import re
from typing import cast

from sqlalchemy.orm import Session

from danswer.chat.models import CitationInfo
from danswer.chat.models import LlmDoc
from danswer.db.chat import get_chat_messages_by_session
from danswer.db.models import ChatMessage
from danswer.llm.answering.models import PreviousMessage
from danswer.search.models import InferenceSection
from danswer.utils.logger import setup_logger

logger = setup_logger()


def llm_doc_from_inference_section(inference_section: InferenceSection) -> LlmDoc:
    return LlmDoc(
        document_id=inference_section.center_chunk.document_id,
        # This one is using the combined content of all the chunks of the section
        # In default settings, this is the same as just the content of base chunk
        content=inference_section.combined_content,
        blurb=inference_section.center_chunk.blurb,
        semantic_identifier=inference_section.center_chunk.semantic_identifier,
        source_type=inference_section.center_chunk.source_type,
        metadata=inference_section.center_chunk.metadata,
        updated_at=inference_section.center_chunk.updated_at,
        link=inference_section.center_chunk.source_links[0]
        if inference_section.center_chunk.source_links
        else None,
        source_links=inference_section.center_chunk.source_links,
    )


def create_chat_chain(
    chat_session_id: int,
    db_session: Session,
    prefetch_tool_calls: bool = True,
    # Optional id at which we finish processing
    stop_at_message_id: int | None = None,
) -> tuple[ChatMessage, list[ChatMessage]]:
    """Build the linear chain of messages without including the root message"""
    mainline_messages: list[ChatMessage] = []

    all_chat_messages = get_chat_messages_by_session(
        chat_session_id=chat_session_id,
        user_id=None,
        db_session=db_session,
        skip_permission_check=True,
        prefetch_tool_calls=prefetch_tool_calls,
    )
    id_to_msg = {msg.id: msg for msg in all_chat_messages}

    if not all_chat_messages:
        raise RuntimeError("No messages in Chat Session")

    root_message = all_chat_messages[0]
    if root_message.parent_message is not None:
        raise RuntimeError(
            "Invalid root message, unable to fetch valid chat message sequence"
        )

    current_message: ChatMessage | None = root_message
    while current_message is not None:
        child_msg = current_message.latest_child_message

        # Break if at the end of the chain
        # or have reached the `final_id` of the submitted message
        if not child_msg or (
            stop_at_message_id and current_message.id == stop_at_message_id
        ):
            break
        current_message = id_to_msg.get(child_msg)

        if current_message is None:
            raise RuntimeError(
                "Invalid message chain,"
                "could not find next message in the same session"
            )

        mainline_messages.append(current_message)

    if not mainline_messages:
        raise RuntimeError("Could not trace chat message history")

    return mainline_messages[-1], mainline_messages[:-1]


def combine_message_chain(
    messages: list[ChatMessage] | list[PreviousMessage],
    token_limit: int,
    msg_limit: int | None = None,
) -> str:
    """Used for secondary LLM flows that require the chat history,"""
    message_strs: list[str] = []
    total_token_count = 0

    if msg_limit is not None:
        messages = messages[-msg_limit:]

    for message in cast(list[ChatMessage] | list[PreviousMessage], reversed(messages)):
        message_token_count = message.token_count

        if total_token_count + message_token_count > token_limit:
            break

        role = message.message_type.value.upper()
        message_strs.insert(0, f"{role}:\n{message.message}")
        total_token_count += message_token_count

    return "\n\n".join(message_strs)


def reorganize_citations(
    answer: str, citations: list[CitationInfo]
) -> tuple[str, list[CitationInfo]]:
    """For a complete, citation-aware response, we want to reorganize the citations so that
    they are in the order of the documents that were used in the response. This just looks nicer / avoids
    confusion ("Why is there [7] when only 2 documents are cited?")."""

    # Regular expression to find all instances of [[x]](LINK)
    pattern = r"\[\[(.*?)\]\]\((.*?)\)"

    all_citation_matches = re.findall(pattern, answer)

    new_citation_info: dict[int, CitationInfo] = {}
    for citation_match in all_citation_matches:
        try:
            citation_num = int(citation_match[0])
            if citation_num in new_citation_info:
                continue

            matching_citation = next(
                iter([c for c in citations if c.citation_num == int(citation_num)]),
                None,
            )
            if matching_citation is None:
                continue

            new_citation_info[citation_num] = CitationInfo(
                citation_num=len(new_citation_info) + 1,
                document_id=matching_citation.document_id,
            )
        except Exception:
            pass

    # Function to replace citations with their new number
    def slack_link_format(match: re.Match) -> str:
        link_text = match.group(1)
        try:
            citation_num = int(link_text)
            if citation_num in new_citation_info:
                link_text = new_citation_info[citation_num].citation_num
        except Exception:
            pass

        link_url = match.group(2)
        return f"[[{link_text}]]({link_url})"

    # Substitute all matches in the input text
    new_answer = re.sub(pattern, slack_link_format, answer)

    # if any citations weren't parsable, just add them back to be safe
    for citation in citations:
        if citation.citation_num not in new_citation_info:
            new_citation_info[citation.citation_num] = citation

    return new_answer, list(new_citation_info.values())
