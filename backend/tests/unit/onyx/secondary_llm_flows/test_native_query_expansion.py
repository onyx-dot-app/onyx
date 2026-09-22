"""Search helpers use typed native output and retain conversation context."""

from unittest.mock import patch

from pydantic_ai import messages as pm
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from onyx.configs.constants import MessageType
from onyx.llm.pydantic_ai_llm import PydanticAILLM
from onyx.secondary_llm_flows.query_expansion import (
    keyword_query_expansion,
    semantic_query_rephrase,
)
from onyx.tools.models import ChatMinimalTextMessage


def make_llm() -> PydanticAILLM:
    return PydanticAILLM(
        api_key="test",
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=10000,
    )


def test_semantic_query_returns_native_text() -> None:
    llm = make_llm()
    llm.model = TestModel(custom_output_text="setup software Y", call_tools=[])
    with patch.object(llm, "record_usage") as usage:
        query = semantic_query_rephrase(
            [
                ChatMinimalTextMessage(
                    message="How do I set it up?", message_type=MessageType.USER
                )
            ],
            llm,
        )
    assert query == "setup software Y"
    usage.assert_called_once()


def test_keyword_queries_use_validated_list_output() -> None:
    llm = make_llm()
    llm.model = TestModel(custom_output_args={"queries": [" deployment ", "setup"]})
    with patch.object(llm, "record_usage") as usage:
        queries = keyword_query_expansion(
            [
                ChatMinimalTextMessage(
                    message="deployment setup", message_type=MessageType.USER
                )
            ],
            llm,
        )
    assert queries == ["deployment", "setup"]
    usage.assert_called_once()


def test_keyword_output_validation_retries_and_accounts_for_each_request() -> None:
    requests = 0

    def completion(
        _messages: list[pm.ModelMessage], info: AgentInfo
    ) -> pm.ModelResponse:
        nonlocal requests
        requests += 1
        queries = ["one", "two", "three", "four"] if requests == 1 else ["one"]
        return pm.ModelResponse(
            parts=[
                pm.ToolCallPart(
                    info.output_tools[0].name, {"queries": queries}, f"call-{requests}"
                )
            ]
        )

    llm = make_llm()
    llm.model = FunctionModel(completion)
    with patch.object(llm, "record_usage") as usage:
        queries = keyword_query_expansion(
            [ChatMinimalTextMessage(message="find one", message_type=MessageType.USER)],
            llm,
        )
    assert queries == ["one"]
    assert usage.call_count == 2
