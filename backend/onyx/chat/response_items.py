from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from onyx.agents.execution_records import OperationSnapshot, RunStatus
from onyx.llm.models import (
    AssistantContent,
    AssistantMessage,
    Message,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
)


class ResponseItemKind(str, Enum):
    GENERATION = "generation"
    TEXT = "text"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class TextPurpose(str, Enum):
    COMMENTARY = "commentary"
    ANSWER = "answer"


class ResponseText(BaseModel):
    kind: Literal[ResponseItemKind.TEXT] = ResponseItemKind.TEXT
    text: str
    purpose: TextPurpose = TextPurpose.COMMENTARY


class ResponseReasoning(BaseModel):
    kind: Literal[ResponseItemKind.REASONING] = ResponseItemKind.REASONING
    content: ThinkingContent


class ResponseToolCall(BaseModel):
    kind: Literal[ResponseItemKind.TOOL_CALL] = ResponseItemKind.TOOL_CALL
    call: ToolCall
    status: RunStatus | None = None


class ResponseToolResult(BaseModel):
    kind: Literal[ResponseItemKind.TOOL_RESULT] = ResponseItemKind.TOOL_RESULT
    result: ToolResultMessage


class GenerationOutcome(BaseModel):
    status: RunStatus
    stop_reason: str | None = None
    error_message: str | None = None
    usage: Usage | None = None


class ResponseGeneration(BaseModel):
    kind: Literal[ResponseItemKind.GENERATION] = ResponseItemKind.GENERATION
    outcome: GenerationOutcome


ResponseContent = Annotated[
    ResponseGeneration
    | ResponseText
    | ResponseReasoning
    | ResponseToolCall
    | ResponseToolResult,
    Field(discriminator="kind"),
]


class ResponseItem(BaseModel):
    id: str
    step_index: int = Field(ge=0)
    content: ResponseContent


def build_response_items(
    execution_id: str,
    messages: list[Message],
    operations: list[OperationSnapshot],
    *,
    step_offset: int = 0,
    answer_message_index: int | None = None,
) -> list[ResponseItem]:
    generation_states = {
        op.message_index: op.status for op in operations if op.tool_call_id is None
    }
    tool_states = {
        (op.message_index, op.tool_call_id): op.status
        for op in operations
        if op.tool_call_id is not None
    }
    items: list[ResponseItem] = []
    step = step_offset - 1
    generation_id: str | None = None
    for message_index, message in enumerate(messages):
        if isinstance(message, AssistantMessage):
            step += 1
            generation_id = message.id or f"{execution_id}:{step}"
            items.append(
                ResponseItem(
                    id=generation_id,
                    step_index=step,
                    content=ResponseGeneration(
                        outcome=GenerationOutcome(
                            status=generation_states.get(
                                message_index, RunStatus.COMPLETE
                            ),
                            stop_reason=message.stop_reason,
                            error_message=message.error_message,
                            usage=message.usage.model_copy(deep=True)
                            if message.usage
                            else None,
                        )
                    ),
                )
            )
            purpose = (
                TextPurpose.ANSWER
                if message_index == answer_message_index
                else TextPurpose.COMMENTARY
            )
            for index, block in enumerate(message.content):
                content: ResponseContent
                if isinstance(block, TextContent):
                    content = ResponseText(text=block.text, purpose=purpose)
                elif isinstance(block, ThinkingContent):
                    content = ResponseReasoning(content=block.model_copy(deep=True))
                else:
                    content = ResponseToolCall(
                        call=block.model_copy(deep=True),
                        status=tool_states.get((message_index, block.id)),
                    )
                items.append(
                    ResponseItem(
                        id=f"{generation_id}:{index}",
                        step_index=step,
                        content=content,
                    )
                )
        elif isinstance(message, ToolResultMessage):
            if generation_id is None:
                raise ValueError("Tool output has no preceding generation")
            result = message.model_copy(
                update={"details": None, "metadata": None}
            ).model_copy(deep=True)
            items.append(
                ResponseItem(
                    id=f"{generation_id}:result:{message.tool_call_id}",
                    step_index=step,
                    content=ResponseToolResult(result=result),
                )
            )
        else:
            raise ValueError("Response output must contain assistant or tool messages")
    return items


def messages_from_items(items: list[ResponseItem]) -> list[Message]:
    messages: list[Message] = []
    generation: AssistantMessage | None = None
    step = -1
    results_started = False
    for item in items:
        content = item.content
        if isinstance(content, ResponseGeneration):
            if item.step_index <= step:
                raise ValueError("Response generation boundary is invalid")
            step = item.step_index
            generation = AssistantMessage(
                id=item.id,
                stop_reason=content.outcome.stop_reason,
                error_message=content.outcome.error_message,
                usage=content.outcome.usage.model_copy(deep=True)
                if content.outcome.usage
                else None,
            )
            messages.append(generation)
            results_started = False
            continue
        if item.step_index != step:
            raise ValueError("Response item has no matching generation")
        if isinstance(content, ResponseToolResult):
            messages.append(content.result.model_copy(deep=True))
            results_started = True
            continue
        if generation is None or results_started:
            raise ValueError("Assistant content must precede its tool results")
        block: AssistantContent
        if isinstance(content, ResponseText):
            block = TextContent(text=content.text)
        elif isinstance(content, ResponseReasoning):
            block = content.content.model_copy(deep=True)
        else:
            block = content.call.model_copy(deep=True)
        generation.content.append(block)
    return messages


def answer_message_index(items: list[ResponseItem]) -> int | None:
    """Locate the explicitly selected answer in reconstructed model messages."""
    message_index = -1
    answer_index: int | None = None
    for item in items:
        if isinstance(item.content, (ResponseGeneration, ResponseToolResult)):
            message_index += 1
        elif (
            isinstance(item.content, ResponseText)
            and item.content.purpose == TextPurpose.ANSWER
        ):
            if answer_index is not None and answer_index != message_index:
                raise ValueError("Response contains multiple selected answers")
            answer_index = message_index
    return answer_index


def group_response_items_by_step(
    items: list[ResponseItem],
) -> dict[int, list[ResponseItem]]:
    generations: dict[int, list[ResponseItem]] = {}
    for item in items:
        generations.setdefault(item.step_index, []).append(item)
    return generations
