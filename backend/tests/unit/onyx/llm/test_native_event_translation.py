"""Legacy single-call consumers must preserve native streamed argument fragments."""

import json

from pydantic_ai import messages as pm

from onyx.llm.pydantic_messages import from_pydantic_event


def test_empty_argument_start_does_not_prepend_json_object() -> None:
    events = [
        pm.PartStartEvent(index=1, part=pm.ToolCallPart("weather", "", "call-1")),
        pm.PartDeltaEvent(index=1, delta=pm.ToolCallPartDelta(args_delta='{"city":')),
        pm.PartDeltaEvent(index=1, delta=pm.ToolCallPartDelta(args_delta='"Paris"}')),
    ]
    fragments: list[str] = []
    for event in events:
        chunk = from_pydantic_event(event, pm.ModelResponse(parts=[]))
        assert chunk is not None
        for call in chunk.choice.delta.tool_calls:
            assert call.index == 1
            if call.function and call.function.arguments:
                fragments.append(call.function.arguments)
    assert json.loads("".join(fragments)) == {"city": "Paris"}
