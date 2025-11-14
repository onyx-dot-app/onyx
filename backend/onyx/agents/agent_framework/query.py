import json
from collections.abc import Iterator
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from onyx.agents.agent_framework.models import RunItemStreamEvent
from onyx.agents.agent_framework.models import StreamEvent
from onyx.agents.agent_framework.models import ToolCallOutputStreamItem
from onyx.agents.agent_framework.models import ToolCallStreamItem
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.model_response import ModelResponseStream
from onyx.tools.tool import RunContextWrapper
from onyx.tools.tool import Tool


@dataclass
class QueryResult:
    stream: Iterator[StreamEvent]
    new_messages_stateful: list[ChatCompletionMessage]


def _update_tool_call_with_delta(
    tool_calls_in_progress: dict[int, dict[str, Any]],
    tool_call_delta: Any,
) -> None:
    index = tool_call_delta.index

    if index not in tool_calls_in_progress:
        tool_calls_in_progress[index] = {
            "id": None,
            "name": None,
            "arguments": "",
        }

    if tool_call_delta.id:
        tool_calls_in_progress[index]["id"] = tool_call_delta.id

    if tool_call_delta.function:
        if tool_call_delta.function.name:
            tool_calls_in_progress[index]["name"] = tool_call_delta.function.name

        if tool_call_delta.function.arguments:
            tool_calls_in_progress[index][
                "arguments"
            ] += tool_call_delta.function.arguments


def query(
    llm_with_default_settings: LLM,
    messages: LanguageModelInput,
    tools: Sequence[Tool],
    context: Any,
    tool_choice: ToolChoiceOptions | None = None,
) -> QueryResult:
    tool_definitions = [tool.tool_definition() for tool in tools]
    tools_by_name = {tool.name: tool for tool in tools}

    new_messages_stateful: list[ChatCompletionMessage] = []

    def stream_generator() -> Iterator[StreamEvent]:
        reasoning_started = False
        message_started = False

        tool_calls_in_progress: dict[int, dict[str, Any]] = {}

        # Accumulate the assistant message content
        content_parts: list[str] = []
        reasoning_parts: list[str] = []

        for chunk in llm_with_default_settings.stream(
            prompt=messages,
            tools=tool_definitions,
            tool_choice=tool_choice,
        ):
            assert isinstance(chunk, ModelResponseStream)

            delta = chunk.choice.delta
            finish_reason = chunk.choice.finish_reason

            if delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)
                if not reasoning_started:
                    yield RunItemStreamEvent(type="reasoning_start")
                    reasoning_started = True

            if delta.content:
                content_parts.append(delta.content)
                if reasoning_started:
                    yield RunItemStreamEvent(type="reasoning_done")
                    reasoning_started = False
                if not message_started:
                    yield RunItemStreamEvent(type="message_start")
                    message_started = True

            if delta.tool_calls:
                if reasoning_started and not message_started:
                    yield RunItemStreamEvent(type="reasoning_done")
                    reasoning_started = False
                if message_started:
                    yield RunItemStreamEvent(type="message_done")
                    message_started = False

                for tool_call_delta in delta.tool_calls:
                    _update_tool_call_with_delta(
                        tool_calls_in_progress, tool_call_delta
                    )

            yield chunk

            if not finish_reason:
                continue
            if message_started:
                yield RunItemStreamEvent(type="message_done")
                message_started = False

            if finish_reason == "tool_calls" and tool_calls_in_progress:
                sorted_tool_calls = sorted(tool_calls_in_progress.items())

                # Build tool calls for the message and execute tools
                assistant_tool_calls = []
                tool_outputs: dict[str, str] = {}

                for _, tool_call_data in sorted_tool_calls:
                    call_id = tool_call_data["id"]
                    name = tool_call_data["name"]
                    arguments_str = tool_call_data["arguments"]

                    assistant_tool_calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": arguments_str,
                            },
                        }
                    )

                    yield RunItemStreamEvent(
                        type="tool_call",
                        details=ToolCallStreamItem(
                            call_id=call_id,
                            name=name,
                            arguments=arguments_str,
                        ),
                    )

                    if name in tools_by_name:
                        tool = tools_by_name[name]
                        arguments = json.loads(arguments_str)

                        run_context = RunContextWrapper(context=context)

                        # TODO: Instead of executing sequentially, execute in parallel
                        # In practice, it's not a must right now since we don't use parallel
                        # tool calls, so kicking the can down the road for now.
                        output = tool.run_v2(run_context, **arguments)
                        tool_outputs[call_id] = output

                        yield RunItemStreamEvent(
                            type="tool_call_output",
                            details=ToolCallOutputStreamItem(
                                call_id=call_id,
                                output=output,
                            ),
                        )

                # Add assistant message with tool calls
                new_messages_stateful.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": assistant_tool_calls,
                    }
                )

                # Add tool response messages
                for _, tool_call_data in sorted_tool_calls:
                    call_id = tool_call_data["id"]

                    if call_id in tool_outputs:
                        new_messages_stateful.append(
                            {
                                "role": "tool",
                                "content": tool_outputs[call_id],
                                "tool_call_id": call_id,
                            }
                        )

            elif finish_reason == "stop" and content_parts:
                # Add assistant message with content
                new_messages_stateful.append(
                    {
                        "role": "assistant",
                        "content": "".join(content_parts),
                    }
                )

    return QueryResult(
        stream=stream_generator(),
        new_messages_stateful=new_messages_stateful,
    )
