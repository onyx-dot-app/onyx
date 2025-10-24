"""Citation context handler for assigning sequential citation numbers to documents."""

import json
from typing import Any

from onyx.chat.turn.models import ChatTurnContext


def assign_citation_numbers(
    agent_turn_messages: list[dict],
    ctx: ChatTurnContext,
) -> list[dict]:
    """Assign citation numbers to LlmDoc objects in agent_turn_messages.

    Iterates through tool response messages and assigns sequential citation numbers
    to any LlmDoc objects that don't already have one.

    Args:
        chat_history: Messages before the current user message (immutable)
        current_user_message: The user message just inputted (immutable)
        agent_turn_messages: Messages generated during this agent turn
        ctx: Chat turn context for tracking citation count

    Returns:
        Updated agent_turn_messages with citation numbers assigned
    """
    updated_messages = []

    for message in agent_turn_messages:
        if message.get("role") == "tool":
            # Parse tool content to find LlmDoc objects
            content = message.get("content")
            if content:
                updated_content = _assign_citations_to_content(content, ctx)
                updated_message = message.copy()
                updated_message["content"] = updated_content
                updated_messages.append(updated_message)
            else:
                updated_messages.append(message)
        else:
            updated_messages.append(message)

    return updated_messages


def _assign_citations_to_content(
    content: str | list[str | dict[str, Any]], ctx: ChatTurnContext
) -> str | list[str | dict[str, Any]]:
    """Assign citation numbers to LlmDoc objects in content.

    Args:
        content: Tool message content (can be string or list)
        ctx: Chat turn context for tracking citation count

    Returns:
        Updated content with citation numbers assigned
    """
    if isinstance(content, str):
        # Try to parse as JSON to find LlmDoc representations
        try:
            parsed = json.loads(content)
            updated = _process_parsed_content(parsed, ctx)
            return json.dumps(updated)
        except (json.JSONDecodeError, TypeError):
            # Not JSON, return as-is
            return content
    elif isinstance(content, list):
        # Process each item in the list
        updated_list = []
        for item in content:
            if isinstance(item, dict):
                updated_list.append(_process_dict_item(item, ctx))
            else:
                updated_list.append(item)
        return updated_list
    else:
        return content


def _process_parsed_content(parsed: Any, ctx: ChatTurnContext) -> Any:
    """Process parsed JSON content to assign citations.

    Args:
        parsed: Parsed JSON content
        ctx: Chat turn context

    Returns:
        Updated parsed content
    """
    if isinstance(parsed, dict):
        return _process_dict_item(parsed, ctx)
    elif isinstance(parsed, list):
        return [_process_parsed_content(item, ctx) for item in parsed]
    else:
        return parsed


def _process_dict_item(item: dict[str, Any], ctx: ChatTurnContext) -> dict[str, Any]:
    """Process a dictionary item to assign citations if it's an LlmDoc.

    Args:
        item: Dictionary that might represent an LlmDoc
        ctx: Chat turn context

    Returns:
        Updated dictionary with citation number if applicable
    """
    # Check if this looks like an LlmDoc by checking for key fields
    if _is_llm_doc_dict(item):
        # Check if citation number is None or missing
        if item.get("document_citation_number") is None:
            ctx.documents_cited_count += 1
            item["document_citation_number"] = ctx.documents_cited_count
    # Recursively process nested dicts
    elif isinstance(item, dict):
        for key, value in item.items():
            if isinstance(value, dict):
                item[key] = _process_dict_item(value, ctx)
            elif isinstance(value, list):
                item[key] = [
                    _process_dict_item(v, ctx) if isinstance(v, dict) else v
                    for v in value
                ]
    return item


def _is_llm_doc_dict(item: dict[str, Any]) -> bool:
    """Check if a dictionary represents an LlmDoc.

    Args:
        item: Dictionary to check

    Returns:
        True if this looks like an LlmDoc
    """
    # An LlmDoc should have these core fields
    required_fields = {"document_id", "content", "semantic_identifier", "source_type"}
    return required_fields.issubset(item.keys())
