from pydantic import BaseModel

from onyx.llm.models import (
    ToolResultMessage,
)


def test_message_metadata_is_local_and_result_details_are_serialized() -> None:
    class Details(BaseModel):
        value: str

    message = ToolResultMessage(
        id="result",
        content="visible",
        tool_call_id="call",
        tool_name="echo",
        metadata=Details(value="local"),
        estimated_tokens=42,
        details=Details(value="stored"),
    )
    dumped = message.model_dump()
    assert "metadata" not in dumped and "estimated_tokens" not in dumped
    assert dumped["id"] == "result" and dumped["details"] == {"value": "stored"}


def test_runtime_message_fields_do_not_change_provider_requests() -> None:
    from onyx.llm.interfaces import LLMConfig
    from onyx.llm.model_request import serialize_request
    from onyx.llm.models import GenerationRequest

    class Details(BaseModel):
        value: str

    baseline = ToolResultMessage(
        content="visible", tool_call_id="call", tool_name="echo"
    )
    enriched = baseline.model_copy(
        update={
            "id": "stable-id",
            "metadata": Details(value="private"),
            "estimated_tokens": 42,
            "details": Details(value="artifact"),
            "is_error": True,
            "terminate": True,
        }
    )
    config = LLMConfig(
        model_provider="openai", model_name="test", temperature=0, max_input_tokens=4096
    )
    original, _ = serialize_request(GenerationRequest(messages=[baseline]), config)
    actual, _ = serialize_request(GenerationRequest(messages=[enriched]), config)
    assert actual == original
    assert "private" not in str(actual) and "artifact" not in str(actual)
    assert baseline.model_dump()["id"] is None
    assert baseline.model_dump()["details"] is None
    assert baseline.model_dump()["is_error"] is False
    assert baseline.model_dump()["terminate"] is False
