"""Model-history replay and stable input message identities."""

from collections import Counter

from onyx.llm.models import (
    AssistantMessage,
    Message,
    ThinkingBlock,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def run_input_message_id(run_id: str, index: int) -> str:
    return f"run:{run_id}:input:{index}"


def completed_tool_call_ids(messages: list[Message], assistant_index: int) -> set[str]:
    result_ids: set[str] = set()
    for index in range(assistant_index + 1, len(messages)):
        following = messages[index]
        if not isinstance(following, ToolResultMessage):
            break
        result_ids.add(following.tool_call_id)
    return result_ids


def messages_for_model(
    messages: list[Message], *, copy_messages: bool = True
) -> list[Message]:
    """Exclude incomplete tool exchanges and unsigned thinking from model history.

    History truncation can drop an assistant tool call while leaving its
    result behind. Providers such as Ollama reject these orphaned results
    with an "unexpected tool call id" error, so omit them from model context.

    Set copy_messages=False only when the caller owns the detached input messages.
    """
    result: list[Message] = []
    accepted: set[str] = set()
    for index, message in enumerate(messages):
        if isinstance(message, AssistantMessage):
            result_ids = completed_tool_call_ids(messages, index)
            call_counts = Counter(call.id for call in message.tool_calls)
            accepted = {
                call_id
                for call_id, count in call_counts.items()
                if count == 1 and call_id in result_ids
            }
            if any(count > 1 for count in call_counts.values()):
                logger.warning(
                    "Omitting ambiguous duplicate tool calls from model context"
                )
            copy = message.model_copy(deep=copy_messages)
            content = []
            for part in copy.content:
                if isinstance(part, ToolCall) and part.id not in accepted:
                    continue
                if isinstance(part, ThinkingContent) and part.blocks:
                    # A provider sends the signature only after its thinking block ends.
                    blocks = [
                        block
                        for block in part.blocks
                        if not isinstance(block, ThinkingBlock) or block.signature
                    ]
                    if len(blocks) != len(part.blocks):
                        logger.debug("Omitting unsigned thinking from model context")
                        if not blocks:
                            continue
                        part = part.model_copy(
                            update={
                                "blocks": blocks,
                                "text": "".join(
                                    block.thinking
                                    for block in blocks
                                    if isinstance(block, ThinkingBlock)
                                ),
                            }
                        )
                content.append(part)
            copy.content = content
            if copy.content:
                result.append(copy)
            else:
                logger.debug(
                    "Omitting an unfinished empty assistant message from model context"
                )
        elif isinstance(message, ToolResultMessage):
            if message.tool_call_id in accepted:
                result.append(
                    message.model_copy(deep=True) if copy_messages else message
                )
                accepted.remove(message.tool_call_id)
            else:
                logger.debug(
                    "Omitting an incomplete tool result from model context: %s",
                    message.tool_call_id,
                )
        else:
            accepted.clear()
            result.append(message.model_copy(deep=True) if copy_messages else message)
    return result
