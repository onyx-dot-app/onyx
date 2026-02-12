from litellm.llms.ollama.chat.transformation import OllamaChatCompletionResponseIterator
from litellm.llms.ollama.chat.transformation import OllamaChatConfig

from onyx.llm.litellm_singleton.monkey_patches import apply_monkey_patches


def test_ollama_chunk_parser_preserves_existing_tool_call_id() -> None:
    apply_monkey_patches()

    iterator = OllamaChatCompletionResponseIterator(
        streaming_response=iter(()),
        sync_stream=True,
    )

    chunk = {
        "model": "mistral",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "fae19e3fb",
                    "function": {
                        "name": "search",
                        "arguments": {"query": "test"},
                    },
                }
            ],
        },
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 1,
        "eval_count": 1,
    }

    parsed = iterator.chunk_parser(chunk)

    assert parsed.choices[0].delta.tool_calls is not None
    assert parsed.choices[0].delta.tool_calls[0]["id"] == "fae19e3fb"
    assert parsed.choices[0].finish_reason == "tool_calls"


def test_ollama_transform_request_preserves_tool_call_linkage_fields() -> None:
    apply_monkey_patches()

    config = OllamaChatConfig()

    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "fae19e3fb",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": '{"query":"weather"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "fae19e3fb",
            "content": '{"results": []}',
        },
    ]

    request_data = config.transform_request(
        model="mistral",
        messages=messages,
        optional_params={"stream": True},
        litellm_params={},
        headers={},
    )

    transformed_messages = request_data["messages"]

    assert transformed_messages[0]["tool_calls"][0]["id"] == "fae19e3fb"
    assert transformed_messages[0]["tool_calls"][0]["function"]["name"] == "search"
    assert transformed_messages[1]["tool_call_id"] == "fae19e3fb"
