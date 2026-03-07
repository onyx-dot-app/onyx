from typing import Any

from litellm.llms.ollama.chat.transformation import OllamaChatCompletionResponseIterator

from onyx.llm.litellm_singleton.monkey_patches import apply_monkey_patches

_UNSET = object()


def _create_iterator() -> OllamaChatCompletionResponseIterator:
    apply_monkey_patches()
    return OllamaChatCompletionResponseIterator(
        streaming_response=iter(()),
        sync_stream=True,
    )


def _build_chunk(
    *,
    thinking: object = _UNSET,
    content: object = _UNSET,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant"}
    if thinking is not _UNSET:
        message["thinking"] = thinking
    if content is not _UNSET:
        message["content"] = content

    return {
        "model": "llama3.1",
        "message": message,
        "done": False,
        "prompt_eval_count": 0,
        "eval_count": 0,
    }


def test_ollama_chunk_parser_transitions_from_native_thinking_to_content() -> None:
    iterator = _create_iterator()

    thinking_chunk = _build_chunk(thinking="Let me think")
    content_chunk = _build_chunk(thinking="", content="Final answer")

    thinking_response = iterator.chunk_parser(thinking_chunk)
    content_response = iterator.chunk_parser(content_chunk)

    assert thinking_response.choices[0].delta.reasoning_content == "Let me think"
    assert thinking_response.choices[0].delta.content is None

    assert getattr(content_response.choices[0].delta, "reasoning_content", None) is None
    assert content_response.choices[0].delta.content == "Final answer"
    assert iterator.finished_reasoning_content is True


def test_ollama_chunk_parser_preserves_content_when_thinking_and_content_coexist() -> (
    None
):
    iterator = _create_iterator()

    combined_chunk = _build_chunk(
        thinking="Need one thought",
        content="Visible answer token",
    )

    response = iterator.chunk_parser(combined_chunk)

    assert response.choices[0].delta.reasoning_content == "Need one thought"
    assert response.choices[0].delta.content == "Visible answer token"
